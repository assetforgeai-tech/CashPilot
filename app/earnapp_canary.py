"""Owner-controlled, account-scoped EarnApp Mac canary lane."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import re
import secrets
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from app import database, earnapp_identity, earnapp_policy, earnapp_recovery, earnapp_runtime
from app.collectors.earnapp import EarnAppAccountCollector

WorkerDeploy = Callable[[int, str, dict[str, Any]], Awaitable[dict[str, Any]]]
WorkerRemove = Callable[[int, str, int, str], Awaitable[Any]]
PlatformWorkerRemove = WorkerRemove

LINK_VERIFY_ATTEMPTS = 10
LINK_VERIFY_INTERVAL_SECONDS = 15
LINK_VERIFY_MIN_INTERVAL_SECONDS = 5
LINK_VERIFY_BURST = 5
LINK_VERIFY_COOLDOWN_SECONDS = 300
MAC_PROXY_TUN_IP = "10.255.255.1"
_UPTIME_BILLING = frozenset({"uptime", "fixed", "qualified_uptime"})
_BYTE_BILLING = frozenset({"bandwidth", "bytes", "byte", "traffic", "gb"})
_ACCOUNT_VERIFY_LOCKS: dict[int, asyncio.Lock] = {}


def account_api_lock(account_id: int) -> asyncio.Lock:
    """Share one account-scoped lock between verification and collection calls."""
    return _ACCOUNT_VERIFY_LOCKS.setdefault(int(account_id), asyncio.Lock())


def _workload_metric_names(evidence: Mapping[str, Any], billing: str) -> tuple[str, ...]:
    """Select monotonic/runtime counters and prefer the current-day series.

    ``usage_total`` is a historical aggregate.  It remains a compatibility
    fallback for older collector payloads, but must not be used when the API
    provides ``usage_current`` because historical rollups can change without
    the node doing work in the current verification window.
    """
    if billing in _UPTIME_BILLING:
        names: list[str] = ["uptime", "total_uptime"]
    else:
        names = ["bandwidth", "total_bandwidth"]
    if evidence.get("usage_current") is not None:
        names.append("usage_current")
    elif evidence.get("usage_total") is not None:
        names.append("usage_total")
    names.append("earned_total")
    return tuple(names)


def _safe_node_id(value: str) -> str:
    node_id = str(value or "").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,120}", node_id):
        raise ValueError("invalid EarnApp logical node id")
    return node_id


def _mutable_node_id(value: str) -> str:
    node_id = _safe_node_id(value)
    if earnapp_policy.is_protected_logical_node(node_id):
        raise ValueError("protected EarnApp node is inspection-only")
    return node_id


def _valid_ubuntu_device_id(value: Any) -> str:
    """Return a runtime UUID only when it is safe to use for CAS cleanup."""
    device_id = str(value or "").strip()
    return device_id if re.fullmatch(r"sdk-node-[0-9a-f]{32}", device_id) else ""


def _identity_value(node_id: str) -> dict[str, Any]:
    digest = hashlib.sha256(node_id.encode("utf-8")).hexdigest()
    suffix = digest[:12]
    serial = digest[:16].upper()
    platform_uuid = f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}".upper()
    return {
        "id": secrets.token_hex(16),
        "platform": earnapp_runtime.MAC_PLATFORM,
        "appid": earnapp_runtime.MAC_APPID,
        "version": "1.660.577",
        "sdk_version": "1.660.577",
        "arch": "x64",
        "release": "Version 11.0.1 (Build 20B50)",
        "ifname": "en0",
        "iface_type": "eth",
        "hostname": f"MacBook-Pro-{suffix}",
        "local_hostname": f"MacBook-Pro-{suffix}",
        "conf_user": "cashpilot",
        "os_product": "macOS",
        "os_version": "11.0.1",
        "os_build": "20B50",
        "codename": "Big Sur",
        "device_model": "MacBookPro17,1",
        "uname_s": "Darwin",
        "uname_m": "x86_64",
        "uname_r": "20.1.0",
        "serial_material_mac": serial,
        "serial": serial,
        "platform_serial": serial,
        "platform_uuid": platform_uuid,
        "confdir": "file:///Users/cashpilot/Library/Application%20Support/com.earnapp/",
        "gw_ip": "0.0.0.0",
        "ipv6_supported": False,
        "http3": True,
        "is_swift": True,
        "status_send": True,
        "idle": False,
        "lan_ip": MAC_PROXY_TUN_IP,
        "skip_local_addr": True,
        "mobile_connected": False,
        "roaming": False,
        "is_debug": False,
        "makeflags": "DIST=APP RELEASE=y AUTO_SIGN=y IS_MACOS=y MACOS_SDK=y CONFIG_BATREQ=y CONFIG_BAT_CYCLE=y",
        "bat_platform": "app_macr_mac_sdk",
        "new_state": {"full_screen": "off", "power_source": "AC", "monitor_power": "on"},
        "usage": {"total_bytes": 0, "app_bytes": 0},
        "perf": {"cpu": 0.0, "cpu_max": 100.0, "mem": 8192, "mem_free": 4096, "mem_max": 8192},
        "perr_os_version": "OS version: macOS 11.0.1",
        "ua": "brdsdk/1.660.577 CFNetwork/1209.0.0 Darwin/20.1.0",
        "timezone": "Asia/Ho_Chi_Minh",
        "consent_ts": 0,
    }


async def get_or_create_mac_identity_profile(logical_node_id: str) -> dict[str, str]:
    node_id = _safe_node_id(logical_node_id)
    profile = await earnapp_identity.ensure_identity_profile(node_id, "macos")
    identity = earnapp_identity.decrypt_profile(profile["value"], "macos")
    if identity.get("lan_ip") != MAC_PROXY_TUN_IP:
        raise ValueError("EarnApp persisted Mac identity lan_ip is incompatible with the proxy tunnel")
    return {
        "asset_id": profile["asset_id"],
        "device_id": profile["device_id"],
        "value": profile["value"],
    }


def _proxy_metadata(proxy: Mapping[str, Any]) -> dict[str, Any]:
    host = str(proxy.get("host") or "").strip()
    port = int(proxy.get("port") or 0)
    protocol = str(proxy.get("protocol") or "").strip().lower()
    if host and (not 1 <= port <= 65535 or protocol not in {"http", "socks5"}):
        raise ValueError("EarnApp canary proxy is invalid")
    result: dict[str, Any] = {
        "proxy_id": int(proxy.get("proxy_id") or 0),
        "host": host,
        "port": port,
        "protocol": protocol,
        "exit_ip": str(proxy.get("exit_ip") or ""),
        "country_code": str(proxy.get("country_code") or "").upper(),
        "ip_type": str(proxy.get("ip_type") or "").lower(),
    }
    for key in ("username", "password"):
        if proxy.get(key):
            result[key] = str(proxy[key])
    return result


def _redacted_proxy(proxy: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in _proxy_metadata(proxy).items() if key not in {"username", "password"}}


def _in_container_proxy_env(proxy: Mapping[str, Any]) -> dict[str, str]:
    protocol = str(proxy.get("protocol") or "socks5").strip().upper()
    if protocol not in {"HTTP", "SOCKS5"}:
        raise ValueError("EarnApp proxy protocol is invalid")
    return {
        "PROXY_TYPE": protocol,
        "PROXY_CREDENTIALS": ":".join(
            (
                str(proxy.get("host") or "").strip(),
                str(proxy.get("port") or "").strip(),
                str(proxy.get("username") or ""),
                str(proxy.get("password") or ""),
            )
        ),
    }


def build_canary_spec(
    logical_node_id: str,
    account_id: int,
    device_id: str,
    proxy: Mapping[str, Any],
    identity_asset_kind: str = earnapp_runtime.MAC_IDENTITY_ASSET_KIND,
    *,
    generation: int = 1,
    identity_asset_id: str | None = None,
) -> dict[str, Any]:
    node_id = _safe_node_id(logical_node_id)
    device = earnapp_runtime.validate_device_id(device_id)
    earnapp_runtime.validate_identity_asset_kind(identity_asset_kind)
    proxy_meta = _redacted_proxy(proxy)
    return {
        "image": earnapp_runtime.MAC_RUNTIME_IMAGE,
        "image_contract_sha256": earnapp_runtime.MAC_RUNTIME_ASSET_MANIFEST_SHA256,
        "image_delivery": "operator_preload",
        "provider_slug": "earnapp",
        "host_runtime": earnapp_runtime.MAC_RUNTIME_HOST,
        "env": {
            "EARNAPP_ENC": "/etc/earnapp-spoof/profile.json.enc",
            "EARNAPP_PLATFORM": earnapp_runtime.MAC_PLATFORM,
            "EARNAPP_APPID": earnapp_runtime.MAC_APPID,
            "EARNAPP_DEVICE_ID": device,
            "EARNAPP_LOGICAL_NODE_ID": node_id,
            "EARNAPP_EXPECTED_EGRESS_IP": str(proxy_meta.get("exit_ip") or ""),
            **_in_container_proxy_env(proxy),
        },
        "volumes": {f"{node_id}-data": {"bind": "/etc/earnapp", "mode": "rw"}},
        "labels": {
            "cashpilot.provider": "earnapp",
            "cashpilot.instance_mode": "proxy",
            "cashpilot.earnapp.logical_node_id": node_id,
            "cashpilot.earnapp.account_id": str(int(account_id)),
            "cashpilot.earnapp.device_id": device,
            "cashpilot.earnapp.platform": earnapp_runtime.MAC_PLATFORM,
            "cashpilot.earnapp.runtime_contract": earnapp_runtime.MAC_APPID,
            "cashpilot.earnapp.generation": str(max(1, int(generation))),
        },
        "privileged": False,
        "cap_add": ["NET_ADMIN"],
        "devices": None,
        "network_mode": "bridge",
        "egress_mode": "proxy",
        "egress_udp": "none",
        "proxy": proxy_meta,
        "resources": {"mem_limit": "1g", "oom_score_adj": 200},
        "runtime_assets": [
            {
                "provider": "earnapp",
                "asset_kind": identity_asset_kind,
                "asset_id": identity_asset_id or node_id,
                "target": "/etc/earnapp-spoof/profile.json.enc",
                "encoding": "base64",
            }
        ],
        "runtime_contract": {
            "platform": earnapp_runtime.MAC_PLATFORM,
            "appid": earnapp_runtime.MAC_APPID,
            "device_id_prefix": earnapp_runtime.MAC_DEVICE_PREFIX,
        },
        "account_id": int(account_id),
        "runtime_backend": "docker",
    }


def build_runtime_spec(
    logical_node_id: str,
    account_id: int,
    platform: str,
    device_id: str,
    proxy: Mapping[str, Any],
    *,
    generation: int = 1,
    identity_asset_id: str | None = None,
) -> dict[str, Any]:
    """Build a Docker runtime spec for one persisted MacOS or iOS node."""
    selected = str(platform or "").strip().lower()
    if selected == "macos":
        return build_canary_spec(
            logical_node_id,
            account_id,
            device_id,
            proxy,
            generation=generation,
            identity_asset_id=identity_asset_id,
        )
    if selected == "ubuntu":
        node_id = _safe_node_id(logical_node_id)
        device = str(device_id or "").strip()
        if device and not re.fullmatch(r"sdk-node-[0-9a-f]{32}", device):
            raise ValueError("EarnApp Ubuntu device_id must use the sdk-node- prefix")
        proxy_meta = _redacted_proxy(proxy)
        expected_egress_ip = str(proxy_meta.get("exit_ip") or "").strip()
        if not expected_egress_ip:
            raise ValueError("EarnApp Ubuntu runtime requires an authoritative proxy egress IP")
        protocol = str(proxy.get("protocol") or "socks5").strip().upper()
        if protocol not in {"HTTP", "SOCKS5"}:
            raise ValueError("EarnApp Ubuntu proxy protocol is invalid")
        proxy_credentials = ":".join(
            (
                str(proxy.get("host") or "").strip(),
                str(proxy.get("port") or "").strip(),
                str(proxy.get("username") or ""),
                str(proxy.get("password") or ""),
            )
        )
        return {
            "image": earnapp_runtime.UBUNTU_RUNTIME_IMAGE,
            "image_delivery": "operator_preload",
            "provider_slug": "earnapp",
            "host_runtime": earnapp_runtime.UBUNTU_RUNTIME_HOST,
            "env": {
                "EARNAPP_PLATFORM": earnapp_runtime.UBUNTU_PLATFORM,
                "EARNAPP_APPID": earnapp_runtime.UBUNTU_APPID,
                "EARNAPP_LOGICAL_NODE_ID": node_id,
                "EARNAPP_EXPECTED_EGRESS_IP": expected_egress_ip,
                "NODE_TLS_REJECT_UNAUTHORIZED": "0",
                # Ubuntu's verified runtime owns its redsocks/iptables route;
                # do not put this node behind CashPilot's generic sidecar.
                "PROXY_TYPE": protocol,
                "PROXY_CREDENTIALS": proxy_credentials,
            },
            "volumes": {f"{node_id}-data": {"bind": "/etc/earnapp", "mode": "rw"}},
            "labels": {
                "cashpilot.provider": "earnapp",
                "cashpilot.instance_mode": "proxy",
                "cashpilot.earnapp.logical_node_id": node_id,
                "cashpilot.earnapp.account_id": str(int(account_id)),
                "cashpilot.earnapp.platform": earnapp_runtime.UBUNTU_PLATFORM,
                "cashpilot.earnapp.runtime_contract": earnapp_runtime.UBUNTU_APPID,
                "cashpilot.earnapp.generation": str(max(1, int(generation))),
            },
            "privileged": False,
            "cap_add": ["NET_ADMIN"],
            "devices": None,
            "network_mode": "bridge",
            "egress_mode": "proxy",
            "egress_udp": "none",
            "proxy": proxy_meta,
            "resources": {"mem_limit": "1g", "oom_score_adj": 200},
            "runtime_assets": [],
            "runtime_contract": {
                "platform": earnapp_runtime.UBUNTU_PLATFORM,
                "appid": earnapp_runtime.UBUNTU_APPID,
                "device_id_prefix": earnapp_runtime.UBUNTU_DEVICE_PREFIX,
            },
            "account_id": int(account_id),
            "runtime_backend": "docker",
            "expected_device_id": device,
            "require_fresh_volume": not bool(device),
        }
    if selected != "ios":
        raise ValueError("Docker EarnApp runtime supports only MacOS, iOS, or Ubuntu")
    node_id = _safe_node_id(logical_node_id)
    device = str(device_id or "").strip()
    if not re.fullmatch(r"sdk-ios-[A-Za-z0-9-]{4,96}", device):
        raise ValueError("EarnApp iOS device_id must use the sdk-ios- prefix")
    proxy_meta = _redacted_proxy(proxy)
    expected_egress_ip = str(proxy_meta.get("exit_ip") or "").strip()
    if not expected_egress_ip:
        raise ValueError("EarnApp iOS runtime requires an authoritative proxy egress IP")
    return {
        "image": earnapp_runtime.IOS_RUNTIME_IMAGE,
        "image_contract_sha256": earnapp_runtime.IOS_RUNTIME_ASSET_MANIFEST_SHA256,
        "image_delivery": "operator_preload",
        "provider_slug": "earnapp",
        "host_runtime": earnapp_runtime.IOS_RUNTIME_HOST,
        "env": {
            "EARNAPP_ENC": "/etc/earnapp-spoof/profile.json.enc",
            "EARNAPP_PLATFORM": earnapp_runtime.IOS_PLATFORM,
            "EARNAPP_APPID": earnapp_runtime.IOS_APPID,
            "EARNAPP_DEVICE_ID": device,
            "EARNAPP_LOGICAL_NODE_ID": node_id,
            "EARNAPP_EXPECTED_EGRESS_IP": expected_egress_ip,
            **_in_container_proxy_env(proxy),
        },
        "volumes": {f"{node_id}-data": {"bind": "/etc/earnapp", "mode": "rw"}},
        "labels": {
            "cashpilot.provider": "earnapp",
            "cashpilot.instance_mode": "proxy",
            "cashpilot.earnapp.logical_node_id": node_id,
            "cashpilot.earnapp.account_id": str(int(account_id)),
            "cashpilot.earnapp.device_id": device,
            "cashpilot.earnapp.platform": earnapp_runtime.IOS_PLATFORM,
            "cashpilot.earnapp.runtime_contract": earnapp_runtime.IOS_APPID,
            "cashpilot.earnapp.generation": str(max(1, int(generation))),
        },
        "privileged": False,
        "cap_add": ["NET_ADMIN"],
        "devices": None,
        "network_mode": "bridge",
        "egress_mode": "proxy",
        "egress_udp": "none",
        "proxy": proxy_meta,
        "resources": {"mem_limit": "1g", "oom_score_adj": 200},
        "runtime_assets": [
            {
                "provider": "earnapp",
                "asset_kind": earnapp_identity.IOS_PROFILE_ASSET_KIND,
                "asset_id": identity_asset_id or node_id,
                "target": "/etc/earnapp-spoof/profile.json.enc",
                "encoding": "base64",
            }
        ],
        "runtime_contract": {
            "platform": earnapp_runtime.IOS_PLATFORM,
            "appid": earnapp_runtime.IOS_APPID,
            "device_id_prefix": earnapp_runtime.IOS_DEVICE_PREFIX,
        },
        "account_id": int(account_id),
        "runtime_backend": "docker",
    }


async def provision_canary(logical_node_id: str, worker_id: int, device_id: str) -> dict[str, Any]:
    node_id = _mutable_node_id(logical_node_id)
    device = earnapp_runtime.validate_device_id(device_id)
    before = await database.get_earnapp_logical_node(node_id)
    node = await earnapp_recovery.provision_node(
        node_id,
        int(worker_id),
        device_id=device,
        proxy_country_code="VN",
        platform="macos",
    )
    return {**node, "created_binding": not bool((before or {}).get("current_proxy_id"))}


async def deploy_canary(
    logical_node_id: str,
    worker_id: int,
    *,
    worker_deploy: WorkerDeploy,
    worker_remove: WorkerRemove,
) -> dict[str, Any]:
    node_id = _mutable_node_id(logical_node_id)
    profile = await get_or_create_mac_identity_profile(node_id)

    # A retry must not recreate a running identity container. The provider
    # instance record is the server-side idempotency marker for this lane.
    existing = await database.get_provider_instance(node_id)
    if existing and str(existing.get("status") or "").lower() in {"running", "deployed"}:
        existing_worker = int(existing.get("worker_id") or 0)
        if existing_worker and existing_worker != int(worker_id):
            raise ValueError("EarnApp canary is already assigned to another worker")
        return {
            "status": "already_deployed",
            "logical_node_id": node_id,
            "worker_id": existing_worker or int(worker_id),
            "container_id": str(existing.get("container_id") or "remote"),
        }

    provisioned = await provision_canary(node_id, int(worker_id), profile["device_id"])
    try:
        proxy = await database.lease_proxy_for_provider_instance("earnapp", int(worker_id), node_id, country_code="VN")
        if not proxy:
            raise ValueError("no eligible VN residential EarnApp proxy available")
        if (
            str(proxy.get("country_code") or "").upper() != "VN"
            or str(proxy.get("ip_type") or "").lower() != "residential"
        ):
            raise ValueError("EarnApp Mac canary requires a VN residential proxy")
        transport_spec = build_canary_spec(
            node_id,
            int(provisioned["account_id"]),
            profile["device_id"],
            proxy,
            generation=int(provisioned["generation"]),
            identity_asset_id=profile["asset_id"],
        )
        transport_spec["proxy"] = _proxy_metadata(proxy)
        persisted_spec = json.loads(json.dumps(transport_spec))
        persisted_spec = earnapp_runtime.redacted_evidence(persisted_spec)
        persisted_spec["proxy"] = _redacted_proxy(proxy)
    except Exception:
        if provisioned.get("created_binding"):
            with contextlib.suppress(Exception):
                await database.rollback_earnapp_canary_binding(
                    node_id,
                    int(worker_id),
                    generation=int(provisioned["generation"]),
                    proxy_id=int(provisioned["proxy_id"]),
                    reason="EARNAPP_CANARY_PREPARE_FAILED",
                )
        raise

    try:
        result = await worker_deploy(int(worker_id), node_id, transport_spec)
    except Exception:
        if provisioned.get("created_binding"):
            with contextlib.suppress(Exception):
                await worker_remove(
                    int(worker_id),
                    node_id,
                    int(provisioned["generation"]),
                    str(profile["device_id"]),
                )
            await database.rollback_earnapp_canary_binding(
                node_id,
                int(worker_id),
                generation=int(provisioned["generation"]),
                proxy_id=int(provisioned["proxy_id"]),
                reason="EARNAPP_CANARY_DEPLOY_FAILED",
            )
        raise
    container_id = str(result.get("container_id") or "remote")
    try:
        await database.save_provider_instance(
            "earnapp",
            node_id,
            worker_id=int(worker_id),
            mode="proxy",
            container_id=container_id,
            proxy_id=int(provisioned["proxy_id"]),
            status="running",
            spec=persisted_spec,
        )
    except Exception:
        with contextlib.suppress(Exception):
            await worker_remove(
                int(worker_id),
                node_id,
                int(provisioned["generation"]),
                str(profile["device_id"]),
            )
        if provisioned.get("created_binding"):
            with contextlib.suppress(Exception):
                await database.rollback_earnapp_canary_binding(
                    node_id,
                    int(worker_id),
                    generation=int(provisioned["generation"]),
                    proxy_id=int(provisioned["proxy_id"]),
                    reason="EARNAPP_CANARY_PERSIST_FAILED",
                )
        raise
    return {
        "status": "deployed",
        "logical_node_id": node_id,
        "account_id": int(provisioned["account_id"]),
        "worker_id": int(worker_id),
        "device_id": profile["device_id"],
        "proxy_id": int(provisioned["proxy_id"]),
        "generation": int(provisioned["generation"]),
        "container_id": container_id,
    }


async def deploy_platform_canary(
    logical_node_id: str,
    worker_id: int,
    *,
    platform: str,
    worker_deploy: WorkerDeploy,
    worker_remove: PlatformWorkerRemove,
    lxd_settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Deploy one fresh iOS-Docker or Ubuntu-Docker canary without touching Mac nodes."""
    from app import earnapp_deploy

    node_id = _mutable_node_id(logical_node_id)
    selected = str(platform or "").strip().lower()
    if selected not in {"ios", "ubuntu"}:
        raise ValueError("platform canary supports only iOS or Ubuntu")

    before = await database.get_earnapp_logical_node(node_id)
    before_platform = str((before or {}).get("platform") or "unknown").strip().lower()
    if before_platform not in {"", "unknown", selected}:
        raise ValueError("EarnApp canary platform is immutable")

    existing = await database.get_provider_instance(node_id)
    if existing and str(existing.get("status") or "").lower() in {
        "running",
        "deployed",
        "verification_pending",
    }:
        existing_worker = int(existing.get("worker_id") or 0)
        if existing_worker and existing_worker != int(worker_id):
            raise ValueError("EarnApp canary is already assigned to another worker")
        return {
            "status": "already_deployed",
            "logical_node_id": node_id,
            "worker_id": existing_worker or int(worker_id),
            "container_id": str(existing.get("container_id") or "remote"),
        }

    await database.assign_earnapp_account(node_id, platform=selected)
    plan = earnapp_deploy.EarnAppNodePlan(int(worker_id), "ipv4-001", node_id)
    try:
        prepared = await earnapp_deploy.prepare_node(
            plan,
            vn_platform_choice=(lambda: "ios"),
        )
    except Exception:
        if not (before or {}).get("current_proxy_id"):
            with contextlib.suppress(Exception):
                await database.release_proxy_for_provider_instance(
                    "earnapp",
                    int(worker_id),
                    node_id,
                    reason="EARNAPP_CANARY_PREPARE_FAILED",
                )
        raise
    created_binding = not bool((before or {}).get("current_proxy_id"))
    if prepared.platform != selected:
        if created_binding:
            with contextlib.suppress(Exception):
                await database.rollback_earnapp_canary_binding(
                    node_id,
                    int(worker_id),
                    generation=prepared.generation,
                    proxy_id=int(prepared.proxy["proxy_id"]),
                    reason="EARNAPP_CANARY_PLATFORM_MISMATCH",
                )
        raise ValueError("EarnApp canary platform selection changed during provisioning")

    if selected in {"ios", "ubuntu"}:
        transport_spec = build_runtime_spec(
            node_id,
            prepared.account_id,
            selected,
            prepared.device_id,
            prepared.proxy,
            generation=prepared.generation,
            identity_asset_id=prepared.identity_asset_id,
        )
        transport_spec["proxy"] = _proxy_metadata(prepared.proxy)
    # Keep lifecycle metadata in the encrypted deployment record. Redaction is
    # for credentials/evidence, but `runtime_backend` is required to dispatch
    # later stop/remove operations to Docker instead of legacy LXD.
    persisted_spec = json.loads(json.dumps(transport_spec))
    persisted_spec = earnapp_runtime.redacted_evidence(persisted_spec)
    persisted_spec["runtime_backend"] = "docker"
    try:
        result = await worker_deploy(int(worker_id), node_id, transport_spec)
    except Exception:
        if created_binding:
            if prepared.device_id:
                with contextlib.suppress(Exception):
                    await worker_remove(int(worker_id), node_id, prepared.generation, prepared.device_id)
            with contextlib.suppress(Exception):
                await database.rollback_earnapp_canary_binding(
                    node_id,
                    int(worker_id),
                    generation=prepared.generation,
                    proxy_id=int(prepared.proxy["proxy_id"]),
                    reason="EARNAPP_CANARY_DEPLOY_FAILED",
                )
        raise

    container_id = str(result.get("container_id") or result.get("instance_id") or "remote")
    runtime_device_id = prepared.device_id
    if selected == "ubuntu":
        runtime_device_id = str(result.get("device_id") or "").strip()
        try:
            bound = await database.bind_earnapp_generated_device_id(
                node_id,
                int(worker_id),
                generation=prepared.generation,
                proxy_id=int(prepared.proxy["proxy_id"]),
                device_id=runtime_device_id,
            )
        except Exception:
            # A bind failure must not leave a fresh runtime orphaned. The
            # worker-side delete is CAS-scoped, so only pass a valid UUID.
            valid_runtime_id = _valid_ubuntu_device_id(runtime_device_id)
            if valid_runtime_id:
                with contextlib.suppress(Exception):
                    await worker_remove(int(worker_id), node_id, prepared.generation, valid_runtime_id)
            if created_binding:
                with contextlib.suppress(Exception):
                    await database.rollback_earnapp_canary_binding(
                        node_id,
                        int(worker_id),
                        generation=prepared.generation,
                        proxy_id=int(prepared.proxy["proxy_id"]),
                        reason="EARNAPP_CANARY_BIND_FAILED",
                    )
            raise
        if not bound:
            valid_runtime_id = _valid_ubuntu_device_id(runtime_device_id)
            if valid_runtime_id:
                with contextlib.suppress(Exception):
                    await worker_remove(int(worker_id), node_id, prepared.generation, valid_runtime_id)
            if created_binding:
                with contextlib.suppress(Exception):
                    await database.rollback_earnapp_canary_binding(
                        node_id,
                        int(worker_id),
                        generation=prepared.generation,
                        proxy_id=int(prepared.proxy["proxy_id"]),
                        reason="EARNAPP_CANARY_BIND_FAILED",
                    )
            raise RuntimeError("EarnApp Ubuntu generated identity assignment conflict")
        persisted_spec["device_id"] = runtime_device_id
    try:
        await database.save_provider_instance(
            "earnapp",
            node_id,
            worker_id=int(worker_id),
            mode="proxy",
            container_id=container_id,
            proxy_id=int(prepared.proxy["proxy_id"]),
            status="running",
            spec=persisted_spec,
        )
    except Exception:
        cleanup_device_id = (
            _valid_ubuntu_device_id(runtime_device_id) if selected == "ubuntu" else str(runtime_device_id or "")
        )
        if cleanup_device_id:
            with contextlib.suppress(Exception):
                await worker_remove(int(worker_id), node_id, prepared.generation, cleanup_device_id)
        # Once the reference Ubuntu UUID is CAS-bound, retaining that exact
        # assignment is the only safe way to reuse the preserved identity volume.
        if created_binding and selected != "ubuntu":
            with contextlib.suppress(Exception):
                await database.rollback_earnapp_canary_binding(
                    node_id,
                    int(worker_id),
                    generation=prepared.generation,
                    proxy_id=int(prepared.proxy["proxy_id"]),
                    reason="EARNAPP_CANARY_PERSIST_FAILED",
                )
        raise

    return {
        "status": "deployed",
        "logical_node_id": node_id,
        "platform": selected,
        "account_id": prepared.account_id,
        "worker_id": int(worker_id),
        "device_id": runtime_device_id,
        "proxy_id": int(prepared.proxy["proxy_id"]),
        "generation": prepared.generation,
        "container_id": container_id,
    }


