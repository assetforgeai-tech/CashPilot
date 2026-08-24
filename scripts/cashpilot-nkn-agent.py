#!/usr/bin/env python3
"""Restricted host-side LXD lifecycle agent for CashPilot NKN slots."""

from __future__ import annotations

import argparse
import contextlib
import ipaddress
import json
import os
import re
import socketserver
import subprocess
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from app.nkn_chaindb import validate_manifest
except ModuleNotFoundError:  # Installed helper keeps the contract beside this script.
    from nkn_chaindb import validate_manifest  # type: ignore[no-redef]

try:
    from scripts.nkn_chaindb_cache import ensure_cached_archive
except ModuleNotFoundError:  # Installed helper keeps the cache module beside this script.
    from nkn_chaindb_cache import ensure_cached_archive  # type: ignore[no-redef]

SOCKET_PATH = Path("/run/cashpilot-nkn-agent/agent.sock")
INSTANCE_PREFIX = "cashpilot-nkn-"
INNER_CONTAINER = "cashpilot-nkn"
ADOPTABLE_CANARY = "cashpilot-nkn-lxd-canary"
ADOPTABLE_INNER_CONTAINER = "nkn-lxd-canary"
IMAGE = "nknorg/nkn:latest"
PORT_RANGE = "30000-30005"
NKN_SNAPSHOT_CACHE_ROOT = Path("/var/lib/cashpilot/nkn-chaindb-cache")
NKN_SNAPSHOT_CACHE_MOUNT = "/var/lib/cashpilot/nkn-chaindb-cache"
NKN_SNAPSHOT_CACHE_DEVICE = "nkn-chaindb-cache"
_SLOT_RE = re.compile(r"^ipv4-(\d{3,6})$")
_IFACE_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,64}$")
_ADDRESS_RE = re.compile(r"^NKN[1-9A-HJ-NP-Za-km-z]{8,}$")
_NODE_ID_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_OFFICIAL_IMAGE_DIGEST_RE = re.compile(r"^nknorg/nkn@sha256:[0-9a-fA-F]{64}$")
_DEFAULT_DNS_SERVERS = ("1.1.1.1", "8.8.8.8")


