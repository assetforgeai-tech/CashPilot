"""Discover and load stable public-IPv4 routing slots for a CashPilot worker.

The bootstrap owns host mutation. This module is deliberately pure apart from
its small CLI so the worker can consume the resulting state without gaining
permission to change host routes during a provider deploy.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

SLOTS_VERSION = 1
_SLOT_RE = re.compile(r"^ipv4-(\d{3,6})$")
_IFACE_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,64}$")


def _json_mapping(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _json_list(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _ipv4(value: object, *, public: bool = False) -> ipaddress.IPv4Address | None:
    try:
        address = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return None
    if not isinstance(address, ipaddress.IPv4Address):
        return None
    if public and not address.is_global:
        return None
    return address


def _normalise_mac(value: object) -> str:
    return re.sub(r"[^0-9a-f]", "", str(value or "").lower())


def _interface_inventory(addresses: Iterable[Mapping[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    by_name: dict[str, dict[str, Any]] = {}
    by_mac: dict[str, str] = {}
    for raw in addresses:
        name = str(raw.get("ifname") or "").strip()
        if not _IFACE_RE.fullmatch(name):
            continue
        entries: list[dict[str, Any]] = []
        for item in raw.get("addr_info") or []:
            if not isinstance(item, Mapping) or item.get("family") != "inet":
                continue
            address = _ipv4(item.get("local"))
            try:
                prefix = int(item.get("prefixlen"))
            except (TypeError, ValueError):
                continue
            if address is None or address.is_loopback or not 0 <= prefix <= 32:
                continue
            entries.append({"address": str(address), "prefix": prefix})
        by_name[name] = {"addresses": entries}
        mac = _normalise_mac(raw.get("address"))
        if mac:
            by_mac[mac] = name
    return by_name, by_mac


def _default_gateways(routes: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    gateways: dict[str, str] = {}
    for route in routes:
        if str(route.get("dst") or "") != "default":
            continue
        interface = str(route.get("dev") or "").strip()
        gateway = _ipv4(route.get("gateway"))
        if _IFACE_RE.fullmatch(interface) and gateway is not None:
            gateways.setdefault(interface, str(gateway))
    return gateways


def _used_networks(addresses: Mapping[str, Mapping[str, Any]]) -> list[ipaddress.IPv4Network]:
    networks: list[ipaddress.IPv4Network] = []
    for interface in addresses.values():
        for item in interface.get("addresses") or []:
            try:
                networks.append(ipaddress.ip_network(f"{item['address']}/{item['prefix']}", strict=False))
            except (KeyError, ValueError):
                continue
    return networks


def _bridge_network(slot_number: int, used: list[ipaddress.IPv4Network]) -> ipaddress.IPv4Network:
    """Choose a deterministic private /24 without overlapping known host nets."""
    offset = max(slot_number - 1, 0)
    candidates: list[ipaddress.IPv4Network] = []
    for second in range(253, 239, -1):
        third = (offset % 253) + 1
        candidates.append(ipaddress.ip_network(f"10.{second}.{third}.0/24"))
        offset //= 253
    for third in range(240, 255):
        candidates.append(ipaddress.ip_network(f"192.168.{third}.0/24"))
    for candidate in candidates:
        if not any(candidate.overlaps(existing) for existing in used):
            return candidate
    raise ValueError("No non-overlapping bridge subnet is available for public-IP slot")


def _previous_ids(previous_slots: Iterable[Mapping[str, Any]]) -> tuple[dict[tuple[str, str], str], int]:
    by_identity: dict[tuple[str, str], str] = {}
    maximum = 0
    for slot in previous_slots:
        slot_id = str(slot.get("slot_id") or "")
        match = _SLOT_RE.fullmatch(slot_id)
        public_ip = _ipv4(slot.get("public_ip"), public=True)
        private_ip = _ipv4(slot.get("private_ip"))
        if not match or public_ip is None or private_ip is None:
            continue
        by_identity[(str(public_ip), str(private_ip))] = slot_id
        maximum = max(maximum, int(match.group(1)))
    return by_identity, maximum


def _azure_candidates(metadata: Mapping[str, Any], by_mac: Mapping[str, str]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    interfaces = metadata.get("interface") or []
    if not isinstance(interfaces, list):
        return candidates
    for interface in interfaces:
        if not isinstance(interface, Mapping):
            continue
        name = by_mac.get(_normalise_mac(interface.get("macAddress")), "")
        ipv4 = interface.get("ipv4") or {}
        if not isinstance(ipv4, Mapping):
            continue
        subnet_value = ""
        subnets = ipv4.get("subnet") or []
        if isinstance(subnets, list):
            for subnet in subnets:
                if not isinstance(subnet, Mapping):
                    continue
                address = _ipv4(subnet.get("address"))
                try:
                    prefix = int(subnet.get("prefix"))
                except (TypeError, ValueError):
                    continue
                if address is not None and 0 <= prefix <= 32:
                    subnet_value = str(ipaddress.ip_network(f"{address}/{prefix}", strict=False))
                    break
        ip_entries = ipv4.get("ipAddress") or []
        if not isinstance(ip_entries, list):
            continue
        for item in ip_entries:
            if not isinstance(item, Mapping):
                continue
            public_ip = _ipv4(item.get("publicIpAddress"), public=True)
            private_ip = _ipv4(item.get("privateIpAddress"))
            if public_ip is None or private_ip is None:
                continue
            candidates.append(
                {
                    "public_ip": str(public_ip),
                    "private_ip": str(private_ip),
                    "interface": name,
                    "subnet": subnet_value,
                    "source": "azure_imds",
                }
            )
    return candidates


def _fallback_candidate(
    fallback_public_ip: str,
    interfaces: Mapping[str, Mapping[str, Any]],
    gateways: Mapping[str, str],
) -> list[dict[str, str]]:
    public_ip = _ipv4(fallback_public_ip, public=True)
    if public_ip is None or len(gateways) != 1:
        return []
    interface, gateway = next(iter(gateways.items()))
    addresses = list((interfaces.get(interface) or {}).get("addresses") or [])
    if len(addresses) != 1:
        return []
    item = addresses[0]
    try:
        private = _ipv4(item["address"])
        prefix = int(item["prefix"])
    except (KeyError, TypeError, ValueError):
        return []
    if private is None:
        return []
    return [
        {
            "public_ip": str(public_ip),
            "private_ip": str(private),
            "interface": interface,
            "subnet": str(ipaddress.ip_network(f"{private}/{prefix}", strict=False)),
            "gateway": gateway,
            "source": "single_ip_fallback",
        }
    ]


def discover_slots(
    azure_metadata: Mapping[str, Any],
    addresses: Iterable[Mapping[str, Any]],
    routes: Iterable[Mapping[str, Any]],
    *,
    fallback_public_ip: str = "",
    previous_slots: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Return stable, deduplicated public IPv4 slot records.

    Azure metadata is authoritative when it contains usable public/private
    mappings. The fallback is accepted only for one unambiguous default-route
    address, so an echo service can never fabricate a multi-IP topology.
    """
    interface_inventory, by_mac = _interface_inventory(addresses)
    gateways = _default_gateways(routes)
    candidates = _azure_candidates(azure_metadata, by_mac)
    if not candidates:
        candidates = _fallback_candidate(fallback_public_ip, interface_inventory, gateways)

    deduplicated: dict[str, dict[str, str]] = {}
    for candidate in candidates:
        public_ip = candidate["public_ip"]
        deduplicated.setdefault(public_ip, candidate)

    previous, next_number = _previous_ids(previous_slots)
    used = _used_networks(interface_inventory)
    slots: list[dict[str, Any]] = []
    for candidate in sorted(deduplicated.values(), key=lambda item: ipaddress.ip_address(item["public_ip"])):
        identity = (candidate["public_ip"], candidate["private_ip"])
        slot_id = previous.get(identity)
        if slot_id is None:
            next_number += 1
            slot_id = f"ipv4-{next_number:03d}"
        match = _SLOT_RE.fullmatch(slot_id)
        if match is None:
            continue
        interface = candidate.get("interface", "")
        subnet = candidate.get("subnet", "")
        gateway = candidate.get("gateway") or gateways.get(interface, "")
        try:
            subnet_value = ipaddress.ip_network(subnet, strict=False)
        except ValueError:
            subnet_value = None
        route_ready = bool(
            interface
            and _IFACE_RE.fullmatch(interface)
            and subnet_value is not None
            and _ipv4(gateway) is not None
            and ipaddress.ip_address(candidate["private_ip"]) in subnet_value
        )
        bridge = _bridge_network(int(match.group(1)), used)
        used.append(bridge)
        slots.append(
            {
                "slot_id": slot_id,
                "public_ip": candidate["public_ip"],
                "private_ip": candidate["private_ip"],
                "interface": interface,
                "subnet": str(subnet_value) if subnet_value is not None else "",
                "gateway": gateway,
                "docker_network": f"cashpilot-direct-{slot_id}",
                "bridge_subnet": str(bridge),
                "bridge_gateway": str(next(bridge.hosts())),
                "source": candidate["source"],
                "route_ready": route_ready,
            }
        )
    return slots


