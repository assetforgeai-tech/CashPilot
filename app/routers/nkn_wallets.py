"""Owner-only NKN wallet inventory routes."""

from __future__ import annotations

import base64
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import database, deps

router = APIRouter()


class NknWalletImportIn(BaseModel):
    archive_b64: str = Field(default="")
    records: list[dict[str, str]] = Field(default_factory=list)


@router.get("/api/admin/nkn-wallets")
async def api_nkn_wallets(request: Request) -> list[dict[str, Any]]:
    deps._require_owner(request)
    return await database.list_nkn_wallets()


@router.post("/api/admin/nkn-wallets/import")
async def api_nkn_wallets_import(request: Request, body: NknWalletImportIn) -> dict[str, Any]:
    deps._require_owner(request)
    if body.records:
        received = len(body.records)
        count = await database.import_nkn_wallet_records(body.records)
        return {"status": "ok", "imported": count, "received": received}
    if not body.archive_b64.strip():
        raise HTTPException(status_code=400, detail="Wallet folder is required")
    try:
        archive = base64.b64decode(body.archive_b64)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid wallet archive") from exc
    count = await database.import_nkn_wallets_from_zip(archive)
    return {"status": "ok", "imported": count}
