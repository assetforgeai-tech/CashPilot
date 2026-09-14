"""Small provider-specific automation helpers."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import threading
import time
from typing import Any

import httpx

_SPIDE_DEVICE_KEY_RE = re.compile(r"\bDevice\s+key\b\s*[:=]\s*([A-Za-z0-9][A-Za-z0-9._-]{7,})", re.I)
_UPROCK_DEVICE_ID_RE = re.compile(r"\bdevice_id=(uprock_[A-Za-z0-9._-]+)")
_WIPTER_LOGIN_READY_RE = re.compile(
    r"LOGIN_SUCCESS|Saving new token|Credential stored for service: com\.wipter\.auth\.production|Valid Wipter keyring secret detected",
    re.I,
)
_WIPTER_TRAFFIC_RE = re.compile(
    r"<<< PONG|Request ID|Upload:|Download:|<<< MESSAGE|Received data|>>> PING|SOCKS.*Connection established|HTTPS.*Request ID",
    re.I,
)


def extract_spide_device_key(logs: str) -> str | None:
    """Return the first Spide CLI Device key from container logs."""
    match = _SPIDE_DEVICE_KEY_RE.search(logs or "")
    return match.group(1) if match else None


def extract_uprock_device_id(logs: str) -> str | None:
    """Return the Uprock desktop device_id from olostep websocket logs."""
    match = _UPROCK_DEVICE_ID_RE.search(logs or "")
    return match.group(1) if match else None


def uprock_status_snapshot(status_payload: str | bytes, logs: str = "") -> dict[str, Any]:
    """Normalize Uprock daemon.sock status plus logs into worker evidence."""
    raw = status_payload.decode() if isinstance(status_payload, bytes) else str(status_payload or "")
    data = json.loads(raw)
    return {
        "ok": data.get("status") == "ok",
        "authenticated": bool(data.get("authenticated")),
        "earning": bool(data.get("earning")),
        "earn_rate": float(data.get("earn_rate") or 0),
        "version": str(data.get("version") or ""),
        "device_id": extract_uprock_device_id(logs),
    }


def wipter_status_snapshot(logs: str | bytes, *, login_state_persisted: bool = False) -> dict[str, Any]:
    """Normalize Wipter logs into worker runtime evidence."""
    text = logs.decode(errors="replace") if isinstance(logs, bytes) else str(logs or "")
    authenticated = bool(login_state_persisted or _WIPTER_LOGIN_READY_RE.search(text))
    traffic_seen = bool(_WIPTER_TRAFFIC_RE.search(text))
    return {
        "ok": authenticated or traffic_seen,
        "authenticated": authenticated,
        "earning": traffic_seen,
        "traffic_seen": traffic_seen,
    }


def _wipter_login_ready(container: Any) -> bool:
    try:
        logs = container.logs(tail=300) or b""
        if _WIPTER_LOGIN_READY_RE.search(logs.decode(errors="replace") if isinstance(logs, bytes) else str(logs)):
            return True
    except Exception:
        pass
    try:
        result = container.exec_run(
            [
                "sh",
                "-lc",
                "test -s /root/.config/wipter-app/secure-credentials.json || secret-tool search service com.wipter.auth.production >/dev/null 2>&1",
            ]
        )
        return getattr(result, "exit_code", 1) == 0
    except Exception:
        return False


def apply_wipter_post_login_restart(
    container: Any,
    *,
    timeout_seconds: int = 240,
    poll_seconds: float = 5.0,
) -> bool:
    """Restart Wipter once after token/keyring login state is persisted."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() <= deadline:
        if _wipter_login_ready(container):
            container.restart()
            return True
        time.sleep(poll_seconds)
    return False


def schedule_wipter_post_login_restart(
    container: Any,
    *,
    timeout_seconds: int = 240,
    poll_seconds: float = 5.0,
) -> threading.Thread:
    """Run the Wipter restart watcher in the background."""
    thread = threading.Thread(
        target=apply_wipter_post_login_restart,
        kwargs={
            "container": container,
            "timeout_seconds": timeout_seconds,
            "poll_seconds": poll_seconds,
        },
        daemon=True,
    )
    thread.start()
    return thread


def spide_auth_headers(credential: str) -> dict[str, str]:
    """Build Spide dashboard auth headers from a pasted bearer token or cookie."""
    value = (credential or "").strip()
    headers = {"Accept": "application/json"}
    if not value:
        return headers
    if value.lower().startswith("bearer "):
        headers["Authorization"] = value
        return headers
    if "=" in value or ";" in value:
        headers["Cookie"] = value
        match = re.search(r"(?:^|;\s*)_token=([^;]+)", value)
        if match:
            headers["Authorization"] = f"Bearer {match.group(1)}"
        return headers
    headers["Authorization"] = f"Bearer {value}"
    return headers


async def register_spide_device(
    credential: str,
    device_key: str,
    *,
    title: str,
    base_url: str = "https://spide.network",
) -> dict[str, Any]:
    """Register a Spide CLI Device key through the dashboard API."""
    for attempt in range(3):
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/api/v1/device/create",
                headers=spide_auth_headers(credential),
                data={"title": title, "device_key": device_key},
            )
        if int(getattr(resp, "status_code", 200)) < 500 or attempt == 2:
            break
        await asyncio.sleep(5)
    if getattr(resp, "is_error", False) or int(getattr(resp, "status_code", 200)) >= 400:
        detail = ""
        with contextlib.suppress(ValueError, TypeError):
            payload = resp.json()
            if isinstance(payload, dict):
                detail = str(payload.get("detail") or payload.get("message") or payload.get("error") or "")
        if not detail:
            detail = str(getattr(resp, "text", "") or "")
        detail = re.sub(r"[\r\n\t]+", " ", detail)[:240]
        raise RuntimeError(
            f"Spide device registration rejected ({resp.status_code})" + (f": {detail}" if detail else "")
        )
    try:
        return resp.json()
    except ValueError:
        return {"status": "ok"}


async def login_spide(email: str, password: str, *, base_url: str = "https://spide.network") -> str:
    """Log in using the raw CLI setup flow and return its bearer token."""
    for attempt in range(3):
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/api/v1/user/login",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "X-Requested-With": "XMLHttpRequest",
                },
                data={"email": email, "password": password},
            )
        if int(getattr(resp, "status_code", 200)) < 500 or attempt == 2:
            break
        await asyncio.sleep(5)
    resp.raise_for_status()
    payload = resp.json()
    token = str(payload.get("token") or "").strip() if isinstance(payload, dict) else ""
    if not token:
        raise RuntimeError("Spide login returned no token")
    return token
