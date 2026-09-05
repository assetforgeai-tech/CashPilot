"""Server-side egress geolocation and IP-type intelligence."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import httpx

_IPWHO_URL = "https://ipwho.is/{ip}"
_IPAPI_URLS = (
    "https://api.ipapi.is/?q={ip}",
    "https://us.ipapi.is/?q={ip}",
    "https://de.ipapi.is/?q={ip}",
)
_KNOWN_IP_TYPES = {"residential", "datacenter", "proxy", "vpn", "hosting", "unknown"}


def _normalize_country_code(value: Any) -> str:
    code = str(value or "").strip().upper()
    if code == "UK":
        return "GB"
    return code if len(code) == 2 and code.isalpha() else ""


def normalize_ipwho_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    data = dict(payload or {})
    if data.get("success") is not True:
        return {}
    connection = data.get("connection") if isinstance(data.get("connection"), Mapping) else {}
    security = data.get("security") if isinstance(data.get("security"), Mapping) else {}
    connection_type = str(connection.get("type") or "").strip().lower()
    result = {
        "country_code": _normalize_country_code(data.get("country_code")),
        "country_name": str(data.get("country") or "").strip(),
        "geo_source": "ipwho.is",
        "geo_confidence": "verified",
    }
    if connection_type:
        result["ip_type_source"] = "ipwho.is"
        result["ip_type"] = {
            "residential": "residential",
            "business": "residential",
            "hosting": "hosting",
            "datacenter": "datacenter",
            "mobile": "residential",
        }.get(connection_type, "unknown")
    for key, target in (("proxy", "is_proxy"), ("vpn", "is_vpn"), ("tor", "is_tor")):
        if key in security:
            result[target] = bool(security.get(key))
    return result


def normalize_ipapi_payload(payload: Mapping[str, Any] | None, *, source: str = "ipapi.is") -> dict[str, Any]:
    data = dict(payload or {})
    if not data or data.get("is_bogon") is True:
        return {}
    result: dict[str, Any] = {
        "country_code": _normalize_country_code(data.get("cc")),
        "ip_type_source": source,
    }
    for key in ("is_datacenter", "is_proxy", "is_vpn", "is_tor", "is_hosting"):
        if key in data:
            result[key] = bool(data.get(key))
    return result


def _classify_ip_type(quality: Mapping[str, Any]) -> tuple[str, str]:
    explicit = str(quality.get("ip_type") or "").strip().lower()
    if explicit in _KNOWN_IP_TYPES and explicit != "unknown":
        return explicit, "verified"
    if quality.get("is_vpn"):
        return "vpn", "verified"
    if quality.get("is_proxy") or quality.get("is_tor"):
        return "proxy", "verified"
    if quality.get("is_datacenter"):
        return "datacenter", "verified"
    if quality.get("is_hosting"):
        return "hosting", "verified"
    if quality and any(key.startswith("is_") for key in quality):
        return "residential", "inferred"
    return "unknown", "unknown"


def merge_intelligence(
    exit_ip: str,
    *,
    country: Mapping[str, Any] | None = None,
    quality: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    country_data = dict(country or {})
    quality_data = dict(quality or {})
    merged_quality = {**country_data, **quality_data}
    ip_type, confidence = _classify_ip_type(merged_quality)
    if ip_type not in _KNOWN_IP_TYPES:
        ip_type = "unknown"
        confidence = "unknown"
    country_code = _normalize_country_code(country_data.get("country_code") or quality_data.get("country_code"))
    country_name = str(country_data.get("country_name") or "").strip()
    return {
        "exit_ip": str(exit_ip or "").strip(),
        "country_code": country_code,
        "country_name": country_name,
        "location": country_name or country_code or "Unknown",
        "geo_source": str(
            country_data.get("geo_source") or (quality_data.get("ip_type_source") if country_code else "")
        ),
        "geo_confidence": str(country_data.get("geo_confidence") or ("inferred" if country_code else "unknown")),
        "ip_type": ip_type,
        "ip_type_source": str(merged_quality.get("ip_type_source") or ""),
        "ip_type_confidence": confidence,
        "lookup_status": {},
    }


def _source_name(url: str) -> str:
    return str(urlparse(url).hostname or "unknown")


def _response_status(response: Any) -> str:
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code == 429:
        return "rate_limited"
    if status_code in {401, 403}:
        return "denied"
    return f"http_{status_code}" if status_code else "invalid_response"


def _retry_after_seconds(response: Any) -> int | None:
    value = str(getattr(response, "headers", {}).get("retry-after") or "").strip()
    try:
        return max(0, int(value)) if value else None
    except ValueError:
        return None


async def _lookup_with_client(value: str, client: Any) -> dict[str, Any]:
    lookup_status: dict[str, str] = {}
    retry_after_seconds: int | None = None
    country_payload: dict[str, Any] = {}
    quality_payload: dict[str, Any] = {}

    country_source = _source_name(_IPWHO_URL)
    try:
        response = await client.get(_IPWHO_URL.format(ip=value))
        if response.status_code == 200:
            country_payload = normalize_ipwho_payload(response.json())
            lookup_status[country_source] = "ok" if country_payload else "invalid_payload"
        else:
            lookup_status[country_source] = _response_status(response)
            retry_after_seconds = _retry_after_seconds(response)
    except httpx.HTTPError as exc:
        lookup_status[country_source] = "connect_error" if isinstance(exc, httpx.ConnectError) else "http_error"
    except (ValueError, TypeError):
        lookup_status[country_source] = "invalid_payload"

    for quality_url in _IPAPI_URLS:
        source = _source_name(quality_url)
        try:
            response = await client.get(quality_url.format(ip=value))
            if response.status_code == 200:
                quality_payload = normalize_ipapi_payload(response.json(), source=source)
                lookup_status[source] = "ok" if quality_payload else "invalid_payload"
                if quality_payload:
                    break
            else:
                lookup_status[source] = _response_status(response)
                retry_after_seconds = retry_after_seconds or _retry_after_seconds(response)
                if response.status_code in {401, 403, 429}:
                    break
        except httpx.HTTPError as exc:
            lookup_status[source] = "connect_error" if isinstance(exc, httpx.ConnectError) else "http_error"
            continue
        except (ValueError, TypeError):
            lookup_status[source] = "invalid_payload"

    result = merge_intelligence(value, country=country_payload, quality=quality_payload)
    result["lookup_status"] = lookup_status
    if retry_after_seconds is not None:
        result["retry_after_seconds"] = retry_after_seconds
    return result


async def lookup_ip_intelligence(
    exit_ip: str,
    *,
    timeout: float = 8.0,
    client: Any | None = None,
    proxy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    value = str(exit_ip or "").strip()
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return merge_intelligence(value)
    if not address.is_global:
        return merge_intelligence(value)

    if client is not None:
        return await _lookup_with_client(value, client)

    limits = httpx.Limits(max_connections=2, max_keepalive_connections=0)
    client_kwargs: dict[str, Any] = {
        "timeout": timeout,
        "follow_redirects": False,
        "trust_env": False,
        "limits": limits,
    }
    if proxy:
        protocol = str(proxy.get("protocol") or "http").strip().lower()
        if protocol not in {"http", "socks5"}:
            return merge_intelligence(value)
        proxy_url = httpx.URL(
            f"{protocol}://{str(proxy.get('host') or '').strip()}:{int(proxy.get('port') or 0)}"
        ).copy_with(
            username=str(proxy.get("username") or "") or None,
            password=str(proxy.get("password") or "") or None,
        )
        client_kwargs["proxy"] = proxy_url
    async with httpx.AsyncClient(**client_kwargs) as client:
        return await _lookup_with_client(value, client)
