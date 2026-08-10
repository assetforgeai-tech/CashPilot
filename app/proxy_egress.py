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

