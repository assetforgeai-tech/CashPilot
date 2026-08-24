"""Server-side egress geolocation and IP-type intelligence."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from typing import Any

import httpx

_IPWHO_URL = "https://ipwho.is/{ip}"
_IPAPI_URLS = (
    "https://api.ipapi.is/?q={ip}",
    "https://us.ipapi.is/?q={ip}",
    "https://de.ipapi.is/?q={ip}",
)
_KNOWN_IP_TYPES = {"residential", "datacenter", "proxy", "vpn", "hosting", "unknown"}


def normalize_ipwho_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    data = dict(payload or {})
    if data.get("success") is not True:
        return {}
    return {
        "country_code": str(data.get("country_code") or "").strip().upper(),
        "country_name": str(data.get("country") or "").strip(),
        "geo_source": "ipwho.is",
        "geo_confidence": "verified",
    }


def normalize_ipapi_payload(payload: Mapping[str, Any] | None, *, source: str = "ipapi.is") -> dict[str, Any]:
    data = dict(payload or {})
    if not data or data.get("is_bogon") is True:
        return {}
    return {
        "country_code": str(data.get("cc") or "").strip().upper(),
        "is_datacenter": bool(data.get("is_datacenter")),
        "is_proxy": bool(data.get("is_proxy")),
        "is_vpn": bool(data.get("is_vpn")),
        "is_tor": bool(data.get("is_tor")),
        "is_hosting": bool(data.get("is_hosting")),
        "ip_type_source": source,
    }


def _classify_ip_type(quality: Mapping[str, Any]) -> tuple[str, str]:
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
    ip_type, confidence = _classify_ip_type(quality_data)
    if ip_type not in _KNOWN_IP_TYPES:
        ip_type = "unknown"
        confidence = "unknown"
    country_code = str(country_data.get("country_code") or quality_data.get("country_code") or "").upper()
    country_name = str(country_data.get("country_name") or "").strip()
    return {
        "exit_ip": str(exit_ip or "").strip(),
        "country_code": country_code,
        "country_name": country_name,
        "location": country_name or country_code or "Unknown",
        "geo_source": str(country_data.get("geo_source") or ("ipapi.is" if country_code else "")),
        "geo_confidence": str(country_data.get("geo_confidence") or ("inferred" if country_code else "unknown")),
        "ip_type": ip_type,
        "ip_type_source": str(quality_data.get("ip_type_source") or ""),
        "ip_type_confidence": confidence,
    }


async def lookup_ip_intelligence(exit_ip: str, *, timeout: float = 8.0) -> dict[str, Any]:
    value = str(exit_ip or "").strip()
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return merge_intelligence(value)
    if not address.is_global:
        return merge_intelligence(value)

    country_payload: dict[str, Any] = {}
    quality_payload: dict[str, Any] = {}
    limits = httpx.Limits(max_connections=2, max_keepalive_connections=0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False, limits=limits) as client:
        try:
            response = await client.get(_IPWHO_URL.format(ip=value))
            if response.status_code == 200:
                country_payload = normalize_ipwho_payload(response.json())
        except (httpx.HTTPError, ValueError, TypeError):
            pass
        for quality_url in _IPAPI_URLS:
            try:
                response = await client.get(quality_url.format(ip=value))
                if response.status_code == 200:
                    source = quality_url.split("//", 1)[-1].split("/", 1)[0]
                    quality_payload = normalize_ipapi_payload(response.json(), source=source)
                    if quality_payload:
                        break
                elif response.status_code in {401, 403, 429}:
                    # Do not fan out after an explicit provider limit or denial.
                    break
            except (httpx.HTTPError, ValueError, TypeError):
                continue
    return merge_intelligence(value, country=country_payload, quality=quality_payload)
