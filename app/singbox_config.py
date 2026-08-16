"""Render sing-box config for worker-side egress routing."""

from __future__ import annotations

from typing import Any


def render_tun_proxy_config(
    proxy: dict[str, Any],
    *,
    worker_name: str,
    udp_direct: bool = False,
    interface_name: str = "cp-egress",
) -> dict[str, Any]:
    protocol = str(proxy.get("protocol") or "socks5").lower()
    outbound_type = "http" if protocol == "http" else "socks"
    outbound: dict[str, Any] = {
        "type": outbound_type,
        "tag": "proxy-out",
        "server": proxy["host"],
        "server_port": int(proxy["port"]),
    }
    if outbound_type == "socks":
        outbound["version"] = "5"
    if proxy.get("username"):
        outbound["username"] = proxy["username"]
    if proxy.get("password"):
        outbound["password"] = proxy["password"]
    route_rules = [
        {"port": 53, "outbound": "direct"},
        {"domain": [proxy["host"]], "outbound": "direct"},
    ]
    if udp_direct:
        route_rules.extend(
            [
                {"network": "udp", "outbound": "direct"},
                {"network": "tcp", "outbound": "proxy-out"},
            ]
        )
    return {
        "log": {"level": "info"},
        "dns": {
            "servers": [{"tag": "cf", "address": "1.1.1.1", "detour": "direct"}],
            "strategy": "ipv4_only",
        },
        "inbounds": [
            {
                "type": "tun",
                "tag": "tun-in",
                "interface_name": interface_name,
                "address": ["172.31.255.1/30"],
                "auto_route": True,
                "strict_route": True,
                "stack": "system",
            }
        ],
        "outbounds": [outbound, {"type": "direct", "tag": "direct"}],
        "route": {
            "auto_detect_interface": True,
            "rules": route_rules,
            "final": "proxy-out",
        },
    }
