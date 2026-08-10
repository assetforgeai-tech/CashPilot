"""Small provider-specific automation helpers."""

from __future__ import annotations

import re
from typing import Any

import httpx

_SPIDE_DEVICE_KEY_RE = re.compile(r"\bDevice\s+key\b\s*[:=]\s*([A-Za-z0-9][A-Za-z0-9._-]{7,})", re.I)


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
