"""Secret-free account-pool summaries backed by provider-specific adapters."""

from __future__ import annotations

from typing import Any

from app import database, provider_runtime


async def list_provider_account_pools() -> list[dict[str, Any]]:
    accounts = await database.list_earnapp_accounts()
    proxy_capacity = {
        str(row.get("provider_slug") or row.get("provider_name") or "").strip().lower(): row
        for row in await database.get_provider_proxy_capacity()
    }
    earnapp = {
        "provider": "earnapp",
        "total": len(accounts),
        "active": sum(str(row.get("state") or "").upper() == "ACTIVE" for row in accounts),
        "attention": sum(str(row.get("state") or "").upper() != "ACTIVE" for row in accounts),
        "assigned_nodes": sum(int(row.get("assigned_nodes") or 0) for row in accounts),
        "adapter": "earnapp",
        "modeled": True,
    }
    earnapp.update(_capacity_fields(proxy_capacity.get("earnapp")))
    rows = [earnapp]
    for slug in sorted(provider_runtime.ACTIVE_SLUGS - {"earnapp"}):
        row = {
                "provider": slug,
                "total": None,
                "active": None,
                "attention": None,
                "assigned_nodes": None,
                "adapter": "none",
                "modeled": False,
            }
        row.update(_capacity_fields(proxy_capacity.get(slug)))
        rows.append(row)
    return rows


def _capacity_fields(row: dict[str, Any] | None) -> dict[str, int | None]:
    """Expose proxy capacity without turning unknown discovery into zero."""
    if not row:
        return {"proxy_total": None, "proxy_eligible": None, "proxy_available": None, "proxy_leased": None}
    return {
        "proxy_total": int(row.get("total") or 0),
        "proxy_eligible": int(row.get("eligible") or 0),
        "proxy_available": int(row.get("available") or 0),
        "proxy_leased": int(row.get("leased") or 0),
    }
