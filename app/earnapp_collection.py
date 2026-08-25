"""Account-scoped EarnApp collector orchestration."""

from __future__ import annotations

from typing import Any

from app import database
from app.collectors.earnapp import EarnAppAccountCollector


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


async def collect_account(account_id: int) -> dict[str, Any]:
    account = await database.get_earnapp_account_credentials(account_id)
    if not account:
        return {"status": "error", "error_kind": "auth", "error": "EarnApp account unavailable"}
    route = await ensure_collection_route(account_id)
    if not route:
        return {"status": "error", "error_kind": "route", "error": "EarnApp account proxy unavailable"}

    collector = EarnAppAccountCollector(account.get("credentials") or {}, route)
    snapshot = await collector.collect_snapshot()
    if snapshot.get("status") == "ok":
        await database.save_earnapp_snapshot(account_id, snapshot)
    elif snapshot.get("error_kind") == "auth":
        await database.set_earnapp_account_state(account_id, "AUTH_FAILED")
    return snapshot
