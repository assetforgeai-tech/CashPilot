"""Vtproxy sync-only adapter."""

from __future__ import annotations

from typing import Any

import httpx

from app import database

DEFAULT_BASE_URL = "https://vtproxy.net"


def _split_endpoint(endpoint: str) -> tuple[str, int]:
    host, port_text = str(endpoint).rsplit(":", 1)
    return host, int(port_text)


def parse_balance(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") or {}
    return {
        "balance": data.get("balance"),
        "email": data.get("email", ""),
    }


def parse_packages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    packages = (payload.get("data") or {}).get("packages") or []
    out: list[dict[str, Any]] = []
    for pkg in packages:
        if not isinstance(pkg, dict):
            continue
        out.append(
            {
                "type": str(pkg.get("type") or ""),
                "price": pkg.get("price"),
                "min_quantity": pkg.get("min_quantity"),
                "max_quantity": pkg.get("max_quantity"),
            }
        )
    return out


def parse_proxies(payload: dict[str, Any]) -> list[dict[str, Any]]:
    proxies = (payload.get("data") or {}).get("proxies") or []
    out: list[dict[str, Any]] = []
    for proxy in proxies:
        if not isinstance(proxy, dict):
            continue
        endpoint = str(proxy.get("endpoint") or "")
        if not endpoint:
            continue
        host, port = _split_endpoint(endpoint)
        out.append(
            {
                "provider_proxy_id": proxy.get("id"),
                "endpoint": endpoint,
                "host": host,
                "port": port,
                "username": str(proxy.get("username") or ""),
                "password": str(proxy.get("password") or ""),
                "protocol": str(proxy.get("protocol") or "socks5").lower(),
                "location": str(proxy.get("location") or ""),
                "status": str(proxy.get("status") or "unknown"),
                "days_left": proxy.get("days_left"),
                "hours_left": proxy.get("hours_left"),
                "expiry_date": proxy.get("expiry_date"),
            }
        )
    return out


class VtproxyClient:
    """Read-only client for the provider API."""

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key}

    async def _get(self, path: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{self.base_url}{path}", headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def balance(self) -> dict[str, Any]:
        return parse_balance(await self._get("/api/v1/public/balance"))

    async def packages(self) -> list[dict[str, Any]]:
        return parse_packages(await self._get("/api/v1/public/packages"))

    async def proxies(self) -> list[dict[str, Any]]:
        return parse_proxies(await self._get("/api/v1/public/proxies"))


async def sync_vtproxy_provider(provider: dict[str, Any]) -> dict[str, Any]:
    api_key = str(provider.get("api_key") or "").strip()
    if not api_key:
        raise ValueError("Vtproxy API key is required")
    client = VtproxyClient(api_key, provider.get("base_url") or DEFAULT_BASE_URL)
    proxies = await client.proxies()
    last_id = await database.upsert_proxy_endpoints(int(provider["id"]), proxies)
    return {"synced": len(proxies), "last_proxy_id": last_id}
