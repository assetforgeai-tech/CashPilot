"""Account-scoped EarnApp collector orchestration."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

from app import database, earnapp_canary
from app.collectors.earnapp import EarnAppAccountCollector

logger = logging.getLogger(__name__)
_COLLECTABLE_STATES = frozenset({"ACTIVE", "AUTH_FAILED"})


async def ensure_collection_route(account_id: int) -> dict[str, Any] | None:
    """Prefer a healthy node route; create control-only capacity before node one."""
    node_routes = await database.get_earnapp_account_node_routes(account_id, healthy_only=True)
    if node_routes:
        return {**node_routes[0], "source": "node"}

    all_nodes = await database.get_earnapp_account_node_routes(account_id, healthy_only=False)
    if all_nodes:
        # Once an account owns nodes, collector traffic must stay on one of those
        # routes. A dead node route is a routing failure, not permission to give
        # the account an unrelated second egress.
        return None

    route = await database.get_earnapp_account_control_route(account_id, healthy_only=True)
    if route:
        return {**route, "source": "account_control"}
    stale_route = await database.get_earnapp_account_control_route(account_id)
    if stale_route:
        await database.release_earnapp_account_control_route(
            account_id,
            expected_proxy_id=int(stale_route["proxy_id"]),
            reason="EARNAPP_CONTROL_ROUTE_UNHEALTHY",
        )
    route = await database.lease_earnapp_account_control_proxy(account_id)
    return {**route, "source": "account_control"} if route else None


async def _collection_routes(account_id: int) -> list[dict[str, Any]]:
    """Return ordered account-owned routes, retaining a control route fallback."""
    node_routes = await database.get_earnapp_account_node_routes(account_id, healthy_only=True)
    if node_routes:
        return [{**route, "source": "node"} for route in node_routes]
    route = await ensure_collection_route(account_id)
    return [route] if route else []


async def collect_account(account_id: int, *, reuse_recent_seconds: int = 0) -> dict[str, Any]:
    async with earnapp_canary.account_api_lock(account_id):
        account = await database.get_earnapp_account_credentials(account_id)
        if not account:
            return {"status": "error", "error_kind": "auth", "error": "EarnApp account unavailable"}
        if reuse_recent_seconds > 0:
            recent = await database.get_latest_earnapp_snapshot(account_id)
            collected_at = str((recent or {}).get("collected_at") or "")
            try:
                collected_when = datetime.fromisoformat(collected_at.replace("Z", "+00:00"))
                if collected_when.tzinfo is None:
                    collected_when = collected_when.replace(tzinfo=UTC)
            except (TypeError, ValueError):
                collected_when = None
            if (
                recent
                and recent.get("status") == "ok"
                and collected_when
                and datetime.now(UTC) - collected_when <= timedelta(seconds=int(reuse_recent_seconds))
            ):
                return {"status": "ok", "source": "recent_snapshot"}
        routes = await _collection_routes(account_id)
        if not routes:
            return {"status": "error", "error_kind": "route", "error": "EarnApp account proxy unavailable"}
        last_snapshot: dict[str, Any] = {"status": "error", "error_kind": "route", "error": "EarnApp route unavailable"}
        for route in routes:
            snapshot = await EarnAppAccountCollector(account.get("credentials") or {}, route).collect_snapshot()
            if snapshot.get("status") == "ok":
                await database.save_earnapp_snapshot(account_id, snapshot)
                if account.get("id") is not None:
                    await database.record_earnapp_auth_result(account_id, success=True)
                return snapshot
            last_snapshot = snapshot
            if snapshot.get("error_kind") == "auth":
                failure_kind = str(snapshot.get("auth_failure_kind") or "AUTH_FAILED").upper()
                if account.get("id") is not None:
                    await database.record_earnapp_auth_result(
                        account_id,
                        success=False,
                        failure_kind=failure_kind,
                    )
                return snapshot
        return last_snapshot


async def _payment_collector(account_id: int) -> EarnAppAccountCollector:
    account = await database.get_earnapp_account_credentials(account_id)
    if not account:
        raise ValueError("EarnApp account unavailable")
    routes = await _collection_routes(account_id)
    if not routes:
        raise ValueError("EarnApp account proxy unavailable")
    return EarnAppAccountCollector(account.get("credentials") or {}, routes[0])


async def configure_payment(account_id: int, *, payment_method: str, destination: str) -> dict[str, Any]:
    async with earnapp_canary.account_api_lock(account_id):
        collector = await _payment_collector(account_id)
        return await collector.configure_payment(payment_method=payment_method, destination=destination)


async def configure_payment_from_paypal_pool(
    account_id: int, *, snapshot: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Assign one fixed PayPal destination, then enable it on EarnApp."""
    snapshot = snapshot or await database.get_latest_earnapp_snapshot(account_id)
    payment = (snapshot or {}).get("payment") if isinstance(snapshot, Mapping) else None
    if not isinstance(payment, Mapping):
        try:
            payment = json.loads(str((snapshot or {}).get("payment_json") or "{}"))
        except (TypeError, ValueError):
            payment = {}
    methods = payment.get("methods") if isinstance(payment, dict) else []
    paypal = next(
        (item for item in methods if isinstance(item, dict) and "paypal" in str(item.get("id") or "").casefold()),
        None,
    )
    if not paypal:
        raise ValueError("EarnApp PayPal payment method is unavailable")
    assigned = await database.assign_earnapp_paypal(account_id)
    if not assigned:
        raise ValueError("no available PayPal account in pool")
    return await configure_payment(
        account_id,
        payment_method=str(paypal["id"]),
        destination=str(assigned["destination"]),
    )


