"""Owner-only MYST wallet inventory routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app import database, deps

router = APIRouter()


class MystWalletImportIn(BaseModel):
    raw: str = Field(default="")

class MystWalletUpdateIn(BaseModel):
    state: str | None = None
    funding: str | None = None
    quarantined_reason: str | None = None


@router.get("/api/admin/myst-wallets")
async def api_myst_wallets(request: Request) -> list[dict[str, Any]]:
    deps._require_owner(request)
    return await database.list_myst_wallets()


@router.post("/api/admin/myst-wallets/import")
async def api_myst_wallets_import(request: Request, body: MystWalletImportIn) -> dict[str, Any]:
    deps._require_owner(request)
    if not body.raw.strip():
        raise HTTPException(status_code=400, detail="Wallet data is required")
    count = await database.import_myst_wallets(body.raw)
    return {"status": "ok", "imported": count}

@router.get("/api/admin/myst-wallets/export")
async def api_myst_wallets_export(request: Request, funding: str | None = None) -> PlainTextResponse:
    deps._require_owner(request)
    rows = await database.export_myst_wallets(funding=funding)
    return PlainTextResponse("\n".join(rows), media_type="text/plain")

@router.patch("/api/admin/myst-wallets/{wallet_id}")
async def api_myst_wallets_update(request: Request, wallet_id: int, body: MystWalletUpdateIn) -> dict[str, str]:
    deps._require_owner(request)
    ok = await database.update_myst_wallet(
        wallet_id,
        state=body.state,
        funding=body.funding,
        quarantined_reason=body.quarantined_reason,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="MYST wallet not found")
    return {"status": "ok"}