def load_slots(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Load validated slot state; malformed or unversioned state fails closed."""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(value, dict) or value.get("version") != SLOTS_VERSION:
        return []
    raw_slots = value.get("slots")
    if not isinstance(raw_slots, list):
        return []
    slots: list[dict[str, Any]] = []
    seen_public: set[str] = set()
    seen_ids: set[str] = set()
    for raw in raw_slots:
        if not isinstance(raw, dict):
            return []
        slot_id = str(raw.get("slot_id") or "")
        public_ip = _ipv4(raw.get("public_ip"), public=True)
        private_ip = _ipv4(raw.get("private_ip"))
        interface = str(raw.get("interface") or "")
        network = str(raw.get("docker_network") or "")
        if (
            not _SLOT_RE.fullmatch(slot_id)
            or public_ip is None
            or private_ip is None
            or not _IFACE_RE.fullmatch(interface)
            or network != f"cashpilot-direct-{slot_id}"
            or str(public_ip) in seen_public
            or slot_id in seen_ids
        ):
            return []
        seen_public.add(str(public_ip))
        seen_ids.add(slot_id)
        slots.append(dict(raw))
    return sorted(slots, key=lambda item: int(_SLOT_RE.fullmatch(str(item["slot_id"])).group(1)))


def _write_state(path: Path, slots: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({"version": SLOTS_VERSION, "slots": slots}, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o644)
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover CashPilot public IPv4 slots")
    parser.add_argument("command", choices=("discover",))
    parser.add_argument("--imds-file", type=Path)
    parser.add_argument("--addresses-file", type=Path, required=True)
    parser.add_argument("--routes-file", type=Path, required=True)
    parser.add_argument("--fallback-public-ip", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    previous = load_slots(args.output) if args.output.exists() else []
    slots = discover_slots(
        _json_mapping(args.imds_file),
        _json_list(args.addresses_file),
        _json_list(args.routes_file),
        fallback_public_ip=args.fallback_public_ip,
        previous_slots=previous,
    )
    _write_state(args.output, slots)
    return 0 if slots else 2


if __name__ == "__main__":  # pragma: no cover - exercised by the bootstrap
    raise SystemExit(main())
