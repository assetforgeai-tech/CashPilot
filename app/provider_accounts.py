"""Secret-free account-pool summaries backed by provider-specific adapters."""

from __future__ import annotations

from typing import Any

from app import database, provider_runtime


async def list_provider_account_pools() -> list[dict[str, Any]]:
    accounts = await database.list_earnapp_accounts()
    earnapp = {
        "provider": "earnapp",
        "total": len(accounts),
        "active": sum(str(row.get("state") or "").upper() == "ACTIVE" for row in accounts),
        "attention": sum(str(row.get("state") or "").upper() != "ACTIVE" for row in accounts),
        "assigned_nodes": sum(int(row.get("assigned_nodes") or 0) for row in accounts),
        "adapter": "earnapp",
        "modeled": True,
    }
    rows = [earnapp]
    for slug in sorted(provider_runtime.ACTIVE_SLUGS - {"earnapp"}):
        rows.append(
            {
                "provider": slug,
                "total": None,
                "active": None,
                "attention": None,
                "assigned_nodes": None,
                "adapter": "none",
                "modeled": False,
            }
        )
    return rows
