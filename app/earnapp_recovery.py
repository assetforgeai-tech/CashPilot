"""EarnApp logical-node recovery and split-brain protection."""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

from app import database, earnapp_accounts

STALE_WORKER_SECONDS = 15 * 60
RECOVERY_HOLD_SECONDS = 60 * 60
REPLACEMENT_TICKET_SECONDS = 15 * 60


class RecoveryClaimDenied(RuntimeError):
    """Raised when a node claim fails its worker, ticket, or generation guard."""


def _ticket_hash(token: str) -> str:
    return hashlib.sha256(str(token or "").encode()).hexdigest()


async def provision_node(
    logical_node_id: str,
    worker_id: int,
    *,
    device_id: str,
    proxy_country_code: str = "",
) -> dict[str, Any]:
    """Create the account binding and acquire an eligible residential route."""
    node_id = str(logical_node_id or "").strip()
    await earnapp_accounts.assign_account(node_id)
    current = await database.get_earnapp_logical_node(node_id)
    if not current:
        raise RecoveryClaimDenied("EarnApp logical node could not be created")
    if current.get("current_proxy_id"):
        if int(current.get("assigned_worker_id") or 0) != int(worker_id):
            raise RecoveryClaimDenied("EarnApp logical node is assigned to another worker")
        return _public_node(current)

    country_code = str(proxy_country_code or "").strip().upper()
    control = await database.get_earnapp_account_control_route(int(current["account_id"]), healthy_only=True)
    if control and country_code and str(control.get("country_code") or "").strip().upper() != country_code:
        await database.release_earnapp_account_control_route(
            int(current["account_id"]),
            expected_proxy_id=int(control["proxy_id"]),
            reason=f"EARNAPP_NODE_REQUIRES_{country_code}",
        )
        control = None
    transferred = await database.transfer_earnapp_control_route_to_node(
        int(current["account_id"]), node_id, worker_id=int(worker_id), country_code=country_code
    )
    if transferred:
        proxy = {"proxy_id": int(transferred["proxy_id"])}
    else:
        proxy = await database.lease_proxy_for_provider_instance(
            "earnapp", int(worker_id), node_id, country_code=country_code
        )
        if not proxy:
            raise RecoveryClaimDenied("no eligible residential EarnApp proxy available")
    try:
        node = await database.bind_earnapp_node_runtime(
            node_id,
            int(worker_id),
            device_id=str(device_id or ""),
            proxy_id=int(proxy["proxy_id"]),
        )
    except Exception:
        await database.release_proxy_for_provider_instance(
            "earnapp", int(worker_id), node_id, reason="EARNAPP_NODE_BIND_FAILED"
        )
        raise
    return _public_node(node)


async def sweep_stale_nodes(*, stale_after_seconds: int = STALE_WORKER_SECONDS) -> dict[str, list[dict[str, Any]]]:
    return await database.sweep_stale_earnapp_nodes(
        stale_after_seconds=stale_after_seconds,
        hold_seconds=RECOVERY_HOLD_SECONDS,
    )


async def issue_replacement_ticket(logical_node_id: str, target_worker_id: int) -> str:
    node = await database.get_earnapp_logical_node(logical_node_id)
    if not node or str(node.get("state") or "") not in {"RECOVERY_HOLD", "RECOVERABLE"}:
        raise RecoveryClaimDenied("EarnApp node is not recoverable")
    token = secrets.token_urlsafe(32)
    result = await database.create_earnapp_replacement_ticket(
        logical_node_id,
        int(target_worker_id),
        generation=int(node["generation"]),
        token_hash=_ticket_hash(token),
        expires_seconds=REPLACEMENT_TICKET_SECONDS,
    )
    if result != "created":
        messages = {
            "target_worker_not_found": "EarnApp replacement target worker does not exist",
            "node_not_found": "EarnApp logical node not found",
            "generation_mismatch": "EarnApp recovery generation changed before ticket creation",
            "node_not_recoverable": "EarnApp node is no longer recoverable",
        }
        raise RecoveryClaimDenied(messages.get(result, "EarnApp replacement ticket could not be created"))
    return token


async def claim_node(
    logical_node_id: str,
    worker_id: int,
    *,
    expected_generation: int,
    replacement_ticket: str = "",
) -> dict[str, Any]:
    node = await database.get_earnapp_logical_node(logical_node_id)
    if not node:
        raise RecoveryClaimDenied("EarnApp logical node not found")
    assigned_worker_id = int(node.get("assigned_worker_id") or 0)
    last_worker_id = int(node.get("last_worker_id") or assigned_worker_id or 0)
    replacing = bool(
        (assigned_worker_id and assigned_worker_id != int(worker_id))
        or (not assigned_worker_id and last_worker_id and last_worker_id != int(worker_id))
    )
    if replacing and not replacement_ticket:
        raise RecoveryClaimDenied("a one-time replacement ticket is required")
    claimed = await database.claim_earnapp_node(
        logical_node_id,
        int(worker_id),
        expected_generation=int(expected_generation),
        ticket_hash=_ticket_hash(replacement_ticket) if replacing else "",
    )
    if not claimed:
        reason = (
            "replacement ticket or generation is invalid"
            if replacing
            else "generation is stale or no proxy is available"
        )
        raise RecoveryClaimDenied(reason)
    return _public_node(claimed)


async def heartbeat_node(logical_node_id: str, worker_id: int, *, generation: int) -> bool:
    return await database.heartbeat_earnapp_node(
        logical_node_id,
        int(worker_id),
        generation=int(generation),
    )


def _public_node(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "logical_node_id": str(node.get("logical_node_id") or ""),
        "account_id": int(node.get("account_id") or 0),
        "worker_id": int(node.get("assigned_worker_id") or 0),
        "device_id": str(node.get("device_id") or ""),
        "proxy_id": int(node.get("current_proxy_id") or 0),
        "preferred_proxy_id": int(node.get("preferred_proxy_id") or 0),
        "state": str(node.get("state") or ""),
        "generation": int(node.get("generation") or 0),
    }
