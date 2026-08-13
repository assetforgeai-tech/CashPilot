"""Owner-only proxy provider and proxy pool routes."""

from __future__ import annotations

from typing import Any

import asyncio
import csv
import io
import json
import re
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
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

class ProxyRecheckIn(BaseModel):
    proxy_ids: list[int] | None = None
    concurrency: int | None = None

class ProxySchedulerIn(BaseModel):
    enabled: bool = False
    interval_minutes: int = 15
    concurrency: int = 8

class ProxyImportIn(BaseModel):
    text: str
    provider_name: str = "manual"
    recheck: bool = True
    concurrency: int | None = None

def _normalize_proxy_record(parts: list[str], *, location: str = "", protocol: str = "") -> dict[str, Any] | None:
    if len(parts) == 1 and not protocol:
        value = parts[0].strip()
        if not value:
            return None
        if value.startswith("{") and value.endswith("}"):
            try:
                obj = json.loads(value)
            except Exception:
                obj = {}
            if isinstance(obj, dict):
                host = str(obj.get("host") or obj.get("ip") or "").strip()
                port = int(obj.get("port") or 0)
                if host and port > 0:
                    return {
                        "host": host,
                        "port": port,
                        "username": str(obj.get("username") or obj.get("user") or "").strip(),
                        "password": str(obj.get("password") or obj.get("pass") or "").strip(),
                        "protocol": str(obj.get("protocol") or "socks5").strip().lower(),
                        "location": str(obj.get("location") or location or "").strip(),
                    }
            return None
        parsed = urlparse(value if "://" in value else f"//{value}", scheme="socks5")
        host = parsed.hostname or ""
        port = int(parsed.port or 0)
        if not host or port <= 0:
            return None
        return {
            "host": host,
            "port": port,
            "username": parsed.username or "",
            "password": parsed.password or "",
            "protocol": (parsed.scheme or protocol or "socks5").lower(),
            "location": location,
        }
    if len(parts) >= 4 and re.match(r"^\d+\.\d+\.\d+\.\d+$", parts[0].strip()) and parts[1].strip().isdigit():
        host, port = parts[0].strip(), int(parts[1].strip())
        username = parts[2].strip()
        password = parts[3].strip()
        proto = protocol or (parts[4].strip().lower() if len(parts) > 4 and parts[4].strip().lower() in {"http", "socks5"} else "socks5")
        if len(parts) > 5 and parts[5].strip():
            location = parts[5].strip()
        return {"host": host, "port": port, "username": username, "password": password, "protocol": proto, "location": location}
    if len(parts) >= 2 and parts[0].strip() and parts[1].strip().isdigit():
        host, port = parts[0].strip(), int(parts[1].strip())
        username = parts[2].strip() if len(parts) > 2 else ""
        password = parts[3].strip() if len(parts) > 3 else ""
        proto = protocol or (parts[4].strip().lower() if len(parts) > 4 and parts[4].strip().lower() in {"http", "socks5"} else "socks5")
        if len(parts) > 5 and parts[5].strip():
            location = parts[5].strip()
        return {"host": host, "port": port, "username": username, "password": password, "protocol": proto, "location": location}
    return None

