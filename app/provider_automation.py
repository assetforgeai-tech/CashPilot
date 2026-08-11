"""Small provider-specific automation helpers."""

from __future__ import annotations

import io
import json
import re
import tarfile
import time
from typing import Any

import httpx

_SPIDE_DEVICE_KEY_RE = re.compile(r"\bDevice\s+key\b\s*[:=]\s*([A-Za-z0-9][A-Za-z0-9._-]{7,})", re.I)
_GRASS_STORE_PATH = "/data/profile/.local/share/io.getgrass.desktop/store.json"
_GRASS_PATCH_PATH = "/tmp/cashpilot-grass-store-patch.json"
_GRASS_STORE_KEYS = {
    "store_wynd_status": "wynd:status",
    "store_wynd_user_id": "wynd:user_id",
    "store_token_expiry": "tokenExpiry",
    "store_auto_update": "autoUpdate",
    "store_wynd_authenticated": "wynd:authenticated",
    "store_refresh_token": "refreshToken",
    "store_access_token": "accessToken",
}

def grass_store_patch(credentials: dict[str, str]) -> dict[str, str]:
    """Map deploy credentials to Grass Desktop's store.json keys."""
    missing = [key for key in _GRASS_STORE_KEYS if not str(credentials.get(key, "")).strip()]
    if missing:
        raise ValueError(f"Missing Grass deploy credential(s): {', '.join(missing)}")
    return {store_key: str(credentials[key]) for key, store_key in _GRASS_STORE_KEYS.items()}

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
    """Wait for Grass to create store.json, patch it, then restart the container."""
    patch = grass_store_patch(credentials)
    deadline = time.monotonic() + timeout_seconds
    while True:
        result = container.exec_run(["sh", "-lc", f"test -f {_GRASS_STORE_PATH}"])
        if getattr(result, "exit_code", 1) == 0:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("Grass store.json was not created before timeout")
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
    container.restart()

def extract_spide_device_key(logs: str) -> str | None:
    """Return the first Spide CLI Device key from container logs."""
    match = _SPIDE_DEVICE_KEY_RE.search(logs or "")
    return match.group(1) if match else None

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
