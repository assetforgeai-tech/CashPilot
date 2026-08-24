"""Owner-only proxy provider and proxy pool routes."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import csv
import io
import json
import logging
import re
import secrets
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app import database, deps, egress, proxy_egress
from app.proxy_intelligence import lookup_ip_intelligence
from app.proxy_probe_profiles.earnapp import probe_earnapp_proxy
from app.proxy_providers.vtproxy import sync_vtproxy_provider

router = APIRouter()
logger = logging.getLogger(__name__)
_proxy_rotation_locks: dict[tuple[int, int], asyncio.Lock] = {}
_proxy_recheck_jobs: dict[str, dict[str, Any]] = {}
_proxy_recheck_tasks: set[asyncio.Task] = set()
_MAX_PROXY_RECHECK_JOBS = 100
_SYNC_EARNAPP_IMPORT_LIMIT = 20


def _is_active_proxy_instance(row: dict[str, Any]) -> bool:
    # Failed deploy rows have no sidecar to rotate; other persisted rows remain
    # fail-closed because stop/remove bookkeeping does not currently rewrite status.
    return bool(
        row.get("mode") == "proxy"
        and str(row.get("status") or "").strip().lower() != "failed"
        and str(row.get("instance_id") or "").strip()
    )


def _proxy_rotation_lock(worker_id: int) -> asyncio.Lock:
    key = (id(asyncio.get_running_loop()), worker_id)
    lock = _proxy_rotation_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _proxy_rotation_locks[key] = lock
    return lock


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
    profile: str = "generic"
    rotate_dead: bool = True


class ProxySchedulerIn(BaseModel):
    enabled: bool = False
    interval_minutes: int = 15
    concurrency: int = 8


class ProxyImportIn(BaseModel):
    text: str
    provider_name: str = "manual"
    recheck: bool = True
    concurrency: int | None = None


class ProxyDeleteIn(BaseModel):
    proxy_ids: list[int] | None = None
    status: str | None = None
    delete_all: bool = False
    confirmation: str = ""
    confirmation_again: str = ""


class ProviderProxyLeaseIn(BaseModel):
    provider_slug: str
    worker_id: int
    instance_id: str


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _prune_proxy_recheck_jobs() -> None:
    excess = len(_proxy_recheck_jobs) - _MAX_PROXY_RECHECK_JOBS
    if excess <= 0:
        return
    terminal = [
        job_id
        for job_id, job in _proxy_recheck_jobs.items()
        if str(job.get("status") or "").lower() in {"completed", "failed"}
    ]
    for job_id in terminal[:excess]:
        _proxy_recheck_jobs.pop(job_id, None)


def _schedule_proxy_import_recheck(proxy_ids: list[int], concurrency: int) -> dict[str, Any]:
    job_id = secrets.token_hex(12)
    job = {
        "job_id": job_id,
        "kind": "proxy_import_recheck",
        "status": "scheduled",
        "stage": "scheduled",
        "total": len(proxy_ids),
        "created_at": _utc_timestamp(),
        "updated_at": _utc_timestamp(),
    }
    _proxy_recheck_jobs[job_id] = job
    _prune_proxy_recheck_jobs()

    async def run() -> None:
        job.update(status="running", stage="generic_recheck", updated_at=_utc_timestamp())
        try:
            generic = await run_proxy_pool_recheck(
                proxy_ids=proxy_ids,
                concurrency=concurrency,
                rotate_dead=False,
                probe_retries=1,
            )
            job.update(stage="earnapp_recheck", updated_at=_utc_timestamp())
            earnapp = await run_earnapp_proxy_recheck(proxy_ids=proxy_ids, concurrency=concurrency)
            job.update(
                status="completed",
                stage="completed",
                result={"generic": generic, "earnapp": earnapp},
                updated_at=_utc_timestamp(),
            )
        except Exception as exc:
            logger.exception("Proxy import enrichment job %s failed", job_id)
            job.update(status="failed", error=type(exc).__name__, updated_at=_utc_timestamp())
        finally:
            _prune_proxy_recheck_jobs()

    task = asyncio.create_task(run())
    _proxy_recheck_tasks.add(task)
    task.add_done_callback(_proxy_recheck_tasks.discard)
    return dict(job)


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
        proto = protocol or (
            parts[4].strip().lower() if len(parts) > 4 and parts[4].strip().lower() in {"http", "socks5"} else "socks5"
        )
        if len(parts) > 5 and parts[5].strip():
            location = parts[5].strip()
        return {
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "protocol": proto,
            "location": location,
        }
    if len(parts) >= 2 and parts[0].strip() and parts[1].strip().isdigit():
        host, port = parts[0].strip(), int(parts[1].strip())
        username = parts[2].strip() if len(parts) > 2 else ""
        password = parts[3].strip() if len(parts) > 3 else ""
        proto = protocol or (
            parts[4].strip().lower() if len(parts) > 4 and parts[4].strip().lower() in {"http", "socks5"} else "socks5"
        )
        if len(parts) > 5 and parts[5].strip():
            location = parts[5].strip()
        return {
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "protocol": proto,
            "location": location,
        }
    return None


def _parse_proxy_import(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        parsed: dict[str, Any] | None = None
        if line.startswith("{") and line.endswith("}"):
            parsed = _normalize_proxy_record([line])
        elif "\t" in line or "," in line:
            delimiter = "\t" if "\t" in line else ","
            parts = [part.strip() for part in line.split(delimiter)]
            parsed = _normalize_proxy_record(parts)
        elif "@" in line or "://" in line:
            parsed = _normalize_proxy_record([line])
        elif ":" in line:
            parts = [part.strip() for part in line.split(":")]
            parsed = _normalize_proxy_record(parts)
        if parsed:
            parsed["_raw_line"] = line
            rows.append(parsed)
    return rows


_PROXY_PROBE_HOST = "example.com"
_PROXY_PROBE_PORT = 80
_PROXY_IP_TARGETS = ("api.ipify.org", "checkip.amazonaws.com", "icanhazip.com")


async def _read_exactly_or_none(reader: asyncio.StreamReader, n: int, timeout: float) -> bytes:
    try:
        return await asyncio.wait_for(reader.readexactly(n), timeout=timeout)
    except Exception:
        return b""


async def _read_some_or_none(reader: asyncio.StreamReader, n: int, timeout: float) -> bytes:
    try:
        return await asyncio.wait_for(reader.read(n), timeout=timeout)
    except Exception:
        return b""


def _is_http_success_response(data: bytes) -> bool:
    parts = data.split(maxsplit=2)
    if len(parts) < 2 or not parts[0].startswith(b"HTTP/"):
        return False
    status = parts[1]
    return len(status) == 3 and status.isdigit() and 200 <= int(status) < 300


async def _probe_socks5_proxy(
    host: str,
    port: int,
    *,
    username: str = "",
    password: str = "",
    timeout: float = 5.0,
) -> bool:
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
    try:
        methods = [b"\x00"]
        if username or password:
            methods.append(b"\x02")
        writer.write(b"\x05" + bytes([len(methods)]) + b"".join(methods))
        await writer.drain()
        method = await _read_exactly_or_none(reader, 2, timeout)
        if len(method) != 2 or method[0] != 5:
            return False
        if method[1] == 0x02:
            auth = username.encode("utf-8")
            secret = password.encode("utf-8")
            if len(auth) > 255 or len(secret) > 255:
                return False
            writer.write(b"\x01" + bytes([len(auth)]) + auth + bytes([len(secret)]) + secret)
            await writer.drain()
            auth_reply = await _read_exactly_or_none(reader, 2, timeout)
            if auth_reply != b"\x01\x00":
                return False
        elif method[1] != 0x00:
            return False

        target_host = _PROXY_PROBE_HOST.encode("ascii")
        if len(target_host) > 255:
            return False
        writer.write(
            b"\x05\x01\x00\x03" + bytes([len(target_host)]) + target_host + _PROXY_PROBE_PORT.to_bytes(2, "big")
        )
        await writer.drain()
        reply = await _read_exactly_or_none(reader, 4, timeout)
        if len(reply) != 4 or reply[0] != 5 or reply[1] != 0:
            return False
        atyp = reply[3]
        if atyp == 1:
            if len(await _read_exactly_or_none(reader, 6, timeout)) != 6:
                return False
        elif atyp == 3:
            host_len = await _read_exactly_or_none(reader, 1, timeout)
            if not host_len:
                return False
            if len(await _read_exactly_or_none(reader, int(host_len[0]) + 2, timeout)) != int(host_len[0]) + 2:
                return False
        elif atyp == 4:
            if len(await _read_exactly_or_none(reader, 18, timeout)) != 18:
                return False
        else:
            return False

        writer.write(b"GET / HTTP/1.1\r\nHost: example.com\r\nConnection: close\r\n\r\n")
        await writer.drain()
        data = await _read_some_or_none(reader, 12, timeout)
        return _is_http_success_response(data)
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


async def _probe_http_proxy(
    host: str,
    port: int,
    *,
    username: str = "",
    password: str = "",
    timeout: float = 5.0,
) -> bool:
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
    try:
        headers = [
            f"CONNECT {_PROXY_PROBE_HOST}:{_PROXY_PROBE_PORT} HTTP/1.1",
            f"Host: {_PROXY_PROBE_HOST}:{_PROXY_PROBE_PORT}",
            "Proxy-Connection: keep-alive",
        ]
        if username or password:
            token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
            headers.append(f"Proxy-Authorization: Basic {token}")
        request = "\r\n".join(headers).encode("ascii") + b"\r\n\r\n"
        writer.write(request)
        await writer.drain()
        response = await _read_some_or_none(reader, 1024, timeout)
        if not response.startswith(b"HTTP/1.1 200") and not response.startswith(b"HTTP/1.0 200"):
            return False
        writer.write(b"GET / HTTP/1.1\r\nHost: example.com\r\nConnection: close\r\n\r\n")
        await writer.drain()
        data = await _read_some_or_none(reader, 12, timeout)
        return _is_http_success_response(data)
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


async def _http_get_via_socks5_proxy(
    host: str,
    port: int,
    *,
    username: str = "",
    password: str = "",
    target_host: str = _PROXY_IP_TARGETS[0],
    timeout: float = 8.0,
) -> bytes:
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
    try:
        methods = [b"\x00"]
        if username or password:
            methods.append(b"\x02")
        writer.write(b"\x05" + bytes([len(methods)]) + b"".join(methods))
        await writer.drain()
        method = await _read_exactly_or_none(reader, 2, timeout)
        if len(method) != 2 or method[0] != 5:
            return b""
        if method[1] == 0x02:
            auth = username.encode("utf-8")
            secret = password.encode("utf-8")
            if len(auth) > 255 or len(secret) > 255:
                return b""
            writer.write(b"\x01" + bytes([len(auth)]) + auth + bytes([len(secret)]) + secret)
            await writer.drain()
            if await _read_exactly_or_none(reader, 2, timeout) != b"\x01\x00":
                return b""
        elif method[1] != 0x00:
            return b""

        encoded_host = target_host.encode("ascii")
        writer.write(b"\x05\x01\x00\x03" + bytes([len(encoded_host)]) + encoded_host + (80).to_bytes(2, "big"))
        await writer.drain()
        reply = await _read_exactly_or_none(reader, 4, timeout)
        if len(reply) != 4 or reply[0] != 5 or reply[1] != 0:
            return b""
        atyp = reply[3]
        if atyp == 1:
            if len(await _read_exactly_or_none(reader, 6, timeout)) != 6:
                return b""
        elif atyp == 3:
            host_len = await _read_exactly_or_none(reader, 1, timeout)
            if not host_len:
                return b""
            if len(await _read_exactly_or_none(reader, int(host_len[0]) + 2, timeout)) != int(host_len[0]) + 2:
                return b""
        elif atyp == 4:
            if len(await _read_exactly_or_none(reader, 18, timeout)) != 18:
                return b""
        else:
            return b""

        writer.write(f"GET / HTTP/1.1\r\nHost: {target_host}\r\nConnection: close\r\n\r\n".encode("ascii"))
        await writer.drain()
        return await _read_some_or_none(reader, 2048, timeout)
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


async def _http_get_via_http_proxy(
    host: str,
    port: int,
    *,
    username: str = "",
    password: str = "",
    target_host: str = _PROXY_IP_TARGETS[0],
    timeout: float = 8.0,
) -> bytes:
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
    try:
        headers = [
            f"CONNECT {target_host}:80 HTTP/1.1",
            f"Host: {target_host}:80",
            "Proxy-Connection: keep-alive",
        ]
        if username or password:
            token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
            headers.append(f"Proxy-Authorization: Basic {token}")
        writer.write("\r\n".join(headers).encode("ascii") + b"\r\n\r\n")
        await writer.drain()
        response = await _read_some_or_none(reader, 1024, timeout)
        if not response.startswith(b"HTTP/1.1 200") and not response.startswith(b"HTTP/1.0 200"):
            return b""
        writer.write(f"GET / HTTP/1.1\r\nHost: {target_host}\r\nConnection: close\r\n\r\n".encode("ascii"))
        await writer.drain()
        return await _read_some_or_none(reader, 2048, timeout)
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


async def _probe_proxy(
    host: str,
    port: int,
    *,
    username: str = "",
    password: str = "",
    timeout: float = 5.0,
) -> dict[str, str]:
    host = host.strip()
    if not host or port <= 0:
        return {"status": "dead", "protocol": "", "latency_ms": 0}
    started = time.perf_counter()

    def elapsed_ms() -> int:
        return max(0, int((time.perf_counter() - started) * 1000))

    try:
        if await _probe_socks5_proxy(host, port, username=username, password=password, timeout=timeout):
            exit_ip = await _probe_proxy_exit_ip(host, port, protocol="socks5", username=username, password=password)
            if exit_ip:
                return {
                    "status": "alive",
                    "protocol": "socks5",
                    "exit_ip": exit_ip,
                    "latency_ms": elapsed_ms(),
                }
    except Exception:
        pass
    try:
        if await _probe_http_proxy(host, port, username=username, password=password, timeout=timeout):
            exit_ip = await _probe_proxy_exit_ip(host, port, protocol="http", username=username, password=password)
            if exit_ip:
                return {
                    "status": "alive",
                    "protocol": "http",
                    "exit_ip": exit_ip,
                    "latency_ms": elapsed_ms(),
                }
    except Exception:
        pass
    return {"status": "dead", "protocol": "", "latency_ms": elapsed_ms()}


async def _probe_proxy_exit_ip(
    host: str,
    port: int,
    *,
    protocol: str,
    username: str = "",
    password: str = "",
) -> str | None:
    fetch = _http_get_via_socks5_proxy if protocol == "socks5" else _http_get_via_http_proxy
    for target_host in _PROXY_IP_TARGETS:
        try:
            response = await fetch(
                host,
                port,
                username=username,
                password=password,
                target_host=target_host,
            )
            if not _is_http_success_response(response):
                continue
            body = response.split(b"\r\n\r\n", 1)[-1].decode("utf-8", "replace").strip()
            exit_ip = egress.public_ip(body)
            if exit_ip:
                return exit_ip
        except Exception:
            continue
    return None


async def _probe_proxy_confirmed(
    host: str,
    port: int,
    *,
    username: str = "",
    password: str = "",
    retries: int = 3,
    retry_delay: float = 5.0,
) -> dict[str, str]:
    for attempt in range(max(1, retries)):
        result = await _probe_proxy(host, port, username=username, password=password)
        if result.get("status") == "alive":
            return result
        if attempt < retries - 1:
            await asyncio.sleep(retry_delay)
    return {"status": "dead", "protocol": "", "latency_ms": None}


def _proxy_scheduler_settings(config: dict[str, Any]) -> dict[str, Any]:
    enabled = str(config.get("proxy_pool_recheck_enabled", "")).strip().lower() in {"1", "true", "yes", "on"}
    interval = int(str(config.get("proxy_pool_recheck_interval_minutes", "15") or "15").strip() or 15)
    concurrency = int(str(config.get("proxy_pool_recheck_concurrency", "8") or "8").strip() or 8)
    return {
        "enabled": enabled,
        "interval_minutes": min(1440, max(15, interval)),
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


async def _worker_has_proxy_instances(worker_id: int) -> bool:
    return any(_is_active_proxy_instance(row) for row in await database.list_provider_instances(worker_id=worker_id))


async def _finalize_worker_proxy_binding(
    worker_id: int, binding_version: str, instances: list[str], *, commit: bool
) -> bool:
    """Confirm or roll back a worker binding without exposing worker errors."""
    from app.main import _proxy_to_worker  # local import avoids main -> router cycle at startup

    try:
        finalized = await _proxy_to_worker(
            worker_id,
            "POST",
            "/api/egress/bindings/finalize",
            json={"binding_version": binding_version, "instances": instances, "commit": commit},
            timeout=45,
        )
    except Exception as exc:
        logger.warning(
            "Worker binding %s finalization failed (commit=%s): %s",
            binding_version,
            commit,
            type(exc).__name__,
        )
        return False
    return bool(
        isinstance(finalized, dict)
        and finalized.get("ok")
        and str(finalized.get("binding_version") or "") == binding_version
        and str(finalized.get("action") or "") == ("confirmed" if commit else "rolled_back")
        and set(finalized.get("finalized_instances") or []) == set(instances)
    )


async def _rotate_worker_proxy_after_ack(
    worker_id: int, candidate: dict[str, Any], *, fallback: str | None = None
) -> bool:
    """Apply a candidate on the worker and commit it only after a matching ACK."""
    async with _proxy_rotation_lock(worker_id):
        return await _rotate_worker_proxy_after_ack_locked(worker_id, candidate, fallback=fallback)


async def _rotate_worker_proxy_after_ack_locked(
    worker_id: int, candidate: dict[str, Any], *, fallback: str | None = None
) -> bool:
    """Run one serialized worker rotation while holding its runtime lock."""
    current = await database.get_worker_proxy_assignment(worker_id)
    if not current or not current.get("proxy_id"):
        return False
    candidate_id = int(candidate.get("proxy_id") or candidate.get("id") or 0)
    if candidate_id <= 0:
        return False

    active_rows = [
        row for row in await database.list_provider_instances(worker_id=worker_id) if _is_active_proxy_instance(row)
    ]
    current_proxy_id = int(current.get("proxy_id") or 0)
    if any(int(row.get("proxy_id") or 0) != current_proxy_id for row in active_rows):
        # The worker-level contract requires every active proxy instance to
        # share the assignment being rotated; mixed rows need reconciliation.
        return False
    instances = [str(row["instance_id"]).strip() for row in active_rows]
    if not instances:
        return False

    binding_version = f"rotation_{secrets.token_hex(16)}"
    payload = {
        "binding_version": binding_version,
        "proxy": {**candidate, "proxy_id": candidate_id},
        "instances": instances,
    }
    from app.main import _proxy_to_worker  # local import avoids main -> router cycle at startup

    try:
        ack = await _proxy_to_worker(
            worker_id,
            "POST",
            "/api/egress/bindings/apply",
            json=payload,
            timeout=60,
        )
    except HTTPException:
        # Any worker error is ambiguous: apply may have restarted one or more
        # sidecars before returning a validation/finalization-safe 4xx response.
        await _finalize_worker_proxy_binding(worker_id, binding_version, instances, commit=False)
        return False
    except Exception:
        # Transport failure is ambiguous: the worker may have applied the
        # candidate before the response was lost. A best-effort rollback is
        # safe because finalize validates the binding token before restoring.
        await _finalize_worker_proxy_binding(worker_id, binding_version, instances, commit=False)
        return False
    ack_matches = bool(
        isinstance(ack, dict)
        and ack.get("ok")
        and str(ack.get("binding_version") or "") == binding_version
        and int(ack.get("proxy_id") or 0) == candidate_id
        and set(ack.get("applied_instances") or []) == set(instances)
    )
    if not ack_matches:
        # A 2xx apply response may have changed sidecars even if its metadata is
        # unusable. Revert that binding before leaving the old DB lease intact.
        await _finalize_worker_proxy_binding(worker_id, binding_version, instances, commit=False)
        return False
    expected_exit_ip = str(candidate.get("exit_ip") or "").strip()
    observed_exit_ip = str(ack.get("observed_exit_ip") or "").strip()
    if expected_exit_ip and observed_exit_ip != expected_exit_ip:
        await _finalize_worker_proxy_binding(worker_id, binding_version, instances, commit=False)
        return False
    if not observed_exit_ip:
        await _finalize_worker_proxy_binding(worker_id, binding_version, instances, commit=False)
        return False
    try:
        committed = await database.commit_proxy_rotation(
            worker_id,
            expected_proxy_id=int(current.get("proxy_id") or 0),
            expected_assignment_version=int(current.get("assignment_version") or 0),
            new_proxy_id=candidate_id,
            instance_ids=instances,
            fallback=str(fallback or current.get("fallback") or "rotate"),
        )
    except Exception:
        await _finalize_worker_proxy_binding(worker_id, binding_version, instances, commit=False)
        raise
    if not committed:
        await _finalize_worker_proxy_binding(worker_id, binding_version, instances, commit=False)
        return False

    confirmed = await _finalize_worker_proxy_binding(worker_id, binding_version, instances, commit=True)
    if confirmed:
        return True
    # The DB/runtime candidate is already authoritative after a successful CAS.
    # Retry cleanup once, but never roll the committed DB row back blindly.
    if await _finalize_worker_proxy_binding(worker_id, binding_version, instances, commit=True):
        return True
    logger.warning("Proxy binding %s committed; sidecar cleanup remains pending", binding_version)
    return True


async def _refresh_exit_ip_intelligence(
    proxy_exit_pairs: list[tuple[int, str]], *, concurrency: int = 8
) -> dict[str, int]:
    unique_exit_ips = list(dict.fromkeys(exit_ip for _proxy_id, exit_ip in proxy_exit_pairs if exit_ip))
    semaphore = asyncio.Semaphore(min(16, max(1, int(concurrency or 8))))

    async def lookup(exit_ip: str) -> tuple[str, dict[str, Any]]:
        async with semaphore:
            try:
                cached = await database.get_cached_proxy_intelligence(exit_ip)
                return exit_ip, cached or await lookup_ip_intelligence(exit_ip)
            except Exception as exc:
                logger.warning("Proxy intelligence lookup failed for %s: %s", exit_ip, type(exc).__name__)
                return exit_ip, {}

    intelligence_by_ip = dict(await asyncio.gather(*(lookup(exit_ip) for exit_ip in unique_exit_ips)))
    enriched = 0
    for proxy_id, exit_ip in proxy_exit_pairs:
        intelligence = intelligence_by_ip.get(exit_ip) or {}
        if intelligence and await database.update_proxy_endpoint_intelligence(proxy_id, intelligence):
            enriched += 1
    return {
        "requested": len(proxy_exit_pairs),
        "unique": len(unique_exit_ips),
        "enriched": enriched,
        "unresolved": max(0, len(proxy_exit_pairs) - enriched),
    }


async def run_proxy_pool_recheck(
    *,
    proxy_ids: list[int] | None = None,
    concurrency: int = 8,
    rotate_dead: bool = True,
    probe_retries: int = 3,
) -> dict[str, Any]:
    wanted = {int(x) for x in (proxy_ids or []) if int(x) > 0}
    rows = await database.list_proxy_pool()
    targets = [row for row in rows if not wanted or int(row["id"]) in wanted]
    semaphore = asyncio.Semaphore(min(64, max(1, int(concurrency or 8))))

    async def check(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        async with semaphore:
            proxy = await database.get_proxy_endpoint(int(row.get("id") or 0)) or row
            probe_kwargs: dict[str, Any] = {
                "username": str(proxy.get("username") or "").strip(),
                "password": str(proxy.get("password") or "").strip(),
            }
            if int(probe_retries or 3) != 3:
                probe_kwargs["retries"] = min(3, max(1, int(probe_retries or 1)))
            result = await _probe_proxy_confirmed(
                str(proxy.get("host") or "").strip(),
                int(proxy.get("port") or 0),
                **probe_kwargs,
            )
            return row, result

    checks = await asyncio.gather(*(check(row) for row in targets))
    results = {int(row["id"]): str(result.get("status") or "dead") for row, result in checks}
    protocols = {int(row["id"]): str(result.get("protocol") or "") for row, result in checks}
    exit_ips = {int(row["id"]): str(result.get("exit_ip") or "") for row, result in checks}
    checked = await database.update_proxy_pool_check_results(results, protocols=protocols, exit_ips=exit_ips)
    intelligence_jobs: list[tuple[int, str]] = []
    for row, result in checks:
        proxy_id = int(row["id"])
        await database.save_proxy_probe_result(
            proxy_id,
            profile="generic",
            probe_status=str(result.get("status") or "unknown"),
            verdict=str(result.get("status") or "unknown").upper(),
            eligibility="eligible" if result.get("status") == "alive" else "unknown",
            reason="",
            exit_ip=str(result.get("exit_ip") or ""),
            latency_ms=result.get("latency_ms"),
            probe_version="generic-v1",
            evidence={"protocol": str(result.get("protocol") or "")},
        )
        intelligence_exit_ip = str(
            result.get("exit_ip") or (row.get("exit_ip") if result.get("status") == "alive" else "") or ""
        ).strip()
        if intelligence_exit_ip:
            intelligence_jobs.append((proxy_id, intelligence_exit_ip))
    intelligence = await _refresh_exit_ip_intelligence(intelligence_jobs, concurrency=concurrency)
    duplicate_count = await database.reconcile_proxy_duplicates()

    rotated = 0
    rotate_errors = 0
    for row, result in checks if rotate_dead else []:
        if result.get("status") != "dead" or not row.get("assigned_worker_id"):
            continue
        worker_id = int(row["assigned_worker_id"])
        replacement = await database.find_available_proxy_for_worker(worker_id)
        if not replacement:
            continue
        try:
            candidate = dict(replacement)
            candidate["proxy_id"] = int(replacement.get("proxy_id") or replacement.get("id") or 0)
            if not await _rotate_worker_proxy_after_ack(worker_id, candidate):
                rotate_errors += 1
                continue
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
        "duplicates_marked": duplicate_count,
        "intelligence": intelligence,
    }


async def run_earnapp_proxy_recheck(*, proxy_ids: list[int] | None = None, concurrency: int = 8) -> dict[str, Any]:
    wanted = {int(x) for x in (proxy_ids or []) if int(x) > 0}
    rows = await database.list_proxy_pool()
    selected = [row for row in rows if not wanted or int(row["id"]) in wanted]
    targets = [row for row in selected if str(row.get("status") or "").strip().lower() != "dead"]
    semaphore = asyncio.Semaphore(min(32, max(1, int(concurrency or 8))))

    async def check(row: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        async with semaphore:
            proxy = await database.get_proxy_endpoint(int(row.get("id") or 0)) or row
            result = await probe_earnapp_proxy(
                str(proxy.get("host") or ""),
                int(proxy.get("port") or 0),
                protocol=str(proxy.get("protocol") or "socks5"),
                username=str(proxy.get("username") or ""),
                password=str(proxy.get("password") or ""),
            )
            return int(row["id"]), result

    checked_rows = await asyncio.gather(*(check(row) for row in targets))
    intelligence_jobs = []
    for proxy_id, result in checked_rows:
        await database.save_proxy_probe_result(
            proxy_id,
            profile="earnapp_wss",
            probe_status="alive" if result.get("verdict") in {"CID_SET", "BLACKLIST", "DECLINE"} else "unknown",
            verdict=str(result.get("verdict") or "UNKNOWN"),
            eligibility=str(result.get("eligibility") or "unknown"),
            reason=str(result.get("reason") or ""),
            exit_ip=str(result.get("exit_ip") or ""),
            latency_ms=result.get("latency_ms"),
            probe_version=str(result.get("probe_version") or ""),
            evidence={"profile": "earnapp_wss"},
        )
        if result.get("exit_ip"):
            value = str(result["exit_ip"]).strip()
            intelligence_jobs.append((proxy_id, value))
    intelligence = await _refresh_exit_ip_intelligence(intelligence_jobs, concurrency=concurrency)
    duplicate_count = await database.reconcile_proxy_duplicates()
    return {
        "status": "ok",
        "profile": "earnapp_wss",
        "checked": len(checked_rows),
        "eligible": sum(1 for _, result in checked_rows if result.get("eligibility") == "eligible"),
        "blocked": sum(1 for _, result in checked_rows if result.get("eligibility") == "blocked"),
        "quality_rejected": sum(1 for _, result in checked_rows if result.get("eligibility") == "quality_rejected"),
        "unknown": sum(1 for _, result in checked_rows if result.get("eligibility") == "unknown"),
        "skipped_dead": len(selected) - len(targets),
        "duplicates_marked": duplicate_count,
        "intelligence": intelligence,
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
    rows = await database.list_proxy_pool()
    return [{key: value for key, value in row.items() if key not in {"username", "password"}} for row in rows]


@router.get("/api/proxy-pool/scheduler")
async def api_proxy_pool_scheduler(request: Request) -> dict[str, Any]:
    deps._require_owner(request)
    config = await database.get_config() or {}
    return _proxy_scheduler_settings(config if isinstance(config, dict) else {})


@router.get("/api/proxy-pool/jobs/{job_id}")
async def api_proxy_pool_job(request: Request, job_id: str) -> dict[str, Any]:
    deps._require_owner(request)
    job = _proxy_recheck_jobs.get(str(job_id or "").strip())
    if not job:
        raise HTTPException(status_code=404, detail="Proxy pool job not found")
    result = dict(job)
    _prune_proxy_recheck_jobs()
    return result


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
            "exit_ip",
            "country_code",
            "country_name",
            "ip_type",
            "status",
            "earnapp_verdict",
            "earnapp_eligibility",
            "earnapp_probe_reason",
            "duplicate_egress",
            "canonical_proxy_id",
            "duplicate_reason",
            "pawns_mask_reason",
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
    proxies = [proxy for proxy in proxies if str(proxy.get("protocol") or "").lower() in {"http", "socks5"}]
    if not proxies:
        raise HTTPException(status_code=400, detail="No supported http or socks5 proxies found")
    proxy_ids = await database.upsert_proxy_endpoints_returning_ids(provider_id, proxies)
    await database.create_proxy_import_batch(
        provider_id,
        source_name=provider_name,
        raw_input=body.text,
        parsed_rows=proxies,
        proxy_ids=proxy_ids,
    )
    result: dict[str, Any] = {
        "status": "ok",
        "imported": len(proxy_ids),
        "parsed": len(proxies),
        "provider_id": provider_id,
        "proxy_ids": proxy_ids,
    }
    if body.recheck:
        config = await database.get_config() or {}
        settings = _proxy_scheduler_settings(config if isinstance(config, dict) else {})
        recent_ids = proxy_ids
        concurrency = body.concurrency or settings["concurrency"]
        if len(recent_ids) > _SYNC_EARNAPP_IMPORT_LIMIT:
            result["recheck_job"] = _schedule_proxy_import_recheck(recent_ids, concurrency)
        else:
            result["recheck"] = await run_proxy_pool_recheck(
                proxy_ids=recent_ids or None,
                concurrency=concurrency,
                rotate_dead=False,
            )
            result["earnapp_recheck"] = await run_earnapp_proxy_recheck(
                proxy_ids=recent_ids or None, concurrency=concurrency
            )
    return result


@router.delete("/api/proxy-pool")
async def api_proxy_pool_delete(request: Request, body: ProxyDeleteIn) -> dict[str, Any]:
    deps._require_owner(request)
    if body.delete_all:
        phrase = "DELETE ALL PROXY POOL"
        if body.confirmation != phrase or body.confirmation_again != phrase:
            raise HTTPException(
                status_code=400,
                detail="Delete all requires the exact phrase twice: DELETE ALL PROXY POOL",
            )
        deleted = await database.delete_all_proxy_pool()
        return {"status": "ok", "deleted": deleted, "delete_all": True}
    status = str(body.status or "").strip().lower()
    if status and status != "dead":
        raise HTTPException(status_code=400, detail="Only status=dead bulk delete is allowed")
    deleted = await database.delete_proxy_endpoints(body.proxy_ids, status=status or None)
    return {"status": "ok", "deleted": deleted}


@router.post("/api/proxy-pool/recheck")
async def api_proxy_pool_recheck(request: Request, body: ProxyRecheckIn) -> dict[str, Any]:
    deps._require_owner(request)
    config = await database.get_config() or {}
    settings = _proxy_scheduler_settings(config if isinstance(config, dict) else {})
    if str(body.profile or "generic").strip().lower() == "earnapp_wss":
        return await run_earnapp_proxy_recheck(
            proxy_ids=body.proxy_ids, concurrency=body.concurrency or settings["concurrency"]
        )
    return await run_proxy_pool_recheck(
        proxy_ids=body.proxy_ids,
        concurrency=body.concurrency or settings["concurrency"],
        rotate_dead=body.rotate_dead,
    )


@router.post("/api/proxy-pool/provider-lease")
async def api_proxy_pool_provider_lease(request: Request, body: ProviderProxyLeaseIn) -> dict[str, Any]:
    deps._require_owner(request)
    slug = body.provider_slug.strip().lower()
    if not slug or not body.instance_id.strip():
        raise HTTPException(status_code=400, detail="Provider and instance are required")
    lease = await database.lease_proxy_for_provider_instance(slug, body.worker_id, body.instance_id)
    if not lease:
        raise HTTPException(status_code=404, detail="No eligible proxy available")
    return {"status": "ok", "lease": lease}


@router.post("/api/proxy-pool/provider-release")
async def api_proxy_pool_provider_release(request: Request, body: ProviderProxyLeaseIn) -> dict[str, Any]:
    deps._require_owner(request)
    released = await database.release_proxy_for_provider_instance(
        body.provider_slug, body.worker_id, body.instance_id, reason="manual release"
    )
    return {"status": "ok", "released": released}


@router.post("/api/proxy-pool/earnapp-recheck")
async def api_proxy_pool_earnapp_recheck(request: Request, body: ProxyRecheckIn) -> dict[str, Any]:
    deps._require_owner(request)
    config = await database.get_config() or {}
    settings = _proxy_scheduler_settings(config if isinstance(config, dict) else {})
    return await run_earnapp_proxy_recheck(
        proxy_ids=body.proxy_ids, concurrency=body.concurrency or settings["concurrency"]
    )


@router.get("/api/proxy-pool/duplicates/export")
async def api_proxy_pool_duplicate_export(request: Request, raw: bool = False) -> PlainTextResponse:
    deps._require_owner(request)
    rows = await database.export_duplicate_proxy_rows(raw=raw)
    buf = io.StringIO()
    fields = ["id", "endpoint", "exit_ip", "canonical_proxy_id", "duplicate_reason", "provider_name", "raw_proxy"]
    if raw:
        fields.extend(["username", "password"])
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return PlainTextResponse(buf.getvalue(), media_type="text/csv")


@router.post("/api/workers/{worker_id}/proxy-assignment")
async def api_worker_proxy_assignment(request: Request, worker_id: int, body: ProxyAssignmentIn) -> dict[str, Any]:
    deps._require_owner(request)
    if body.mode not in proxy_egress.MODES:
        raise HTTPException(status_code=400, detail="Invalid proxy mode")
    if body.fallback not in {"hold", "rotate"}:
        raise HTTPException(status_code=400, detail="Invalid proxy fallback")
    worker = await database.get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    proxy = (
        await database.get_proxy_endpoint(body.proxy_id) if body.proxy_id and body.mode != proxy_egress.DIRECT else None
    )
    if body.mode == proxy_egress.PROXY and not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")
    active_instances = await _worker_has_proxy_instances(worker_id)
    if active_instances and body.mode != proxy_egress.PROXY:
        # A worker with live proxy sidecars cannot use the legacy worker-level
        # direct/auto write path; it would leave runtime and DB out of sync.
        raise HTTPException(status_code=409, detail="Active proxy instances require an acknowledged proxy rotation")
    if body.mode == proxy_egress.PROXY and active_instances:
        candidate = dict(proxy or {})
        candidate["proxy_id"] = body.proxy_id
        if not await _rotate_worker_proxy_after_ack(worker_id, candidate, fallback=body.fallback):
            raise HTTPException(status_code=409, detail="Worker did not acknowledge the proxy binding")
        return {"status": "ok", "applied": {"binding": "committed"}}
    ok = await database.set_worker_proxy_assignment(worker_id, body.proxy_id, body.mode, body.fallback)
    if not ok:
        raise HTTPException(status_code=404, detail="Worker or proxy not found")
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
    active_instances = await _worker_has_proxy_instances(worker_id)
    lease = (
        await database.find_available_proxy_for_worker(worker_id)
        if active_instances
        else await database.lease_proxy_for_worker(worker_id)
    )
    if not lease:
        raise HTTPException(status_code=404, detail="No available proxy")
    if active_instances:
        if not await _rotate_worker_proxy_after_ack(worker_id, lease):
            raise HTTPException(status_code=409, detail="Worker did not acknowledge the proxy binding")
        return {"status": "ok", "lease": lease, "applied": {"binding": "committed"}}
    worker = await database.get_worker(worker_id)
    payload = {
        "mode": lease.get("mode") or proxy_egress.PROXY,
        "worker_name": (worker or {}).get("name") or str(worker_id),
        "proxy": lease if (lease.get("proxy_id") and lease.get("mode") != proxy_egress.DIRECT) else None,
    }
    from app.main import _proxy_to_worker

    applied = await _proxy_to_worker(worker_id, "POST", "/api/egress/apply", json=payload, timeout=30)
    return {"status": "ok", "lease": lease, "applied": applied}