async def ensure_paypal_pool_payment(account_id: int, snapshot: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    """Assign/configure PayPal once; never override an existing destination."""
    current = snapshot or await database.get_latest_earnapp_snapshot(account_id)
    payment: Any = current.get("payment") if isinstance(current, Mapping) else None
    if not isinstance(payment, Mapping):
        try:
            payment = json.loads(str((current or {}).get("payment_json") or "{}"))
        except (TypeError, ValueError):
            payment = {}
    if isinstance(payment, Mapping) and payment.get("configured"):
        return dict(payment)
    try:
        return await configure_payment_from_paypal_pool(account_id, snapshot=current)
    except ValueError:
        return None
    except Exception as exc:  # noqa: BLE001 - payout setup must not hide a healthy collection
        logger.warning("EarnApp %s PayPal auto-configuration deferred: %s", account_id, type(exc).__name__)
        return None


async def disable_payment(account_id: int) -> dict[str, Any]:
    async with earnapp_canary.account_api_lock(account_id):
        collector = await _payment_collector(account_id)
        return await collector.disable_payment()


async def collect_active_accounts(*, concurrency: int = 4) -> dict[str, Any]:
    """Collect every operable account without allowing one failure to stop peers."""
    rows = [
        row
        for row in await database.list_earnapp_accounts()
        if str(row.get("state") or "").strip().upper() in _COLLECTABLE_STATES
    ]
    semaphore = asyncio.Semaphore(max(1, min(int(concurrency), 16)))

    async def collect(row: dict[str, Any]) -> dict[str, Any]:
        account_id = int(row.get("id") or 0)
        try:
            async with semaphore:
                result = await collect_account(account_id)
                if result.get("status") == "ok":
                    await ensure_paypal_pool_payment(account_id, result)
        except Exception as exc:  # noqa: BLE001 - scheduled peers must continue
            logger.warning("EarnApp account %s collection failed: %s", account_id, type(exc).__name__)
            return {"account_id": account_id, "status": "error", "error_kind": "internal"}
        status = "ok" if result.get("status") == "ok" else "error"
        item = {"account_id": account_id, "status": status}
        if status == "error":
            item["error_kind"] = str(result.get("error_kind") or "unknown")
        return item

    accounts = list(await asyncio.gather(*(collect(row) for row in rows)))
    succeeded = sum(item["status"] == "ok" for item in accounts)
    return {
        "attempted": len(accounts),
        "succeeded": succeeded,
        "failed": len(accounts) - succeeded,
        "accounts": accounts,
    }


async def account_route_status(account_id: int) -> dict[str, Any]:
    """Return a secret-free view of the exact collector route for one account."""
    healthy_nodes = await database.get_earnapp_account_node_routes(account_id, healthy_only=True)
    if healthy_nodes:
        route, status, source = healthy_nodes[0], "healthy", "node"
    else:
        all_nodes = await database.get_earnapp_account_node_routes(account_id, healthy_only=False)
        if all_nodes:
            route, status, source = all_nodes[0], "unhealthy", "node"
        else:
            route = await database.get_earnapp_account_control_route(account_id, healthy_only=True)
            if route:
                status, source = "healthy", "account_control"
            else:
                route = await database.get_earnapp_account_control_route(account_id)
                if not route:
                    return {
                        "status": "unavailable",
                        "source": "none",
                        "proxy_id": None,
                        "egress_ip": "",
                        "country_code": "",
                        "checked_at": None,
                    }
                status, source = "unhealthy", "account_control"
    return {
        "status": status,
        "source": source,
        "proxy_id": int(route.get("proxy_id") or 0) or None,
        "egress_ip": str(route.get("exit_ip") or ""),
        "country_code": str(route.get("country_code") or "").strip().upper(),
        "checked_at": route.get("last_checked_at"),
    }
