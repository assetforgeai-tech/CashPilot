"""Owner-only EarnApp account pool routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import database, deps

router = APIRouter()


class EarnAppAccountImportIn(BaseModel):
    file_name: str = Field(default="")
    raw: str = Field(default="")


class EarnAppAccountStateIn(BaseModel):
    state: str


@router.get("/api/admin/earnapp-accounts")
async def api_earnapp_accounts(request: Request) -> dict[str, Any]:
    deps._require_owner(request)
    rows = await database.list_earnapp_accounts()
    counts = {"total": len(rows), "valid": 0, "disabled": 0, "expired": 0, "auth_failed": 0, "active_leases": 0}
    for row in rows:
        key = str(row.get("state") or "").lower()
        if key in counts:
            counts[key] += 1
        counts["active_leases"] += int(row.get("assigned_nodes") or 0)
    return {"accounts": rows, "counts": counts}


@router.post("/api/admin/earnapp-accounts/import")
async def api_earnapp_accounts_import(request: Request, body: EarnAppAccountImportIn) -> dict[str, Any]:
    deps._require_owner(request)
    try:
        account_id = await database.upsert_earnapp_account(body.file_name, body.raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "account_id": account_id}


@router.patch("/api/admin/earnapp-accounts/{account_id}")
async def api_earnapp_accounts_update(request: Request, account_id: int, body: EarnAppAccountStateIn) -> dict[str, str]:
    deps._require_owner(request)
    try:
        ok = await database.update_earnapp_account_state(account_id, body.state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="EarnApp account not found")
    return {"status": "ok"}


@router.delete("/api/admin/earnapp-accounts/{account_id}")
async def api_earnapp_accounts_delete(request: Request, account_id: int) -> dict[str, str]:
    deps._require_owner(request)
    if not await database.update_earnapp_account_state(account_id, "DELETED"):
        raise HTTPException(status_code=404, detail="EarnApp account not found")
    return {"status": "deleted"}
