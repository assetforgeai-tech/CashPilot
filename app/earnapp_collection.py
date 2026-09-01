"""Account-scoped EarnApp collector orchestration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

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


async def collect_account(account_id: int) -> dict[str, Any]:
    async with earnapp_canary.account_api_lock(account_id):
        account = await database.get_earnapp_account_credentials(account_id)
        if not account:
            return {"status": "error", "error_kind": "auth", "error": "EarnApp account unavailable"}
        routes = await _collection_routes(account_id)
        if not routes:
            return {"status": "error", "error_kind": "route", "error": "EarnApp account proxy unavailable"}
        last_snapshot: dict[str, Any] = {"status": "error", "error_kind": "route", "error": "EarnApp route unavailable"}
        for route in routes:
            snapshot = await EarnAppAccountCollector(account.get("credentials") or {}, route).collect_snapshot()
            if snapshot.get("status") == "ok":
                await database.save_earnapp_snapshot(account_id, snapshot)
                return snapshot
            last_snapshot = snapshot
            if snapshot.get("error_kind") == "auth":
                await database.set_earnapp_account_state(account_id, "AUTH_FAILED")
                return snapshot
        return last_snapshot


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