class AgentError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _run(
    args: list[str],
    *,
    input_bytes: bytes | None = None,
    check: bool = True,
    timeout: int = 600,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            args,
            input=input_bytes,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AgentError(f"host command failed: {args[0]}", 503) from exc
    if check and result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip().splitlines()
        safe_detail = detail[-1][:240] if detail else "command failed"
        raise AgentError(f"{args[0]} failed: {safe_detail}", 503)
    return result


def _json_command(args: list[str]) -> Any:
    raw = _run(args).stdout
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentError(f"{args[0]} returned invalid JSON", 503) from exc


def _required_text(payload: dict[str, Any], key: str, *, maximum: int = 512) -> str:
    value = str(payload.get(key) or "").strip()
    if not value or len(value) > maximum:
        raise AgentError(f"{key} is required")
    return value


def _bounded_int(payload: dict[str, Any], key: str, minimum: int, maximum: int) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        raise AgentError(f"{key} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise AgentError(f"{key} must be an integer") from exc
    if str(value).strip() != str(number) or not minimum <= number <= maximum:
        raise AgentError(f"{key} must be between {minimum} and {maximum}")
    return number


def instance_name(slot_id: str) -> str:
    if not _SLOT_RE.fullmatch(str(slot_id or "")):
        raise AgentError("invalid NKN slot id")
    return f"{INSTANCE_PREFIX}{slot_id}"


def nkn_config(beneficiary_address: str) -> dict[str, str]:
    beneficiary = str(beneficiary_address or "").strip()
    if not _ADDRESS_RE.fullmatch(beneficiary):
        raise AgentError("beneficiary_address is invalid")
    return {
        "BeneficiaryAddr": beneficiary,
        "beneficiaryAddr": beneficiary,
        "SyncMode": "light",
        "PasswordFile": "wallet.pswd",
    }


def usable_dns_servers(values: list[str] | tuple[str, ...]) -> list[str]:
    """Keep reachable, unique resolver addresses and discard local stubs."""
    result: list[str] = []
    for value in values:
        candidate = str(value or "").strip().strip("[]")
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if address.is_loopback or address.is_unspecified or address.is_multicast or address.is_link_local:
            continue
        if candidate not in result:
            result.append(candidate)
    return result[:3]


def inner_docker_run_command(
    name: str = INNER_CONTAINER,
    *,
    dns_servers: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    if name != INNER_CONTAINER:
        raise AgentError("invalid inner NKN container name")
    selected_dns = usable_dns_servers(dns_servers or list(_DEFAULT_DNS_SERVERS)) or list(_DEFAULT_DNS_SERVERS)
    dns_args = [item for server in selected_dns for item in ("--dns", server)]
    return [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--restart",
        "always",
        "--network",
        "host",
        *dns_args,
        "-v",
        "/opt/nkn:/nkn/data",
        IMAGE,
    ]


def is_official_nkn_image(reference: str) -> bool:
    value = str(reference or "").strip()
    return value == IMAGE or _OFFICIAL_IMAGE_DIGEST_RE.fullmatch(value) is not None


def _ipv4(payload: dict[str, Any], key: str, *, global_only: bool = False) -> str:
    value = _required_text(payload, key, maximum=64)
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise AgentError(f"{key} must be IPv4") from exc
    if not isinstance(address, ipaddress.IPv4Address) or (global_only and not address.is_global):
        raise AgentError(f"{key} must be IPv4")
    return str(address)


def validate_deploy(slot_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if instance_name(slot_id) != instance_name(str(payload.get("slot_id") or "")):
        raise AgentError("slot id does not match path")
    interface = _required_text(payload, "interface", maximum=64)
    if not _IFACE_RE.fullmatch(interface):
        raise AgentError("interface is invalid")
    private_ip = _ipv4(payload, "private_ip")
    public_ip = _ipv4(payload, "public_ip", global_only=True)
    gateway = _ipv4(payload, "gateway")
    subnet_text = _required_text(payload, "subnet", maximum=64)
    try:
        subnet = ipaddress.ip_network(subnet_text, strict=False)
    except ValueError as exc:
        raise AgentError("subnet is invalid") from exc
    if not isinstance(subnet, ipaddress.IPv4Network) or ipaddress.ip_address(private_ip) not in subnet:
        raise AgentError("private_ip is outside subnet")
    wallet_json = _required_text(payload, "wallet_json", maximum=200_000)
    try:
        wallet = json.loads(wallet_json)
    except json.JSONDecodeError as exc:
        raise AgentError("wallet_json is invalid") from exc
    if not isinstance(wallet, dict) or not str(wallet.get("Address") or wallet.get("address") or "").startswith("NKN"):
        raise AgentError("wallet_json has no NKN address")
    validated = {
        "slot_id": slot_id,
        "public_ip": public_ip,
        "private_ip": private_ip,
        "interface": interface,
        "subnet": str(subnet),
        "gateway": gateway,
        "wallet_id": _bounded_int(payload, "wallet_id", 1, 2_147_483_647),
        "wallet_assignment_version": _bounded_int(payload, "wallet_assignment_version", 1, 2_147_483_647),
        "lease_client_id": _required_text(payload, "lease_client_id", maximum=256),
        "wallet_json": wallet_json,
        "wallet_pswd": _required_text(payload, "wallet_pswd", maximum=10_000),
        "beneficiary_address": _required_text(payload, "beneficiary_address", maximum=128),
        "lxd_cpu": _bounded_int(payload, "lxd_cpu", 1, 64),
        "lxd_memory_mib": _bounded_int(payload, "lxd_memory_mib", 128, 65_536),
    }
    adopt_instance = str(payload.get("adopt_instance") or "").strip()
    expected_node_id = str(payload.get("expected_node_id") or "").strip()
    if bool(adopt_instance) != bool(expected_node_id):
        raise AgentError("canary adoption requires both instance name and expected node id")
    if adopt_instance:
        if adopt_instance != ADOPTABLE_CANARY:
            raise AgentError("invalid NKN canary instance")
        if not _NODE_ID_RE.fullmatch(expected_node_id):
            raise AgentError("expected_node_id must be a 64-character hexadecimal NKN node id")
        validated["adopt_instance"] = adopt_instance
        validated["expected_node_id"] = expected_node_id.lower()
    snapshot = payload.get("chaindb_snapshot")
    if snapshot is not None:
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("manifest"), dict):
            raise AgentError("chaindb_snapshot is invalid")
        archive_url = str(snapshot.get("archive_url") or "").strip()
        parsed = urllib.parse.urlsplit(archive_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise AgentError("chaindb_snapshot archive_url must be HTTPS")
        manifest = dict(snapshot["manifest"])
        archive_key = str(manifest.get("archive_key") or "")
        prefix = str(snapshot.get("prefix") or "nkn/chaindb").strip().strip("/")
        if (
            not re.fullmatch(r"[A-Za-z0-9._/-]+", prefix)
            or ".." in prefix.split("/")
            or not archive_key.startswith(f"{prefix}/snapshots/")
            or not archive_key.endswith(".tar.zst")
        ):
            raise AgentError("chaindb_snapshot manifest is invalid")
        raw_max_age = snapshot.get("max_age_seconds", 48 * 60 * 60)
        if isinstance(raw_max_age, bool) or not 1 <= int(raw_max_age) <= 30 * 24 * 60 * 60:
            raise AgentError("chaindb_snapshot max_age_seconds is invalid")
        validated["chaindb_snapshot"] = {
            "manifest": manifest,
            "archive_url": archive_url,
            "prefix": prefix,
            "max_age_seconds": int(raw_max_age),
        }
    return validated


def _cas(payload: dict[str, Any]) -> tuple[int, int, str]:
    return (
        _bounded_int(payload, "wallet_id", 1, 2_147_483_647),
        _bounded_int(payload, "wallet_assignment_version", 1, 2_147_483_647),
        _required_text(payload, "lease_client_id", maximum=256),
    )


def require_assignment(config: dict[str, Any], payload: dict[str, Any]) -> None:
    values = config.get("config") if isinstance(config.get("config"), dict) else config
    expected = (
        int(str(values.get("user.cashpilot.nkn.wallet_id") or "0")),
        int(str(values.get("user.cashpilot.nkn.wallet_assignment_version") or "0")),
        str(values.get("user.cashpilot.nkn.lease_client_id") or ""),
    )
    if _cas(payload) != expected:
        raise AgentError("NKN slot assignment conflict", 409)


def _metadata(payload: dict[str, Any]) -> dict[str, str]:
    return {
        "user.cashpilot.managed": "true",
        "user.cashpilot.provider": "nkn",
        "user.cashpilot.nkn.slot_id": str(payload["slot_id"]),
        "user.cashpilot.nkn.public_ip": str(payload["public_ip"]),
        "user.cashpilot.nkn.private_ip": str(payload["private_ip"]),
        "user.cashpilot.nkn.interface": str(payload["interface"]),
        "user.cashpilot.nkn.subnet": str(payload["subnet"]),
        "user.cashpilot.nkn.gateway": str(payload["gateway"]),
        "user.cashpilot.nkn.wallet_id": str(payload["wallet_id"]),
        "user.cashpilot.nkn.wallet_assignment_version": str(payload["wallet_assignment_version"]),
        "user.cashpilot.nkn.lease_client_id": str(payload["lease_client_id"]),
        "user.cashpilot.nkn.lxd_cpu": str(payload["lxd_cpu"]),
        "user.cashpilot.nkn.lxd_memory_mib": str(payload["lxd_memory_mib"]),
    }


class Controller:
    def _exists(self, name: str) -> bool:
        return _run(["lxc", "info", name], check=False, timeout=30).returncode == 0

    def _config(self, name: str) -> dict[str, Any]:
        value = _json_command(["lxc", "query", f"/1.0/instances/{name}"])
        if not isinstance(value, dict):
            raise AgentError("invalid LXD instance config", 503)
        return value

    def _status(self, name: str) -> str:
        value = _json_command(["lxc", "list", name, "--format=json"])
        if not isinstance(value, list) or not value:
            return "missing"
        return str(value[0].get("status") or "unknown").lower()

    def _wait_ready(self, name: str) -> None:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if _run(["lxc", "exec", name, "--", "true"], check=False, timeout=15).returncode == 0:
                return
            time.sleep(2)
        raise AgentError("LXD instance did not become ready", 503)

    def _set_metadata(self, name: str, payload: dict[str, Any]) -> None:
        for key, value in _metadata(payload).items():
            _run(["lxc", "config", "set", name, key, value], timeout=30)

    def _node_state(self, name: str) -> dict[str, Any]:
        result = _run(
            [
                "lxc",
                "exec",
                name,
                "--",
                "sh",
                "-lc",
                "curl -fsS --max-time 5 -H 'Content-Type: application/json' "
                '-d \'{"jsonrpc":"2.0","method":"getnodestate","params":{},"id":1}\' '
                "http://127.0.0.1:30003",
            ],
            check=False,
            timeout=15,
        )
        if result.returncode != 0:
            return {}
        try:
            response = json.loads(result.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        data = response.get("result") if isinstance(response, dict) else None
        return data if isinstance(data, dict) else {}

    def _wait_node_identity(self, name: str, expected_node_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            state = self._node_state(name)
            if str(state.get("id") or "").lower() == expected_node_id.lower():
                return state
            time.sleep(2)
        raise AgentError("NKN node identity did not return after LXD restart", 503)

    def _inner_container_names(self, name: str) -> set[str]:
        result = _run(
            ["lxc", "exec", name, "--", "docker", "ps", "-a", "--format", "{{.Names}}"],
            timeout=30,
        )
        return {line.strip() for line in result.stdout.decode("utf-8", errors="replace").splitlines() if line.strip()}

    def _verify_adoptable_inner(self, name: str, inner_name: str) -> None:
        value = _json_command(["lxc", "exec", name, "--", "docker", "inspect", inner_name])
        if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
            raise AgentError("invalid NKN canary Docker metadata", 409)
        info = value[0]
        config = info.get("Config") if isinstance(info.get("Config"), dict) else {}
        host_config = info.get("HostConfig") if isinstance(info.get("HostConfig"), dict) else {}
        restart = host_config.get("RestartPolicy") if isinstance(host_config.get("RestartPolicy"), dict) else {}
        mounts = info.get("Mounts") if isinstance(info.get("Mounts"), list) else []
        data_mount_ok = any(
            isinstance(mount, dict)
            and str(mount.get("Source") or "") == "/opt/nkn"
            and str(mount.get("Destination") or "") == "/nkn/data"
            for mount in mounts
        )
        if (
            not is_official_nkn_image(str(config.get("Image") or ""))
            or str(host_config.get("NetworkMode") or "") != "host"
            or str(restart.get("Name") or "") != "always"
            or not data_mount_ok
        ):
            raise AgentError("NKN canary runtime does not match the official preserved-data contract", 409)

    def _verify_lxd_contract(self, config: dict[str, Any], payload: dict[str, Any]) -> None:
        values = config.get("config") if isinstance(config.get("config"), dict) else {}
        try:
            cpu = int(str(values.get("limits.cpu") or ""))
        except ValueError as exc:
            raise AgentError("NKN canary CPU limit is not a fixed integer", 409) from exc
        memory_text = str(values.get("limits.memory") or "").strip()
        memory_match = re.fullmatch(r"(\d+)(MiB|GiB)", memory_text, re.IGNORECASE)
        if memory_match is None:
            raise AgentError("NKN canary memory limit is not an explicit MiB/GiB value", 409)
        memory_mib = int(memory_match.group(1)) * (1024 if memory_match.group(2).lower() == "gib" else 1)
        if cpu != int(payload["lxd_cpu"]) or memory_mib != int(payload["lxd_memory_mib"]):
            raise AgentError("NKN LXD limits do not match server Settings", 409)
        required = {
            "limits.memory.enforce": "hard",
            "limits.memory.swap": "false",
            "security.nesting": "true",
            "security.syscalls.intercept.mknod": "true",
            "security.syscalls.intercept.setxattr": "true",
            "security.syscalls.intercept.sysinfo": "true",
        }
        if any(str(values.get(key) or "").lower() != expected for key, expected in required.items()):
            raise AgentError("NKN LXD hard runtime contract is incomplete", 409)

    def _adopt_instance(
        self,
        source: str,
        target: str,
        expected_node_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if source != ADOPTABLE_CANARY or target != instance_name(str(payload["slot_id"])):
            raise AgentError("invalid NKN canary adoption target")
        if not self._exists(source):
            raise AgentError("NKN LXD canary not found", 404)
        if self._exists(target):
            raise AgentError("NKN target instance already exists", 409)
        if self._status(source) != "running":
            raise AgentError("NKN LXD canary must be running for identity verification", 409)
        source_config = self._config(source)
        values = source_config.get("config") if isinstance(source_config.get("config"), dict) else {}
        provider = str(values.get("user.cashpilot.provider") or "")
        if provider and provider != "nkn":
            raise AgentError("canary is managed by another provider", 409)
        self._verify_lxd_contract(source_config, payload)
        before = self._node_state(source)
        if str(before.get("id") or "").lower() != expected_node_id.lower():
            raise AgentError("NKN canary node id does not match the adoption guard", 409)
        if str(before.get("syncState") or before.get("sync_state") or "") != "PERSIST_FINISHED":
            raise AgentError("NKN canary is not fully synchronized", 409)

        names = self._inner_container_names(source)
        candidates = names.intersection({INNER_CONTAINER, ADOPTABLE_INNER_CONTAINER})
        if len(candidates) != 1 or names != candidates:
            raise AgentError("NKN canary has an unexpected inner Docker layout", 409)
        inner_name = candidates.pop()
        self._verify_adoptable_inner(source, inner_name)

        inner_renamed = False
        instance_moved = False
        try:
            if inner_name != INNER_CONTAINER:
                _run(["lxc", "exec", source, "--", "docker", "rename", inner_name, INNER_CONTAINER], timeout=30)
                inner_renamed = True
            _run(["lxc", "stop", source, "--timeout", "60"], timeout=90)
            _run(["lxc", "move", source, target], timeout=180)
            instance_moved = True
            _run(["lxc", "config", "set", target, "boot.autostart", "true"], timeout=30)
            _run(["lxc", "start", target], timeout=120)
            self._wait_ready(target)
            after = self._wait_node_identity(target, expected_node_id)
            self._ensure_network(target, payload)
            _run(
                ["lxc", "exec", target, "--", "docker", "update", "--restart", "always", INNER_CONTAINER],
                timeout=30,
            )
            self._set_metadata(target, payload)
        except Exception:
            current = target if instance_moved else source
            if instance_moved and self._exists(target):
                if self._status(target) == "running":
                    _run(["lxc", "stop", target, "--timeout", "60"], check=False, timeout=90)
                if _run(["lxc", "move", target, source], check=False, timeout=180).returncode == 0:
                    current = source
                    _run(["lxc", "start", source], check=False, timeout=120)
            if inner_renamed and self._exists(current):
                if self._status(current) != "running":
                    _run(["lxc", "start", current], check=False, timeout=120)
                _run(
                    ["lxc", "exec", current, "--", "docker", "rename", INNER_CONTAINER, ADOPTABLE_INNER_CONTAINER],
                    check=False,
                    timeout=30,
                )
            raise

        sync_state = str(after.get("syncState") or after.get("sync_state") or "")
        return {
            "container_id": target,
            "instance_id": target,
            "slot_id": str(payload["slot_id"]),
            "running": True,
            "online": sync_state == "PERSIST_FINISHED",
            "rpc_reachable": True,
            "runtime_backend": "lxd",
            "sync_state": sync_state,
            "node_id": str(after.get("id") or ""),
            "adopted_from": source,
        }

    def _instance_ip(self, name: str) -> str:
        self._wait_ready(name)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            result = _run(
                ["lxc", "exec", name, "--", "ip", "-j", "-4", "address", "show", "dev", "eth0"],
                check=False,
                timeout=20,
            )
            if result.returncode == 0:
                try:
                    rows = json.loads(result.stdout.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    rows = []
                for row in rows if isinstance(rows, list) else []:
                    for address in row.get("addr_info") or []:
                        value = str(address.get("local") or "")
                        try:
                            parsed = ipaddress.ip_address(value)
                        except ValueError:
                            continue
                        if isinstance(parsed, ipaddress.IPv4Address) and not parsed.is_loopback:
                            return str(parsed)
            time.sleep(2)
        raise AgentError("LXD instance has no IPv4 address", 503)

    def _pin_instance_ip(self, name: str, address: str) -> None:
        config = self._config(name)
        devices = config.get("devices") if isinstance(config.get("devices"), dict) else {}
        eth0 = devices.get("eth0") if isinstance(devices.get("eth0"), dict) else None
        if eth0 is None:
            _run(["lxc", "config", "device", "override", name, "eth0", f"ipv4.address={address}"], timeout=30)
        elif str(eth0.get("ipv4.address") or "") != address:
            _run(["lxc", "config", "device", "set", name, "eth0", "ipv4.address", address], timeout=30)

    def _ensure_proxy_device(self, name: str, device: str, protocol: str, private_ip: str, lxd_ip: str) -> None:
        config = self._config(name)
        devices = config.get("devices") if isinstance(config.get("devices"), dict) else {}
        desired = {
            "type": "proxy",
            "listen": f"{protocol}:{private_ip}:{PORT_RANGE}",
            "connect": f"{protocol}:{lxd_ip}:{PORT_RANGE}",
            "nat": "true",
        }
        current = devices.get(device) if isinstance(devices.get(device), dict) else None
        if current and all(str(current.get(key) or "") == value for key, value in desired.items()):
            return
        if current:
            _run(["lxc", "config", "device", "remove", name, device], timeout=30)
        _run(
            [
                "lxc",
                "config",
                "device",
                "add",
                name,
                device,
                "proxy",
                f"listen={desired['listen']}",
                f"connect={desired['connect']}",
                "nat=true",
            ],
            timeout=60,
        )

    def _ensure_host_routing(self, name: str, payload: dict[str, Any], lxd_ip: str) -> None:
        match = _SLOT_RE.fullmatch(str(payload["slot_id"]))
        if match is None:
            raise AgentError("invalid NKN slot id")
        slot_number = int(match.group(1))
        table = 20_000 + slot_number
        priority = 30_000 + slot_number
        private_ip = str(payload["private_ip"])
        interface = str(payload["interface"])
        subnet = str(payload["subnet"])
        gateway = str(payload["gateway"])
        prefix = subnet.split("/", 1)[1]
        address_check = _run(["ip", "-4", "address", "show", "dev", interface], timeout=30).stdout.decode(
            "utf-8", errors="replace"
        )
        if f"{private_ip}/{prefix}" not in address_check:
            _run(["ip", "address", "add", f"{private_ip}/{prefix}", "dev", interface], timeout=30)
        _run(["ip", "route", "replace", subnet, "dev", interface, "src", private_ip, "table", str(table)])
        _run(
            [
                "ip",
                "route",
                "replace",
                "default",
                "via",
                gateway,
                "dev",
                interface,
                "src",
                private_ip,
                "table",
                str(table),
            ]
        )
        _run(
            ["ip", "rule", "del", "from", f"{lxd_ip}/32", "table", str(table), "priority", str(priority)],
            check=False,
            timeout=30,
        )
        _run(["ip", "rule", "add", "from", f"{lxd_ip}/32", "table", str(table), "priority", str(priority)])
        forward_rules = [
            [
                "iptables",
                "-D",
                "FORWARD",
                "-s",
                f"{lxd_ip}/32",
                "-o",
                interface,
                "-m",
                "comment",
                "--comment",
                f"cashpilot-nkn-{payload['slot_id']}-egress",
                "-j",
                "ACCEPT",
            ],
            [
                "iptables",
                "-D",
                "FORWARD",
                "-d",
                f"{lxd_ip}/32",
                "-i",
                interface,
                "-m",
                "conntrack",
                "--ctstate",
                "RELATED,ESTABLISHED",
                "-m",
                "comment",
                "--comment",
                f"cashpilot-nkn-{payload['slot_id']}-return",
                "-j",
                "ACCEPT",
            ],
        ]
        for forward_rule in forward_rules:
            for _ in range(8):
                if _run(forward_rule, check=False, timeout=30).returncode != 0:
                    break
        for forward_rule in forward_rules:
            _run(["iptables", "-I", "FORWARD", "1", *forward_rule[3:]], timeout=30)
        rule = [
            "iptables",
            "-t",
            "nat",
            "POSTROUTING",
            "-s",
            f"{lxd_ip}/32",
            "-o",
            interface,
            "-m",
            "comment",
            "--comment",
            f"cashpilot-nkn-{payload['slot_id']}",
            "-j",
            "SNAT",
            "--to-source",
            private_ip,
        ]
        for _ in range(8):
            if _run(["iptables", "-t", "nat", "-D", *rule[3:]], check=False, timeout=30).returncode != 0:
                break
        _run(["iptables", "-t", "nat", "-I", *rule[3:]], timeout=30)
        _run(["lxc", "config", "set", name, "user.cashpilot.nkn.lxd_ip", lxd_ip], timeout=30)

    def _ensure_network(self, name: str, payload: dict[str, Any]) -> str:
        lxd_ip = self._instance_ip(name)
        self._pin_instance_ip(name, lxd_ip)
        self._ensure_proxy_device(name, "nkn-tcp", "tcp", str(payload["private_ip"]), lxd_ip)
        self._ensure_proxy_device(name, "nkn-udp", "udp", str(payload["private_ip"]), lxd_ip)
        self._ensure_host_routing(name, payload, lxd_ip)
        return lxd_ip

    def _inner_exists(self, name: str) -> bool:
        return (
            _run(
                ["lxc", "exec", name, "--", "docker", "inspect", INNER_CONTAINER],
                check=False,
                timeout=30,
            ).returncode
            == 0
        )

    def _inner_dns_servers(self, name: str) -> list[str]:
        """Read the platform resolver and avoid inheriting 127.0.0.53."""
        result = _run(
            [
                "lxc",
                "exec",
                name,
                "--",
                "sh",
                "-lc",
                "for file in /run/systemd/resolve/resolv.conf /etc/resolv.conf; do "
                'test -r "$file" && awk \'$1 == "nameserver" {print $2}\' "$file"; done',
            ],
            check=False,
            timeout=30,
        )
        raw = result.stdout.decode("utf-8", errors="replace").split()
        return usable_dns_servers(raw) or list(_DEFAULT_DNS_SERVERS)

    def _install_docker(self, name: str) -> None:
        if _run(["lxc", "exec", name, "--", "sh", "-lc", "command -v docker"], check=False, timeout=30).returncode:
            _run(
                [
                    "lxc",
                    "exec",
                    name,
                    "--",
                    "env",
                    "DEBIAN_FRONTEND=noninteractive",
                    "sh",
                    "-lc",
                    "apt-get update && apt-get install -y docker.io curl ca-certificates iproute2 zstd",
                ],
                timeout=900,
            )
        _run(["lxc", "exec", name, "--", "systemctl", "enable", "--now", "docker"], timeout=120)

    def _write_inner_file(self, name: str, path: str, payload: bytes, mode: str) -> None:
        parent = str(PurePosixPath(path).parent)
        command = f"install -d -m 0700 {parent} && umask 077; cat > {path}; chmod {mode} {path}"
        _run(["lxc", "exec", name, "--", "sh", "-lc", command], input_bytes=payload, timeout=60)

    def _ensure_snapshot_cache_device(self, name: str) -> None:
        NKN_SNAPSHOT_CACHE_ROOT.mkdir(mode=0o755, parents=True, exist_ok=True)
        config = self._config(name)
        devices = config.get("devices") if isinstance(config.get("devices"), dict) else {}
        current = devices.get(NKN_SNAPSHOT_CACHE_DEVICE)
        desired = {
            "type": "disk",
            "source": str(NKN_SNAPSHOT_CACHE_ROOT),
            "path": NKN_SNAPSHOT_CACHE_MOUNT,
            "readonly": "true",
        }
        if isinstance(current, dict) and all(str(current.get(key) or "") == value for key, value in desired.items()):
            return
        if current is not None:
            _run(["lxc", "config", "device", "remove", name, NKN_SNAPSHOT_CACHE_DEVICE], timeout=30)
        _run(
            [
                "lxc",
                "config",
                "device",
                "add",
                name,
                NKN_SNAPSHOT_CACHE_DEVICE,
                "disk",
                f"source={NKN_SNAPSHOT_CACHE_ROOT}",
                f"path={NKN_SNAPSHOT_CACHE_MOUNT}",
                "readonly=true",
            ],
            timeout=60,
        )

    def _install_snapshot(self, name: str, snapshot: dict[str, Any]) -> None:
        max_age_seconds = int(snapshot["max_age_seconds"])
        manifest = validate_manifest(snapshot["manifest"], max_age_seconds=max_age_seconds)
        prefix = str(snapshot["prefix"])
        if not str(manifest["archive_key"]).startswith(f"{prefix}/snapshots/"):
            raise AgentError("chaindb_snapshot prefix does not match archive")
        cached = ensure_cached_archive(
            str(snapshot["archive_url"]),
            expected_sha256=str(manifest["sha256"]),
            expected_size=int(manifest["size_bytes"]),
            cache_root=NKN_SNAPSHOT_CACHE_ROOT,
        )
        self._ensure_snapshot_cache_device(name)
        _run(
            [
                "lxc",
                "exec",
                name,
                "--",
                "sh",
                "-lc",
                "command -v zstd >/dev/null 2>&1 || (apt-get update && apt-get install -y zstd)",
            ],
            timeout=900,
        )
        script = Path(__file__).with_name("nkn_chaindb_restore.py").read_bytes()
        contract = Path(__file__).with_name("nkn_chaindb.py").read_bytes()
        self._write_inner_file(name, "/usr/local/lib/cashpilot/nkn_chaindb.py", contract, "0644")
        self._write_inner_file(name, "/usr/local/sbin/cashpilot-nkn-chaindb-restore", script, "0755")
        request = json.dumps(
            {
                "manifest": manifest,
                "archive_path": f"{NKN_SNAPSHOT_CACHE_MOUNT}/{cached.path.name}",
                "data_dir": "/opt/nkn",
                "container": INNER_CONTAINER,
                "prefix": prefix,
                "max_age_seconds": max_age_seconds,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        self._write_inner_file(name, "/run/cashpilot-nkn-chaindb-request.json", request, "0600")
        try:
            _run(
                [
                    "lxc",
                    "exec",
                    name,
                    "--",
                    "env",
                    "PYTHONPATH=/usr/local/lib/cashpilot",
                    "python3",
                    "/usr/local/sbin/cashpilot-nkn-chaindb-restore",
                    "--data-dir",
                    "/opt/nkn",
                    "--archive",
                    "/opt/nkn/.chaindb-placeholder.tar.zst",
                    "--sha256",
                    "0" * 64,
                    "--size-bytes",
                    "1",
                    "--request",
                    "/run/cashpilot-nkn-chaindb-request.json",
                ],
                timeout=6 * 60 * 60,
            )
        finally:
            _run(
                ["lxc", "exec", name, "--", "rm", "-f", "/run/cashpilot-nkn-chaindb-request.json"],
                check=False,
                timeout=30,
            )

    def _provision_inner(self, name: str, payload: dict[str, Any]) -> str:
        self._install_docker(name)
        if self._inner_exists(name):
            _run(
                ["lxc", "exec", name, "--", "docker", "update", "--restart", "always", INNER_CONTAINER],
                timeout=30,
            )
            _run(["lxc", "exec", name, "--", "docker", "start", INNER_CONTAINER], check=False, timeout=60)
            return "skipped"
        files_ready = (
            _run(
                [
                    "lxc",
                    "exec",
                    name,
                    "--",
                    "sh",
                    "-lc",
                    "test -s /opt/nkn/wallet.json && test -s /opt/nkn/wallet.pswd && test -s /opt/nkn/config.json",
                ],
                check=False,
                timeout=30,
            ).returncode
            == 0
        )
        if not files_ready:
            config = json.dumps(nkn_config(str(payload["beneficiary_address"])), indent=2).encode("utf-8") + b"\n"
            self._write_inner_file(name, "/opt/nkn/config.json", config, "0644")
            self._write_inner_file(name, "/opt/nkn/wallet.json", str(payload["wallet_json"]).encode("utf-8"), "0600")
            self._write_inner_file(name, "/opt/nkn/wallet.pswd", str(payload["wallet_pswd"]).encode("utf-8"), "0600")
        _run(["lxc", "exec", name, "--", "docker", "pull", IMAGE], timeout=900)
        _run(
            [
                "lxc",
                "exec",
                name,
                "--",
                *inner_docker_run_command(dns_servers=self._inner_dns_servers(name)),
            ],
            timeout=120,
        )
        snapshot_status = "skipped"
        if isinstance(payload.get("chaindb_snapshot"), dict):
            try:
                self._install_snapshot(name, dict(payload["chaindb_snapshot"]))
                snapshot_status = "restored"
            except Exception:
                # Snapshot acceleration is optional. A new node must still be
                # allowed to sync normally when R2, checksum, or extraction fails.
                snapshot_status = "fallback"
                _run(["lxc", "exec", name, "--", "docker", "start", INNER_CONTAINER], check=False, timeout=60)
        return snapshot_status

    def deploy(self, raw_payload: dict[str, Any]) -> dict[str, Any]:
        slot_id = str(raw_payload.get("slot_id") or "")
        payload = validate_deploy(slot_id, raw_payload)
        name = instance_name(slot_id)
        if payload.get("adopt_instance"):
            if self._exists(name):
                raise AgentError("NKN target instance already exists", 409)
            return self._adopt_instance(
                str(payload["adopt_instance"]),
                name,
                str(payload["expected_node_id"]),
                payload,
            )
        if self._exists(name):
            config = self._config(name)
            require_assignment(config, payload)
            self._verify_lxd_contract(config, payload)
            if self._status(name) != "running":
                _run(["lxc", "config", "set", name, "boot.autostart", "true"], timeout=30)
                _run(["lxc", "start", name], timeout=120)
        else:
            _run(
                [
                    "lxc",
                    "launch",
                    "ubuntu:24.04",
                    name,
                    "-c",
                    f"limits.cpu={payload['lxd_cpu']}",
                    "-c",
                    f"limits.memory={payload['lxd_memory_mib']}MiB",
                    "-c",
                    "limits.memory.enforce=hard",
                    "-c",
                    "limits.memory.swap=false",
                    "-c",
                    "security.nesting=true",
                    "-c",
                    "security.syscalls.intercept.mknod=true",
                    "-c",
                    "security.syscalls.intercept.setxattr=true",
                    "-c",
                    "security.syscalls.intercept.sysinfo=true",
                    "-c",
                    "boot.autostart=true",
                ],
                timeout=900,
            )
            self._set_metadata(name, payload)
        self._wait_ready(name)
        self._ensure_network(name, payload)
        snapshot_status = self._provision_inner(name, payload)
        evidence = self.evidence(slot_id, payload)
        return {
            "container_id": name,
            "instance_id": name,
            "slot_id": slot_id,
            "snapshot_status": snapshot_status,
            **evidence,
        }

    def _assigned(self, slot_id: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        name = instance_name(slot_id)
        if not self._exists(name):
            raise AgentError("NKN LXD instance not found", 404)
        config = self._config(name)
        require_assignment(config, payload)
        return name, config

    def suspend(self, slot_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        name, _ = self._assigned(slot_id, payload)
        if self._status(name) == "running":
            _run(
                ["lxc", "exec", name, "--", "docker", "update", "--restart", "no", INNER_CONTAINER],
                check=False,
                timeout=30,
            )
            _run(["lxc", "exec", name, "--", "docker", "stop", "-t", "30", INNER_CONTAINER], check=False, timeout=60)
            _run(["lxc", "config", "set", name, "boot.autostart", "false"], timeout=30)
            _run(["lxc", "stop", name, "--timeout", "60"], timeout=90)
        return {"instance_id": name, "slot_id": slot_id, "status": "stopped"}

    def resume(self, slot_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        name, config = self._assigned(slot_id, payload)
        _run(["lxc", "config", "set", name, "boot.autostart", "true"], timeout=30)
        if self._status(name) != "running":
            _run(["lxc", "start", name], timeout=120)
        values = config.get("config") if isinstance(config.get("config"), dict) else {}
        route_payload = {
            "slot_id": slot_id,
            "private_ip": values.get("user.cashpilot.nkn.private_ip", ""),
            "interface": values.get("user.cashpilot.nkn.interface", ""),
            "subnet": values.get("user.cashpilot.nkn.subnet", ""),
            "gateway": values.get("user.cashpilot.nkn.gateway", ""),
        }
        self._ensure_network(name, route_payload)
        _run(
            ["lxc", "exec", name, "--", "docker", "update", "--restart", "always", INNER_CONTAINER],
            timeout=30,
        )
        _run(["lxc", "exec", name, "--", "docker", "start", INNER_CONTAINER], check=False, timeout=60)
        return {"instance_id": name, "slot_id": slot_id, "status": "running"}

    def _cleanup_routing(self, config: dict[str, Any]) -> None:
        values = config.get("config") if isinstance(config.get("config"), dict) else {}
        slot_id = str(values.get("user.cashpilot.nkn.slot_id") or "")
        match = _SLOT_RE.fullmatch(slot_id)
        lxd_ip = str(values.get("user.cashpilot.nkn.lxd_ip") or "")
        interface = str(values.get("user.cashpilot.nkn.interface") or "")
        private_ip = str(values.get("user.cashpilot.nkn.private_ip") or "")
        if match and lxd_ip:
            table = 20_000 + int(match.group(1))
            priority = 30_000 + int(match.group(1))
            _run(
                ["ip", "rule", "del", "from", f"{lxd_ip}/32", "table", str(table), "priority", str(priority)],
                check=False,
                timeout=30,
            )
        if match and lxd_ip and interface and private_ip:
            forward_rules = [
                [
                    "iptables",
                    "-D",
                    "FORWARD",
                    "-s",
                    f"{lxd_ip}/32",
                    "-o",
                    interface,
                    "-m",
                    "comment",
                    "--comment",
                    f"cashpilot-nkn-{slot_id}-egress",
                    "-j",
                    "ACCEPT",
                ],
                [
                    "iptables",
                    "-D",
                    "FORWARD",
                    "-d",
                    f"{lxd_ip}/32",
                    "-i",
                    interface,
                    "-m",
                    "conntrack",
                    "--ctstate",
                    "RELATED,ESTABLISHED",
                    "-m",
                    "comment",
                    "--comment",
                    f"cashpilot-nkn-{slot_id}-return",
                    "-j",
                    "ACCEPT",
                ],
            ]
            for forward_rule in forward_rules:
                for _ in range(8):
                    if _run(forward_rule, check=False, timeout=30).returncode != 0:
                        break
            rule = [
                "iptables",
                "-t",
                "nat",
                "-D",
                "POSTROUTING",
                "-s",
                f"{lxd_ip}/32",
                "-o",
                interface,
                "-m",
                "comment",
                "--comment",
                f"cashpilot-nkn-{slot_id}",
                "-j",
                "SNAT",
                "--to-source",
                private_ip,
            ]
            for _ in range(8):
                if _run(rule, check=False, timeout=30).returncode != 0:
                    break

    def remove(self, slot_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        name, config = self._assigned(slot_id, payload)
        self._cleanup_routing(config)
        _run(["lxc", "delete", name, "--force"], timeout=180)
        return {"instance_id": name, "slot_id": slot_id, "deleted_volume": True}

    def evidence(self, slot_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        name, _ = self._assigned(slot_id, payload)
        running = self._status(name) == "running"
        evidence: dict[str, Any] = {"running": running, "online": False, "runtime_backend": "lxd"}
        if not running:
            return evidence
        data = self._node_state(name)
        if not data:
            return evidence
        sync_state = str(data.get("syncState") or data.get("sync_state") or "")
        node_id = str(data.get("id") or data.get("nodeId") or data.get("node_id") or "")
        evidence.update(
            {
                "rpc_reachable": True,
                "sync_state": sync_state,
                "online": sync_state == "PERSIST_FINISHED",
            }
        )
        if node_id:
            evidence["node_id"] = node_id
        return evidence

    def reconcile_all(self) -> None:
        value = _json_command(["lxc", "list", "--format=json"])
        for item in value if isinstance(value, list) else []:
            name = str(item.get("name") or "")
            if not name.startswith(INSTANCE_PREFIX) or str(item.get("status") or "").lower() != "running":
                continue
            try:
                config = self._config(name)
                values = config.get("config") if isinstance(config.get("config"), dict) else {}
                slot_id = str(values.get("user.cashpilot.nkn.slot_id") or "")
                if instance_name(slot_id) != name:
                    continue
                self._ensure_network(
                    name,
                    {
                        "slot_id": slot_id,
                        "private_ip": values.get("user.cashpilot.nkn.private_ip", ""),
                        "interface": values.get("user.cashpilot.nkn.interface", ""),
                        "subnet": values.get("user.cashpilot.nkn.subnet", ""),
                        "gateway": values.get("user.cashpilot.nkn.gateway", ""),
                    },
                )
            except AgentError:
                continue


def dispatch(method: str, path: str, payload: dict[str, Any], controller: Any) -> dict[str, Any]:
    match = re.fullmatch(r"/v1/slots/(ipv4-\d{3,6})(?:/(suspend|resume|evidence))?", path)
    if match is None:
        raise AgentError("unknown NKN helper endpoint", 404)
    slot_id, action = match.groups()
    if method == "POST" and action is None:
        payload = dict(payload)
        payload["slot_id"] = slot_id
        return controller.deploy(payload)
    if method == "POST" and action in {"suspend", "resume", "evidence"}:
        return getattr(controller, action)(slot_id, payload)
    if method == "DELETE" and action is None:
        return controller.remove(slot_id, payload)
    raise AgentError("method not allowed", 405)


class _Handler(BaseHTTPRequestHandler):
    controller = Controller()

    def _handle(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 500_000:
                raise AgentError("request body too large", 413)
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise AgentError("request body must be an object")
            result = dispatch(self.command, self.path, payload, self.controller)
            self._json(200, result)
        except AgentError as exc:
            self._json(exc.status, {"error": str(exc)})
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            self._json(400, {"error": "invalid request"})
        except Exception:
            self._json(500, {"error": "NKN helper internal error"})

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._handle()

    def do_DELETE(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._handle()

    def log_message(self, format: str, *args: Any) -> None:
        return


if hasattr(socketserver, "UnixStreamServer"):

    class _UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        allow_reuse_address = True
        daemon_threads = True

else:
    _UnixServer = None


def _socket_group() -> int:
    try:
        return os.stat("/var/run/docker.sock").st_gid
    except OSError:
        return 0


def serve(path: Path) -> None:
    if _UnixServer is None:
        raise RuntimeError("Unix domain sockets are required")
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
    server = _UnixServer(str(path), _Handler)
    os.chmod(path, 0o660)
    os.chown(path, 0, _socket_group())
    try:
        _Handler.controller.reconcile_all()
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="Restricted CashPilot NKN LXD host helper")
    parser.add_argument("--socket", type=Path, default=SOCKET_PATH)
    args = parser.parse_args()
    serve(args.socket)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
