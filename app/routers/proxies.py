"""Owner-only proxy provider and proxy pool routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import database, deps, proxy_egress
from app.proxy_providers.vtproxy import sync_vtproxy_provider

router = APIRouter()


class ProxyProviderIn(BaseModel):
    name: str
    type: str
    base_url: str = ""
    api_key: str | None = None
    enabled: bool = True


class ProxyAssignmentIn(BaseModel):
    proxy_id: int | None = None
    mode: str = "proxy"
    fallback: str = "hold"


@router.get("/api/proxy-providers")
async def api_proxy_providers(request: Request) -> list[dict[str, Any]]:
    deps._require_owner(request)
    return await database.list_proxy_providers()


@router.post("/api/proxy-providers")
async def api_proxy_provider_create(request: Request, body: ProxyProviderIn) -> dict[str, Any]:
    deps._require_owner(request)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Provider name is required")
    if body.type.strip().lower() != "vtproxy":
        raise HTTPException(status_code=400, detail="Unsupported proxy provider type")
    provider_id = await database.upsert_proxy_provider(
        body.name,
        body.type,
        base_url=body.base_url,
        api_key=body.api_key,
        enabled=body.enabled,
    )
    return {"status": "ok", "provider_id": provider_id}


@router.post("/api/proxy-providers/{provider_id}/sync")
async def api_proxy_provider_sync(request: Request, provider_id: int) -> dict[str, Any]:
    deps._require_owner(request)
    provider = await database.get_proxy_provider(provider_id, include_secret=True)
    if not provider:
        raise HTTPException(status_code=404, detail="Proxy provider not found")
    if provider["type"] != "vtproxy":
        raise HTTPException(status_code=400, detail="This provider type does not support sync")
    try:
        result = await sync_vtproxy_provider(provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", **result}


@router.get("/api/proxy-pool")
async def api_proxy_pool(request: Request) -> list[dict[str, Any]]:
    deps._require_owner(request)
    return await database.list_proxy_pool()


@router.post("/api/workers/{worker_id}/proxy-assignment")
async def api_worker_proxy_assignment(request: Request, worker_id: int, body: ProxyAssignmentIn) -> dict[str, Any]:
    deps._require_owner(request)
    if body.mode not in proxy_egress.MODES:
        raise HTTPException(status_code=400, detail="Invalid proxy mode")
    if body.fallback not in {"hold", "rotate"}:
        raise HTTPException(status_code=400, detail="Invalid proxy fallback")
    ok = await database.set_worker_proxy_assignment(worker_id, body.proxy_id, body.mode, body.fallback)
    if not ok:
        raise HTTPException(status_code=404, detail="Worker or proxy not found")
    worker = await database.get_worker(worker_id)
    proxy = await database.get_proxy_endpoint(body.proxy_id) if body.proxy_id and body.mode != proxy_egress.DIRECT else None
    payload = {
        "mode": body.mode,
        "worker_name": (worker or {}).get("name") or str(worker_id),
        "proxy": proxy,
    }
    from app.main import _proxy_to_worker  # local import avoids main -> router cycle at startup

    applied = await _proxy_to_worker(worker_id, "POST", "/api/egress/apply", json=payload, timeout=30)
    return {"status": "ok", "applied": applied}

@router.post("/api/workers/{worker_id}/proxy-lease")
async def api_worker_proxy_lease(request: Request, worker_id: int) -> dict[str, Any]:
    deps._require_owner(request)
    lease = await database.lease_proxy_for_worker(worker_id)
    if not lease:
        raise HTTPException(status_code=404, detail="No available proxy")
    worker = await database.get_worker(worker_id)
    payload = {
        "mode": lease.get("mode") or proxy_egress.PROXY,
        "worker_name": (worker or {}).get("name") or str(worker_id),
        "proxy": lease if (lease.get("proxy_id") and lease.get("mode") != proxy_egress.DIRECT) else None,
    }
    from app.main import _proxy_to_worker

    applied = await _proxy_to_worker(worker_id, "POST", "/api/egress/apply", json=payload, timeout=30)
    return {"status": "ok", "lease": lease, "applied": applied}