async def verify_canary(
    logical_node_id: str,
    *,
    attempts: int = LINK_VERIFY_ATTEMPTS,
    interval_seconds: float = LINK_VERIFY_INTERVAL_SECONDS,
) -> dict[str, Any]:
    """Link and verify one provisioned canary through its exact account route."""
    node_id = _mutable_node_id(logical_node_id)
    node = await database.get_earnapp_logical_node(node_id)
    if not node or str(node.get("state") or "") != "ACTIVE":
        raise ValueError("EarnApp canary is not active")
    account = await database.get_earnapp_account_credentials(int(node.get("account_id") or 0))
    if not account or str(account.get("state") or "") != "ACTIVE":
        raise ValueError("EarnApp canary account is not active")
    account_id = int(node["account_id"])
    lock = account_api_lock(account_id)
    async with lock:
        return await _verify_canary_locked(
            node_id,
            node,
            account,
            attempts=attempts,
            interval_seconds=interval_seconds,
        )


async def _verify_canary_locked(
    node_id: str,
    node: Mapping[str, Any],
    account: Mapping[str, Any],
    *,
    attempts: int,
    interval_seconds: float,
) -> dict[str, Any]:
    routes = await database.get_earnapp_account_node_routes(int(node["account_id"]), healthy_only=False)
    route = next(
        (
            item
            for item in routes
            if str(item.get("logical_node_id") or "") == node_id
            and int(item.get("proxy_id") or 0) == int(node.get("current_proxy_id") or 0)
        ),
        None,
    )
    if not route:
        raise ValueError("EarnApp canary proxy route is unavailable")
    collector = EarnAppAccountCollector(account.get("credentials") or {}, route)
    platform = str(node.get("platform") or "macos").strip().lower()
    if platform not in earnapp_identity.SUPPORTED_PLATFORMS:
        raise ValueError("EarnApp canary platform is invalid")
    remaining = max(1, int(attempts))
    last: dict[str, Any] = {}
    baseline: dict[str, float] | None = None
    baseline_billing = ""
    expected_device_id = str(node.get("device_id") or "").strip()
    with contextlib.suppress(Exception):
        persisted_spec = await database.get_provider_instance_spec(node_id)
        persisted = persisted_spec.get("earnapp_device_verification") if isinstance(persisted_spec, Mapping) else None
        persisted_billing = str((persisted or {}).get("billing") or "").strip().lower()
        if (
            isinstance(persisted, Mapping)
            and str(persisted.get("device_id") or "") == str(node.get("device_id") or "")
            and persisted_billing in _UPTIME_BILLING | _BYTE_BILLING
        ):
            metric_names = _workload_metric_names(persisted, persisted_billing)
            baseline = {key: max(0.0, float(persisted[key])) for key in metric_names if persisted.get(key) is not None}
            baseline_billing = persisted_billing
    for attempt in range(1, remaining + 1):
        last = await collector.link_and_verify_device(expected_device_id, platform=platform)
        observed_device_id = str(last.get("device_id") or "").strip()
        if observed_device_id and observed_device_id != expected_device_id:
            # A dashboard row from an older canary must never satisfy this node.
            last = {
                "status": "error",
                "error_kind": "identity",
                "error": "EarnApp evidence belongs to a different device",
                "device_id": expected_device_id,
                "observed_device_id": observed_device_id,
                "authenticated": last.get("authenticated") is True,
                "link_attempted": last.get("link_attempted") is True,
                "device_present": False,
                "online": False,
                "banned": False,
            }
        if last.get("online") is True and last.get("device_present") is True and last.get("banned") is not True:
            billing = str(last.get("billing") or "").strip().lower()
            if billing in _UPTIME_BILLING or billing in _BYTE_BILLING:
                metric_names = _workload_metric_names(last, billing)
            else:
                baseline = None
                baseline_billing = ""
                last = {
                    **last,
                    "status": "online_pending_usage",
                    "workload_state": "online_pending_usage",
                    "workload_reason": "billing_unknown",
                }
                if attempt >= remaining:
                    break
                # Unknown billing is still a retryable state; enforce the same
                # relay floor as link/status retries so callers cannot hammer
                # EarnApp by passing interval_seconds=0.
                delay = max(LINK_VERIFY_MIN_INTERVAL_SECONDS, float(interval_seconds))
                if attempt % LINK_VERIFY_BURST == 0 and attempt < remaining:
                    delay = max(delay, LINK_VERIFY_COOLDOWN_SECONDS)
                await asyncio.sleep(delay)
                continue

            current = {key: max(0.0, float(last[key])) for key in metric_names if last.get(key) is not None}
            if baseline is not None and baseline_billing == billing:
                delta = {key: max(0.0, current[key] - baseline[key]) for key in current if key in baseline}
                earned_growth = max(0.0, delta.get("earned_total", 0.0))
                if billing in _UPTIME_BILLING:
                    workload_verified = (
                        any(
                            delta.get(metric, 0.0) > 0
                            for metric in ("uptime", "total_uptime", "usage_current", "usage_total")
                        )
                        or earned_growth > 0
                    )
                else:
                    workload_verified = any(value > 0 for value in delta.values())
                if workload_verified:
                    return earnapp_runtime.redacted_evidence(
                        {
                            **last,
                            "status": "workload_verified",
                            "workload_state": "workload_verified",
                            "workload_delta": delta,
                        }
                    )
            baseline = current
            baseline_billing = billing
            last = {
                **last,
                "status": "online_pending_usage",
                "workload_state": "online_pending_usage",
                "workload_reason": "awaiting_metric_delta",
            }
        terminal_error = last.get("error_kind") in {"auth", "shape", "identity", "proxy_blocked"}
        if terminal_error or last.get("banned") is True or attempt >= remaining:
            break
        delay = max(LINK_VERIFY_MIN_INTERVAL_SECONDS, float(interval_seconds))
        if attempt % LINK_VERIFY_BURST == 0 and attempt < remaining:
            delay = max(delay, LINK_VERIFY_COOLDOWN_SECONDS)
        await asyncio.sleep(delay)
    return earnapp_runtime.redacted_evidence(last)
