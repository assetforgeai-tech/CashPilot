"""Owner-only MYST wallet inventory routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import database, deps

router = APIRouter()


class MystWalletImportIn(BaseModel):
    raw: str = Field(default="")


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
