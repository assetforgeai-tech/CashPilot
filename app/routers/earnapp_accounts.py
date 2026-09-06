"""Owner-only EarnApp Account Pool and recovery control routes."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import database, deps, earnapp_accounts, earnapp_collection, earnapp_recovery

router = APIRouter()


class EarnAppAccountImportIn(BaseModel):
    profile_key: str = Field(min_length=1, max_length=200)
    account_name: str = Field(min_length=1, max_length=320)
    email: str = Field(default="", max_length=320)
    auth_method: str = Field(min_length=1, max_length=20)
    cookies: dict[str, Any] = Field(default_factory=dict)


class EarnAppDeleteIn(BaseModel):
    confirm_account_name: str = Field(default="")
    confirm_phrase: str = Field(default="")


class EarnAppPaymentIn(BaseModel):
    payment_method: str = Field(min_length=1, max_length=100)
    destination: str = Field(min_length=3, max_length=320)


class ReplacementTicketIn(BaseModel):
    target_worker_id: int = Field(gt=0)


_RUNTIME_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,120}$")


def _remote_worker_reports_not_found(exc: Exception) -> bool:
    """Distinguish a remote runtime 404 from a missing worker record."""
    return (
        int(getattr(exc, "status_code", 0) or 0) == 404
        and str(getattr(exc, "detail", "") or "") == "Worker request failed"
    )


async def _remove_local_runtime(binding: dict[str, Any]) -> bool:
    """Remove one tracked runtime and require a worker-side removal ACK.

    Account deletion never unlinks the remote EarnApp device.  It only asks the
    worker to remove the local Docker/LXD runtime identified by the durable
    binding, and treats every transport/CAS/worker error as a refusal to delete
    the account or release its proxy lease.
    """
    worker_id = int(binding.get("worker_id") or 0)
    logical_node_id = str(binding.get("logical_node_id") or "").strip()
    instance_id = str(binding.get("instance_id") or "").strip()
    if worker_id <= 0 or not _RUNTIME_ID_RE.fullmatch(logical_node_id) or not _RUNTIME_ID_RE.fullmatch(instance_id):
        return False

    # Import lazily: this router is included by app.main, while app.main also
    # imports the router during startup.
    from app.main import _proxy_to_worker

    backend = str(binding.get("runtime_backend") or "").strip().lower()

    async def _lxd_runtime_absent(generation: int, device_id: str) -> bool:
        try:
            response = await _proxy_to_worker(
                worker_id,
                "POST",
                f"/api/earnapp/nodes/{logical_node_id}/presence",
                json={"generation": generation, "device_id": device_id},
                timeout=30,
            )
        except Exception as exc:
            # Only the host helper's exact-name LXD lookup may prove absence.
            # Network/5xx/CAS errors remain unresolved and block deletion.
            return _remote_worker_reports_not_found(exc)
        return isinstance(response, dict) and response.get("present") is False

    try:
        if backend == "lxd":
            generation = int(binding.get("generation") or 0)
            device_id = str(binding.get("device_id") or "").strip()
            if generation <= 0 or not device_id:
                return False
            response = await _proxy_to_worker(
                worker_id,
                "DELETE",
                f"/api/earnapp/nodes/{logical_node_id}",
                json={"generation": generation, "device_id": device_id},
                timeout=180,
            )
        elif backend == "docker":
            generation = int(binding.get("generation") or 0)
            device_id = str(binding.get("device_id") or "").strip()
            if generation <= 0 or not device_id:
                return False
            response = await _proxy_to_worker(
                worker_id,
                "DELETE",
                f"/api/earnapp/docker-nodes/{instance_id}",
                json={"generation": generation, "device_id": device_id},
                timeout=180,
            )
        else:
            return False
    except Exception as exc:
        if int(getattr(exc, "status_code", 0) or 0) == 404 and backend == "lxd":
            generation = int(binding.get("generation") or 0)
            device_id = str(binding.get("device_id") or "").strip()
            if generation > 0 and device_id:
                return await _lxd_runtime_absent(generation, device_id)
        return False

    if not isinstance(response, dict) or str(response.get("status") or "").lower() != "removed":
        return False
    if backend == "docker":
        return response.get("main_present") is False and response.get("sidecar_present") is False
    return not ("running" in response and bool(response.get("running")))


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _token_warning(row: dict[str, Any]) -> str:
    expiry = _parse_timestamp(row.get("token_expires_at"))
    if expiry is None:
        return "expiry_unknown"
    remaining = (expiry - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        return "expired"
    if remaining <= 24 * 60 * 60:
        return "expires_within_24h"
    if remaining <= 7 * 24 * 60 * 60:
        return "expires_within_7d"
    return "healthy"


def _public_account(
    row: dict[str, Any], snapshot: dict[str, Any] | None, route: dict[str, Any] | None = None
) -> dict[str, Any]:
    try:
        credential_keys = __import__("json").loads(str(row.get("credential_keys_json") or "[]"))
    except (TypeError, ValueError, __import__("json").JSONDecodeError):
        credential_keys = []
    devices: list[dict[str, Any]] = []
    if snapshot:
        try:
            raw_devices = __import__("json").loads(str(snapshot.get("devices_json") or "[]"))
            devices = (
                [device for device in raw_devices if isinstance(device, dict)] if isinstance(raw_devices, list) else []
            )
        except (TypeError, ValueError, __import__("json").JSONDecodeError):
            devices = []
    usage_devices = [device for device in devices if device.get("usage_available")]
    try:
        payment = __import__("json").loads(str(snapshot.get("payment_json") or "{}")) if snapshot else {}
    except (TypeError, ValueError, __import__("json").JSONDecodeError):
        payment = {}
    return {
        "id": int(row["id"]),
        "profile_key": str(row.get("profile_key") or ""),
        "account_name": str(row.get("account_name") or ""),
        "email": str(row.get("email") or ""),
        "auth_method": str(row.get("auth_method") or ""),
        "state": str(row.get("state") or ""),
        "token_expires_at": row.get("token_expires_at"),
        "cookie_expires_at": row.get("cookie_expires_at"),
        "token_warning": _token_warning(row),
        "assigned_nodes": int(row.get("assigned_nodes") or 0),
        "active_nodes": int(row.get("active_nodes") or 0),
        "recovery_nodes": int(row.get("recovery_nodes") or 0),
        "planned_nodes": int(row.get("planned_nodes") or 0),
        "credentials_present": {str(key): True for key in credential_keys},
        "collector": {
            "money_balance": float(snapshot["money_balance"]) if snapshot else None,
            "money_total": float(snapshot["money_total"]) if snapshot else None,
            "online_nodes": int(snapshot["online_nodes"]) if snapshot else None,
            "offline_nodes": int(snapshot["offline_nodes"]) if snapshot else None,
            "usage_current": sum(float(device.get("usage_current") or 0) for device in usage_devices)
            if snapshot
            else None,
            "usage_total": sum(float(device.get("usage_total") or 0) for device in usage_devices) if snapshot else None,
            "usage_available_nodes": len(usage_devices) if snapshot else None,
            "usage_missing_nodes": len(devices) - len(usage_devices) if snapshot else None,
            "earnings_update_in_ms": int(snapshot["earnings_update_in_ms"])
            if snapshot and snapshot.get("earnings_update_in_ms") is not None
            else None,
            "payment": payment if isinstance(payment, dict) else {},
            "collected_at": snapshot.get("collected_at") if snapshot else None,
        },
        "route": route
        or {
            "status": "unavailable",
            "source": "none",
            "proxy_id": None,
            "egress_ip": "",
            "country_code": "",
            "checked_at": None,
        },
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


async def _account_payload() -> dict[str, Any]:
    rows = await database.list_earnapp_accounts()
    accounts: list[dict[str, Any]] = []
    for row in rows:
        snapshot = await database.get_latest_earnapp_snapshot(int(row["id"]))
        route = await earnapp_collection.account_route_status(int(row["id"]))
        accounts.append(_public_account(row, snapshot, route))
    nodes = []
    now = datetime.now(UTC)
    for row in await database.list_earnapp_logical_nodes():
        hold_until = _parse_timestamp(row.get("recovery_hold_until"))
        remaining = max(0, int((hold_until - now).total_seconds())) if hold_until else 0
        nodes.append(
            {
                "logical_node_id": str(row.get("logical_node_id") or ""),
                "account_id": int(row.get("account_id") or 0),
                "state": str(row.get("state") or ""),
                "generation": int(row.get("generation") or 0),
                "assigned_worker_id": row.get("assigned_worker_id"),
                "device_id": str(row.get("device_id") or ""),
                "platform": str(row.get("platform") or "unknown").strip().lower(),
                "current_proxy_id": row.get("current_proxy_id"),
                "preferred_proxy_id": row.get("preferred_proxy_id"),
                "recovery_hold_remaining_seconds": remaining,
                "recovery_hold_seconds": 3600,
                "updated_at": row.get("updated_at"),
            }
        )
    counts = {
        "accounts": len(accounts),
        "active": sum(row["state"] == "ACTIVE" for row in accounts),
        "locked": sum(row["state"] == "ACCOUNT_LOCKED" for row in accounts),
        "nodes": len([row for row in nodes if row["state"] != "RETIRED"]),
        "active_nodes": sum(row["state"] == "ACTIVE" for row in nodes),
        "recovery_nodes": sum(row["state"] in {"RECOVERY_HOLD", "RECOVERABLE"} for row in nodes),
        "planned_nodes": sum(row["state"] == "PLANNED" for row in nodes),
    }
    return {
        "accounts": accounts,
        "nodes": nodes,
        "counts": counts,
        "proxy_capacity": await database.get_earnapp_proxy_capacity(),
    }


@router.get("/api/admin/earnapp/accounts")
async def api_earnapp_accounts(request: Request) -> dict[str, Any]:
    deps._require_owner(request)
    return await _account_payload()


@router.post("/api/admin/earnapp/accounts/import")
async def api_earnapp_accounts_import(request: Request, body: EarnAppAccountImportIn) -> dict[str, Any]:
    deps._require_owner(request)
    try:
        account_id = await earnapp_accounts.import_account(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "account_id": account_id}


@router.post("/api/admin/earnapp/accounts/{account_id}/collect")
async def api_earnapp_account_collect(request: Request, account_id: int) -> dict[str, Any]:
    deps._require_owner(request)
    result = await earnapp_collection.collect_account(account_id)
    if result.get("status") != "ok":
        raise HTTPException(status_code=502, detail=str(result.get("error") or "EarnApp collection failed"))
    return {key: result.get(key) for key in ("status", "money_balance", "money_total", "online_nodes", "offline_nodes")}


@router.post("/api/admin/earnapp/accounts/{account_id}/payment")
async def api_earnapp_account_payment(request: Request, account_id: int, body: EarnAppPaymentIn) -> dict[str, Any]:
    deps._require_owner(request)
    try:
        return await earnapp_collection.configure_payment(
            account_id,
            payment_method=body.payment_method.strip(),
            destination=body.destination.strip(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/api/admin/earnapp/accounts/{account_id}/payment")
async def api_earnapp_account_payment_disable(request: Request, account_id: int) -> dict[str, Any]:
    deps._require_owner(request)
    try:
        return await earnapp_collection.disable_payment(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/api/admin/earnapp/accounts/{account_id}")
async def api_earnapp_account_delete(request: Request, account_id: int, body: EarnAppDeleteIn) -> dict[str, str]:
    deps._require_owner(request)
    account = await database.get_earnapp_account_credentials(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="EarnApp account not found")
    if str(body.confirm_account_name).strip() != str(account.get("account_name") or ""):
        raise HTTPException(status_code=400, detail="Account-name confirmation does not match")
    if str(body.confirm_phrase).strip() != "DELETE ACCOUNT":
        raise HTTPException(status_code=400, detail="Type DELETE ACCOUNT to confirm")
    try:
        deleted = await earnapp_accounts.delete_account(account_id, runtime_cleanup=_remove_local_runtime)
    except earnapp_accounts.AccountDeletionDenied as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="EarnApp account not found")
    return {"status": "deleted"}


@router.post("/api/admin/earnapp/nodes/{logical_node_id}/replacement-ticket")
async def api_earnapp_replacement_ticket(
    request: Request, logical_node_id: str, body: ReplacementTicketIn
) -> dict[str, Any]:
    deps._require_owner(request)
    try:
        token = await earnapp_recovery.issue_replacement_ticket(logical_node_id, body.target_worker_id)
    except earnapp_recovery.RecoveryClaimDenied as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "logical_node_id": logical_node_id,
        "target_worker_id": body.target_worker_id,
        "replacement_ticket": token,
        "expires_in_seconds": earnapp_recovery.REPLACEMENT_TICKET_SECONDS,
    }