def _parse_proxy_import(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if line.startswith("{") and line.endswith("}"):
            parsed = _normalize_proxy_record([line])
            if parsed:
                rows.append(parsed)
            continue
        if "\t" in line or "," in line:
            delimiter = "\t" if "\t" in line else ","
            parts = [part.strip() for part in line.split(delimiter)]
            parsed = _normalize_proxy_record(parts)
            if parsed:
                rows.append(parsed)
            continue
        if "@" in line or "://" in line:
            parsed = _normalize_proxy_record([line])
            if parsed:
                rows.append(parsed)
            continue
        if ":" in line:
            parts = [part.strip() for part in line.split(":")]
            parsed = _normalize_proxy_record(parts)
            if parsed:
                rows.append(parsed)
    return rows

async def _probe_proxy(host: str, port: int, timeout: float = 5.0) -> dict[str, str]:
    host = host.strip()
    if not host or port <= 0:
        return {"status": "dead", "protocol": ""}
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.write(b"\x05\x01\x00")
        await writer.drain()
        data = await asyncio.wait_for(reader.readexactly(2), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        if data[0] == 5:
            return {"status": "alive", "protocol": "socks5"}
    except Exception:
        pass
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.write(b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(64), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        if data.startswith(b"HTTP/"):
            return {"status": "alive", "protocol": "http"}
    except Exception:
        pass
    return {"status": "dead", "protocol": ""}

async def _probe_proxy_confirmed(
    host: str,
    port: int,
    *,
    retries: int = 3,
    retry_delay: float = 5.0,
) -> dict[str, str]:
    for attempt in range(max(1, retries)):
        result = await _probe_proxy(host, port)
        if result.get("status") == "alive":
            return result
        if attempt < retries - 1:
            await asyncio.sleep(retry_delay)
    return {"status": "dead", "protocol": ""}

def _proxy_scheduler_settings(config: dict[str, Any]) -> dict[str, Any]:
    enabled = str(config.get("proxy_pool_recheck_enabled", "")).strip().lower() in {"1", "true", "yes", "on"}
    interval = int(str(config.get("proxy_pool_recheck_interval_minutes", "15") or "15").strip() or 15)
    concurrency = int(str(config.get("proxy_pool_recheck_concurrency", "8") or "8").strip() or 8)
    return {
        "enabled": enabled,
        "interval_minutes": min(1440, max(1, interval)),
        "concurrency": min(64, max(1, concurrency)),
    }

async def _apply_proxy_to_worker(worker_id: int, proxy: dict[str, Any]) -> dict[str, Any]:
    worker = await database.get_worker(worker_id)
    payload = {
        "mode": proxy_egress.PROXY,
        "worker_name": (worker or {}).get("name") or str(worker_id),
        "proxy": proxy,
    }
    from app.main import _proxy_to_worker  # local import avoids main -> router cycle at startup

    return await _proxy_to_worker(worker_id, "POST", "/api/egress/apply", json=payload, timeout=30)

async def run_proxy_pool_recheck(*, proxy_ids: list[int] | None = None, concurrency: int = 8) -> dict[str, Any]:
    wanted = {int(x) for x in (proxy_ids or []) if int(x) > 0}
    rows = await database.list_proxy_pool()
    targets = [row for row in rows if not wanted or int(row["id"]) in wanted]
    semaphore = asyncio.Semaphore(min(64, max(1, int(concurrency or 8))))

    async def check(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        async with semaphore:
            result = await _probe_proxy_confirmed(str(row.get("host") or "").strip(), int(row.get("port") or 0))
            return row, result

    checks = await asyncio.gather(*(check(row) for row in targets))
    results = {int(row["id"]): str(result.get("status") or "dead") for row, result in checks}
    protocols = {int(row["id"]): str(result.get("protocol") or "") for row, result in checks}
    checked = await database.update_proxy_pool_check_results(results, protocols=protocols)

    alive_rows = [row for row, result in checks if result.get("status") == "alive"]
    rotated = 0
    rotate_errors = 0
    for row, result in checks:
        if result.get("status") != "dead" or not row.get("assigned_worker_id"):
            continue
        replacement = next((candidate for candidate in alive_rows if not candidate.get("assigned_worker_id") and int(candidate["id"]) != int(row["id"])), None)
        if not replacement:
            continue
        proxy = await database.get_proxy_endpoint(int(replacement["id"]))
        if not proxy:
            continue
        worker_id = int(row["assigned_worker_id"])
        try:
            ok = await database.set_worker_proxy_assignment(worker_id, int(replacement["id"]), proxy_egress.PROXY, "rotate")
            if not ok:
                rotate_errors += 1
                continue
            await _apply_proxy_to_worker(worker_id, proxy)
            replacement["assigned_worker_id"] = worker_id
            rotated += 1
        except Exception:
            rotate_errors += 1
    return {
        "status": "ok",
        "checked": checked,
        "alive": sum(1 for v in results.values() if v == "alive"),
        "dead": sum(1 for v in results.values() if v == "dead"),
        "rotated": rotated,
        "rotate_errors": rotate_errors,
    }


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

@router.get("/api/proxy-pool/scheduler")
async def api_proxy_pool_scheduler(request: Request) -> dict[str, Any]:
    deps._require_owner(request)
    config = await database.get_config() or {}
    return _proxy_scheduler_settings(config if isinstance(config, dict) else {})

@router.post("/api/proxy-pool/scheduler")
async def api_proxy_pool_scheduler_save(request: Request, body: ProxySchedulerIn) -> dict[str, Any]:
    deps._require_owner(request)
    settings = _proxy_scheduler_settings(
        {
            "proxy_pool_recheck_enabled": body.enabled,
            "proxy_pool_recheck_interval_minutes": body.interval_minutes,
            "proxy_pool_recheck_concurrency": body.concurrency,
        }
    )
    await database.set_config_bulk(
        {
            "proxy_pool_recheck_enabled": "true" if settings["enabled"] else "false",
            "proxy_pool_recheck_interval_minutes": str(settings["interval_minutes"]),
            "proxy_pool_recheck_concurrency": str(settings["concurrency"]),
        }
    )
    return {"status": "ok", **settings}

@router.get("/api/proxy-pool/export")
async def api_proxy_pool_export(
    request: Request,
    status: str | None = None,
    provider: str | None = None,
    location: str | None = None,
    protocol: str | None = None,
) -> PlainTextResponse:
    deps._require_owner(request)
    rows = await database.export_proxy_pool(status=status, provider=provider, location=location, protocol=protocol)
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=[
            "id",
            "provider_name",
            "endpoint",
            "protocol",
            "location",
            "status",
            "expiry_date",
            "assigned_worker_id",
            "last_checked_at",
        ],
        extrasaction="ignore",
    )
    writer.writeheader()
    writer.writerows(rows)
    return PlainTextResponse(buf.getvalue(), media_type="text/csv")

@router.post("/api/proxy-pool/import")
async def api_proxy_pool_import(request: Request, body: ProxyImportIn) -> dict[str, Any]:
    deps._require_owner(request)
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Proxy input is required")
    provider_name = body.provider_name.strip() or "manual"
    provider_id = await database.upsert_proxy_provider(provider_name, "manual", enabled=True)
    proxies = _parse_proxy_import(body.text)
    if not proxies:
        raise HTTPException(status_code=400, detail="No valid proxies found")
    last_id = await database.upsert_proxy_endpoints(provider_id, proxies)
    result: dict[str, Any] = {"status": "ok", "imported": len(proxies), "provider_id": provider_id}
    if body.recheck:
        config = await database.get_config() or {}
        settings = _proxy_scheduler_settings(config if isinstance(config, dict) else {})
        recent_ids = list(range(max(1, int(last_id or 0) - len(proxies) + 1), int(last_id or 0) + 1)) if last_id else []
        result["recheck"] = await run_proxy_pool_recheck(proxy_ids=recent_ids or None, concurrency=body.concurrency or settings["concurrency"])
    return result

@router.post("/api/proxy-pool/recheck")
async def api_proxy_pool_recheck(request: Request, body: ProxyRecheckIn) -> dict[str, Any]:
    deps._require_owner(request)
    config = await database.get_config() or {}
    settings = _proxy_scheduler_settings(config if isinstance(config, dict) else {})
    return await run_proxy_pool_recheck(proxy_ids=body.proxy_ids, concurrency=body.concurrency or settings["concurrency"])


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
