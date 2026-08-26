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

from app import database, earnapp_recovery, earnapp_runtime
from app.collectors.earnapp import EarnAppAccountCollector

WorkerDeploy = Callable[[int, str, dict[str, Any]], Awaitable[dict[str, Any]]]
WorkerRemove = Callable[[int, str], Awaitable[Any]]

LINK_VERIFY_ATTEMPTS = 10
LINK_VERIFY_INTERVAL_SECONDS = 15
MAC_PROXY_TUN_IP = "172.31.255.1"


def _safe_node_id(value: str) -> str:
    node_id = str(value or "").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,120}", node_id):
        raise ValueError("invalid EarnApp logical node id")
    return node_id


def _identity_value(node_id: str) -> dict[str, Any]:
    digest = hashlib.sha256(node_id.encode("utf-8")).hexdigest()
    suffix = digest[:12]
    serial = digest[:16].upper()
    platform_uuid = f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}".upper()
    return {
        "id": secrets.token_hex(16),
        "platform": earnapp_runtime.MAC_PLATFORM,
        "appid": earnapp_runtime.MAC_APPID,
        "version": "1.605.415",
        "sdk_version": "1.605.415",
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
        "makeflags": "DIST=APP RELEASE=y AUTO_SIGN=y IS_MACOS=y MACOS_SDK=y IS_MAC_BVPN=y",
        "bat_platform": "app_macr_mac",
        "new_state": {"full_screen": "off", "power_source": "AC", "monitor_power": "on"},
        "usage": {"total_bytes": 0, "app_bytes": 0},
        "perf": {"cpu": 0.0, "cpu_max": 100.0, "mem": 8192, "mem_free": 4096, "mem_max": 8192},
        "perr_os_version": "OS version: macOS 11.0.1",
        "ua": "brdsdk/1.605.415 CFNetwork/1209.0.0 Darwin/20.1.0",
        "timezone": "Asia/Ho_Chi_Minh",
        "consent_ts": 0,
    }


async def get_or_create_mac_identity_profile(logical_node_id: str) -> dict[str, str]:
    node_id = _safe_node_id(logical_node_id)
    existing = await database.get_earnapp_mac_profile(node_id)
    if existing:
        identity = earnapp_runtime.decrypt_mac_profile(existing["value"])
        device_id = (
            earnapp_runtime.MAC_DEVICE_PREFIX
            + hashlib.sha256((str(identity["id"]) + str(identity["serial"])).encode("utf-8")).hexdigest()[:32]
        )
        if device_id != existing["device_id"]:
            raise ValueError("EarnApp Mac profile device identity changed")
        value = existing["value"]
        if identity.get("lan_ip") != MAC_PROXY_TUN_IP:
            identity["lan_ip"] = MAC_PROXY_TUN_IP
            value = earnapp_runtime.encrypt_mac_profile(identity)
            await database.save_earnapp_mac_profile(node_id, device_id=device_id, value=value)
        return {"asset_id": node_id, "device_id": device_id, "value": value}

    identity = _identity_value(node_id)
    device_id = (
        earnapp_runtime.MAC_DEVICE_PREFIX
        + hashlib.sha256((str(identity["id"]) + str(identity["serial"])).encode("utf-8")).hexdigest()[:32]
    )
    value = earnapp_runtime.encrypt_mac_profile(identity)
    await database.save_earnapp_mac_profile(node_id, device_id=device_id, value=value)
    return {"asset_id": node_id, "device_id": device_id, "value": value}


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
        "provider_slug": "earnapp",
        "host_runtime": earnapp_runtime.MAC_RUNTIME_HOST,
        "env": {
            "EARNAPP_ENC": "/etc/earnapp-spoof/profile.json.enc",
            "EARNAPP_PLATFORM": earnapp_runtime.MAC_PLATFORM,
            "EARNAPP_APPID": earnapp_runtime.MAC_APPID,
            "EARNAPP_DEVICE_ID": device,
            "EARNAPP_LOGICAL_NODE_ID": node_id,
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
        "cap_add": None,
        "devices": None,
        "network_mode": None,
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
    }


async def provision_canary(logical_node_id: str, worker_id: int, device_id: str) -> dict[str, Any]:
    node_id = _safe_node_id(logical_node_id)
    device = earnapp_runtime.validate_device_id(device_id)
    before = await database.get_earnapp_logical_node(node_id)
    node = await earnapp_recovery.provision_node(node_id, int(worker_id), device_id=device, proxy_country_code="VN")
    return {**node, "created_binding": not bool((before or {}).get("current_proxy_id"))}


async def deploy_canary(
    logical_node_id: str,
    worker_id: int,
    *,
    worker_deploy: WorkerDeploy,
    worker_remove: WorkerRemove,
) -> dict[str, Any]:
    node_id = _safe_node_id(logical_node_id)
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
                await worker_remove(int(worker_id), node_id)
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
            await worker_remove(int(worker_id), node_id)
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


async def verify_canary(
    logical_node_id: str,
    *,
    attempts: int = LINK_VERIFY_ATTEMPTS,
    interval_seconds: float = LINK_VERIFY_INTERVAL_SECONDS,
) -> dict[str, Any]:
    """Link and verify one provisioned canary through its exact account route."""
    node_id = _safe_node_id(logical_node_id)
    node = await database.get_earnapp_logical_node(node_id)
    if not node or str(node.get("state") or "") != "ACTIVE":
        raise ValueError("EarnApp canary is not active")
    account = await database.get_earnapp_account_credentials(int(node.get("account_id") or 0))
    if not account or str(account.get("state") or "") != "ACTIVE":
        raise ValueError("EarnApp canary account is not active")
    routes = await database.get_earnapp_account_node_routes(int(node["account_id"]), healthy_only=True)
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
    remaining = max(1, int(attempts))
    last: dict[str, Any] = {}
    for attempt in range(1, remaining + 1):
        last = await collector.link_and_verify_device(str(node.get("device_id") or ""), platform="macos")
        if last.get("online") is True and last.get("device_present") is True and last.get("banned") is not True:
            return earnapp_runtime.redacted_evidence(last)
        if last.get("error_kind") in {"auth", "shape"} or last.get("banned") is True or attempt >= remaining:
            break
        await asyncio.sleep(max(0, float(interval_seconds)))
    return earnapp_runtime.redacted_evidence(last)
