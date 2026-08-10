"""Proxy egress policy helpers."""

from __future__ import annotations

from typing import Any

from app import catalog

PROXY = "proxy"
DIRECT = "direct"
AUTO = "auto"

MODES = {PROXY, DIRECT, AUTO}
UDP = {"required", "optional", "none"}

def normalize_mode(value: Any, default: str = PROXY) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in MODES else default

def service_mode(service: dict[str, Any] | None, default: str = PROXY) -> str:
    return normalize_mode(catalog.service_egress_mode(service, default), default)

def service_udp(service: dict[str, Any] | None) -> str:
    return catalog.service_egress_udp(service)

def proxy_supports_udp(proxy: dict[str, Any] | None) -> bool:
    if not proxy:
        return False
    protocol = str(proxy.get("protocol") or "").strip().lower()
    return protocol == "socks5" and bool(proxy.get("udp_ok"))

def choose_mode(requested_mode: Any, service_udp: Any = "none", proxy: dict[str, Any] | None = None) -> str:
    mode = normalize_mode(requested_mode, AUTO)
    udp = str(service_udp or "none").strip().lower()
    if mode == DIRECT or not proxy:
        return DIRECT
    if udp == "required" and not proxy_supports_udp(proxy):
        return DIRECT
    return PROXY
