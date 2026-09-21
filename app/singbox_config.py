"""Render sing-box config for worker-side egress routing."""

from __future__ import annotations

import ipaddress
from typing import Any


def _is_ip(value: Any) -> bool:
    try:
        ipaddress.ip_address(str(value))
    except ValueError:
        return False
    return True


def pin_proxy_endpoint(proxy: dict[str, Any], *, resolver: Any) -> dict[str, Any]:
    """Resolve a proxy hostname once; keep lease metadata untouched."""
    result = dict(proxy)
    if not _is_ip(result.get("host")):
        resolved = str(resolver(str(result.get("host") or "")) or "").strip()
        if not _is_ip(resolved):
            raise ValueError("proxy hostname did not resolve to IPv4")
        result["host"] = resolved
    return result


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
    # A resolved proxy IP needs no bootstrap DNS exception. Hostnames retain
    # the narrow bootstrap path required to reach the proxy itself.
    if not _is_ip(proxy["host"]):
        outbound["domain_resolver"] = "bootstrap"
    if proxy.get("username"):
        outbound["username"] = proxy["username"]
    if proxy.get("password"):
        outbound["password"] = proxy["password"]
    route_rules = [
        {"action": "sniff"},
        {"port": 53, "action": "hijack-dns"},
    ]
    if _is_ip(proxy["host"]):
        # The pinned proxy transport itself must escape the TUN capture;
        # this single /32 is not a general direct-fallback route.
        route_rules.append({"ip_cidr": [f"{proxy['host']}/32"], "outbound": "direct"})
    if not _is_ip(proxy["host"]):
        route_rules.append({"domain": [proxy["host"]], "outbound": "direct"})
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
            "servers": [
                {
                    "tag": "cf",
                    "type": "https",
                    # Pin the DoH endpoint too: the sidecar has no direct DNS
                    # bootstrap, so resolving the hostname would deadlock DNS.
                    "server": "1.1.1.1",
                    "path": "/dns-query",
                    "detour": "proxy-out",
                    "tls": {"enabled": True, "server_name": "cloudflare-dns.com"},
                }
            ]
            + ([] if _is_ip(proxy["host"]) else [{"tag": "bootstrap", "type": "udp", "server": "1.1.1.1"}]),
            "rules": [] if _is_ip(proxy["host"]) else [{"domain": [proxy["host"]], "server": "bootstrap"}],
            "strategy": "ipv4_only",
            "reverse_mapping": True,
        },
        "inbounds": [
            {
                "type": "tun",
                "tag": "tun-in",
                "interface_name": interface_name,
                "address": ["172.31.255.1/30"],
                "auto_route": True,
                "route_exclude_address": [f"{proxy['host']}/32"] if _is_ip(proxy["host"]) else [],
                # Capture raw SDK sockets before strict policy routing.
                "auto_redirect": True,
                "strict_route": True,
                "stack": "system",
            }
        ],
        "outbounds": [outbound, {"type": "direct", "tag": "direct"}],
        "route": {
            "auto_detect_interface": True,
            "default_domain_resolver": "cf",
            "rules": route_rules,
            "final": "proxy-out",
        },
    }
