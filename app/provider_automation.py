"""Small provider-specific automation helpers."""

from __future__ import annotations

import io
import json
import re
import tarfile
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
_GRASS_STORE_PATH = "/var/lib/grass-xdg/data/io.getgrass.desktop/store.json"
_GRASS_PATCH_PATH = "/tmp/cashpilot-grass-store-patch.json"
_GRASS_REQUIRED_DEVICE_KEYS = (
    "wynd:device_id",
    "wynd:device_privkey",
    "wynd:device_pubkey",
    "wynd:device_registered_pubkey",
)
_GRASS_STORE_KEYS = {
    "store_access_token": "accessToken",
    "store_refresh_token": "refreshToken",
    "store_wynd_status": "wynd:status",
    "store_wynd_authenticated": "wynd:authenticated",
    "store_wynd_user_id": "wynd:user_id",
    "store_auto_update": "autoUpdate",
}
_GRASS_OPTIONAL_STORE_KEYS = {
    "store_wynd_device_registered_user_id": "wynd:device_registered_user_id",
}


def grass_store_patch(credentials: dict[str, str]) -> dict[str, str]:
    """Map deploy credentials to Grass Desktop's store.json keys."""
    missing = [key for key in _GRASS_STORE_KEYS if not str(credentials.get(key, "")).strip()]
    if missing:
        raise ValueError(f"Missing Grass deploy credential(s): {', '.join(missing)}")
    patch = {store_key: str(credentials[key]) for key, store_key in _GRASS_STORE_KEYS.items()}
    patch.update(
        {
            store_key: str(credentials[key])
            for key, store_key in _GRASS_OPTIONAL_STORE_KEYS.items()
            if str(credentials.get(key, "")).strip()
        }
    )
    return patch


def _tar_patch_file(payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, separators=(",", ":")).encode()
    info = tarfile.TarInfo(_GRASS_PATCH_PATH.rsplit("/", 1)[-1])
    info.size = len(data)
    info.mode = 0o600
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def apply_grass_store_patch(
    container: Any,
    credentials: dict[str, str],
    *,
    timeout_seconds: int = 90,
    poll_seconds: float = 1.0,
) -> None:
    """Wait for Grass to register a fresh device, patch auth, then restart."""
    patch = grass_store_patch(credentials)
    deadline = time.monotonic() + timeout_seconds
    while True:
        result = container.exec_run(
            [
                "python3",
                "-c",
                (
                    "import json,sys;"
                    f"store_path={_GRASS_STORE_PATH!r};"
                    "store=json.load(open(store_path));"
                    f"missing=[k for k in {_GRASS_REQUIRED_DEVICE_KEYS!r} if not str(store.get(k,'')).strip()];"
                    "sys.exit(1 if missing else 0)"
                ),
            ]
        )
        if getattr(result, "exit_code", 1) == 0:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("Grass device identity was not registered before timeout")
        time.sleep(poll_seconds)

    container.put_archive("/tmp", _tar_patch_file({"store": patch}))
    script = (
        "import json;"
        f"store_path={_GRASS_STORE_PATH!r};"
        f"patch_path={_GRASS_PATCH_PATH!r};"
        "store=json.load(open(store_path));"
        "patch=json.load(open(patch_path))['store'];"
        "store.update(patch);"
        "open(store_path,'w').write(json.dumps(store,separators=(',',':')));"
        "import os;"
        "os.remove(patch_path)"
    )
    result = container.exec_run(["python3", "-c", script])
    if getattr(result, "exit_code", 1) != 0:
        raise RuntimeError("Grass store.json patch failed")
    # Grass flushes its unauthenticated in-memory state during graceful shutdown,
    # which can overwrite the patched identity. Kill avoids the flush; explicit
    # start relaunches against the patched store.json.
    container.kill()
    container.start()


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
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/api/v1/device/create",
            headers=spide_auth_headers(credential),
            json={"title": title, "device_key": device_key},
        )
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        return {"status": "ok"}
