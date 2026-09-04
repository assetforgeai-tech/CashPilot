"""Generate and validate persisted EarnApp identities for supported platforms."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import string
import time
import uuid
from collections.abc import Mapping
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app import earnapp_runtime

SUPPORTED_PLATFORMS = frozenset({"macos", "ios", "ubuntu"})
IOS_PROFILE_ASSET_KIND = "ios_identity_profile"
UBUNTU_IDENTITY_ASSET_KIND = "ubuntu_identity_profile"
IOS_DEVICE_PREFIX = "sdk-ios-"
IOS_CP_ID = earnapp_runtime.IOS_INSTALL_APPID
UBUNTU_DEVICE_PREFIX = "sdk-node-"
# The SDK 1.660.577 filters 172.16.0.0/12 as Docker bridge space. Keep the
# provider's identity metadata outside that range so its interface survives.
PROXY_TUN_IP = "10.255.255.1"

_IOS_CATALOG = (
    ("iPhone14,5", "17.4.1", "21E237", "23.4.0", "CFNetwork/1496.0.7", "iPhone 13", "A15"),
    ("iPhone15,2", "17.6.1", "21G93", "23.6.0", "CFNetwork/1498.700.2", "iPhone 14 Pro", "A16"),
    ("iPhone16,2", "18.2.1", "22C161", "24.2.0", "CFNetwork/1568.200.51", "iPhone 15 Pro Max", "A17 Pro"),
    ("iPhone17,3", "18.4.1", "22E252", "24.4.0", "CFNetwork/1568.400.1", "iPhone 16", "A18"),
    ("iPhone17,2", "18.5", "22F76", "24.5.0", "CFNetwork/1575.500.1", "iPhone 16 Pro", "A18 Pro"),
)
_MAC_CATALOG = (
    ("MacBookPro17,1", "11.0.1", "20B50", "20.1.0", "Big Sur", "1209.0.0"),
    ("MacBookPro18,3", "12.6.8", "21G725", "21.6.0", "Monterey", "1335.0.3"),
    ("MacBookPro18,2", "13.6.7", "22G720", "22.6.0", "Ventura", "1408.0.4"),
    ("MacBookPro20,1", "14.6.1", "23G93", "23.6.0", "Sonoma", "1498.700.2"),
)

_MAC_STATE_FIELDS = frozenset(
    {
        "battery_percentage",
        "full_screen",
        "full_screen_ts",
        "idle_state",
        "monitor_power",
        "power_source",
        "session_state",
        "user_io",
    }
)
_IOS_REFERENCE_FIELDS = frozenset(
    {
        "codename",
        "conf_user",
        "confdir",
        "cp_id",
        "device_kind",
        "device_marketing",
        "device_model",
        "gw_ip",
        "iface_type",
        "is_swift",
        "mobile_type",
        "soc",
    }
)


def _platform(value: str) -> str:
    platform = str(value or "").strip().lower()
    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError("unsupported EarnApp platform")
    return platform


def _node_suffix(logical_node_id: str) -> str:
    value = str(logical_node_id or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,120}", value):
        raise ValueError("invalid EarnApp logical node id")
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def _random_text(length: int, alphabet: str) -> str:
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _local_unicast_mac() -> str:
    raw = bytearray(secrets.token_bytes(6))
    raw[0] = (raw[0] | 0x02) & 0xFE
    return ":".join(f"{part:02x}" for part in raw)


def _device_id(prefix: str, identity: dict[str, Any]) -> str:
    digest = hashlib.sha256((str(identity["id"]) + str(identity["serial"])).encode()).hexdigest()[:32]
    return prefix + digest


def device_id_for_identity(identity: dict[str, Any], platform: str) -> str:
    selected = _platform(platform)
    if selected == "macos":
        return _device_id(earnapp_runtime.MAC_DEVICE_PREFIX, identity)
    if selected == "ios":
        return _device_id(IOS_DEVICE_PREFIX, identity)
    return str(identity.get("device_id") or "")


def _base_state() -> dict[str, Any]:
    return {
        "idle": False,
        "ipv6_supported": False,
        "http3": True,
        "status_send": True,
        "mobile_connected": False,
        "roaming": False,
        "is_debug": False,
        "skip_local_addr": True,
        "usage": {"total_bytes": 0, "app_bytes": 0},
        "timezone": "Asia/Ho_Chi_Minh",
        "consent_ts": 0,
    }


def _usage_state(*, mobile: bool, battery_percentage: int) -> dict[str, Any]:
    return {
        "total_bytes": "",
        "app_bytes": json.dumps(
            {
                "wifi_connected": bool(mobile),
                "screen_on": bool(mobile),
                "battery_level": int(battery_percentage),
                "using_battery": bool(mobile),
                "on_call": False,
                "roaming": False,
                "mobile_connected": False,
            },
            separators=(",", ":"),
        ),
    }


def _runtime_state(*, mobile: bool, battery_percentage: int) -> dict[str, Any]:
    state: dict[str, Any] = {
        "full_screen": "off",
        "power_source": secrets.choice(("AC", "battery")) if mobile else "AC",
        "monitor_power": "on",
        "battery_percentage": int(battery_percentage),
        "session_state": "logged",
        "idle_state": {
            "cpu_usage": secrets.randbelow(11) + 2 if mobile else secrets.randbelow(5),
            "mem_usage": secrets.randbelow(21) + 8 if mobile else secrets.randbelow(6),
        },
    }
    if mobile:
        return state
    state.update(
        {
            "user_io": 2_806_000 + secrets.randbelow(1_194_001),
            "full_screen_ts": time.time_ns() // 1_000_000,
        }
    )
    return state


def _mac_identity(logical_node_id: str) -> dict[str, Any]:
    suffix = _node_suffix(logical_node_id)
    model, os_version, os_build, uname_r, codename, cfnetwork = secrets.choice(_MAC_CATALOG)
    serial = secrets.token_hex(20)
    identity = {
        **_base_state(),
        "id": f"cp-macos-{os_version.replace('.', '')}-x64-{codename.lower().replace(' ', '-')}-{secrets.token_hex(4)}",
        "platform": earnapp_runtime.MAC_PLATFORM,
        "appid": earnapp_runtime.MAC_APPID,
        "version": "1.660.577",
        "sdk_version": "1.660.577",
        "arch": "x64",
        "release": f"Version {os_version} (Build {os_build})",
        "ifname": "en0",
        "iface_type": "eth",
        "hostname": f"MacBook-Pro-{suffix}",
        "local_hostname": f"MacBook-Pro-{suffix}",
        "conf_user": "cashpilot",
        "timezone": secrets.choice(("America/Los_Angeles", "America/New_York", "Europe/Berlin", "Europe/London")),
        "os_product": "macOS",
        "os_version": os_version,
        "os_build": os_build,
        "codename": codename,
        "device_model": model,
        "uname_s": "Darwin",
        "uname_m": "x86_64",
        "uname_r": uname_r,
        "serial_material_mac": _local_unicast_mac(),
        "serial": serial,
        "platform_serial": _random_text(11, string.ascii_uppercase + string.digits),
        "platform_uuid": str(uuid.uuid4()).upper(),
        "confdir": "file:///Users/cashpilot/Library/Application%20Support/com.earnapp/",
        "gw_ip": "0.0.0.0",
        "lan_ip": PROXY_TUN_IP,
        "is_swift": True,
        "makeflags": "DIST=APP RELEASE=y AUTO_SIGN=y IS_MACOS=y MACOS_SDK=y CONFIG_BATREQ=y CONFIG_BAT_CYCLE=y",
        "bat_platform": "app_macr_mac_sdk",
        "new_state": _runtime_state(mobile=False, battery_percentage=-1),
        "perf": {
            "cpu": "0.0",
            "cpu_max": "0.0",
            "mem": "8192",
            "mem_free": secrets.choice(("2048", "2210", "2300", "3840", "4096", "4200", "5120")),
            "mem_max": "8192",
        },
        "perr_os_version": f"OS version: macOS {os_version}",
        "ua": f"brdsdk/1.660.577 CFNetwork/{cfnetwork} Darwin/{uname_r}",
    }
    identity["usage"] = _usage_state(mobile=False, battery_percentage=-1)
    identity["device_id"] = _device_id(earnapp_runtime.MAC_DEVICE_PREFIX, identity)
    return identity


def _ios_identity(logical_node_id: str) -> dict[str, Any]:
    suffix = _node_suffix(logical_node_id)
    model, os_version, os_build, uname_r, cfnetwork, marketing, soc = secrets.choice(_IOS_CATALOG)
    serial = _random_text(10, string.ascii_uppercase + string.digits)
    major = os_version.split(".", 1)[0]
    container_uuid = str(uuid.uuid4()).upper()
    battery_percentage = secrets.choice((38, 52, 67, 81, 94))
    memory_usage = (281 + secrets.randbelow(89)) / 10
    memory_max = max(memory_usage, (321 + secrets.randbelow(49)) / 10)
    identity = {
        **_base_state(),
        "id": f"cp-ios-{model.lower().replace(',', '')}-{os_version}-{secrets.token_hex(4)}",
        "platform": "ios",
        "appid": "com.brd.earnapp",
        "tv_platform": "ios",
        "version": "1.617.813",
        "sdk_version": "1.617.813",
        "arch": "arm64",
        "release": f"Version {os_version} (Build {os_build})",
        "ifname": "en0",
        "serial": serial,
        "hostname": f"iPhone-{suffix}",
        "local_hostname": f"iPhone-{suffix}",
        "os_product": "iOS",
        "os_version": os_version,
        "os_build": os_build,
        "codename": f"iOS {major}",
        "device_model": model,
        "device_marketing": marketing,
        "device_kind": "iphone",
        "soc": soc,
        "uname_s": "Darwin",
        "uname_m": "arm64",
        "uname_r": uname_r,
        "conf_user": "mobile",
        "confdir": (
            "file:///var/mobile/Containers/Data/Application/"
            f"{container_uuid}/Library/Application%20Support/com.brd.earnapp/"
        ),
        # The app identity is stable across installs; the container UUID is
        # the per-node value carried by confdir and the persisted profile.
        "cp_id": IOS_CP_ID,
        "gw_ip": "0.0.0.0",
        "iface_type": "wifi",
        "identifier_for_vendor": str(uuid.uuid4()).upper(),
        "container_uuid": container_uuid,
        "wifi_mac": _local_unicast_mac(),
        "lan_ip": PROXY_TUN_IP,
        "is_swift": True,
        "mobile_type": "wifi",
        "makeflags": "DIST=APP RELEASE=y IS_IOS=y IOS_SDK=y IOS_UNITY=n CONFIG_BATREQ=y CONFIG_BAT_CYCLE=y CONFIG_BAT_PLATFORM=app_macr_ios_sdk",
        "bat_platform": "app_macr_ios_sdk",
        "new_state": _runtime_state(mobile=True, battery_percentage=battery_percentage),
        "perf": {
            "cpu": "0.15",
            "cpu_max": "1.4",
            "mem": f"{memory_usage:.1f}",
            "mem_free": secrets.choice(("800", "900", "1400", "1500", "2100", "2200")),
            "mem_max": f"{memory_max:.1f}",
        },
        "perr_os_version": f"OS version: iOS {os_version}",
        "ua": f"earnapp/1 {cfnetwork} Darwin/{uname_r}",
    }
    identity["usage"] = _usage_state(mobile=True, battery_percentage=battery_percentage)
    identity["device_id"] = _device_id(IOS_DEVICE_PREFIX, identity)
    return identity


def _ubuntu_identity(logical_node_id: str) -> dict[str, Any]:
    suffix = _node_suffix(logical_node_id)
    machine_id = secrets.token_hex(16)
    serial = secrets.token_hex(16)
    identity = {
        "platform": "ubuntu",
        "appid": earnapp_runtime.UBUNTU_APPID,
        "id": secrets.token_hex(16),
        "serial": serial,
        "machine_id": machine_id,
        "hostname": f"earnapp-{suffix}",
        "local_hostname": f"earnapp-{suffix}",
        "os_version": "22.04.5",
        "os_release": "Ubuntu 22.04.5 LTS",
        "release": "ubuntu_22.04_x64",
        "arch": "amd64",
        "ifname": "enp2s0",
        "mac_address": _local_unicast_mac(),
        "lan_ip": PROXY_TUN_IP,
        "conf_user": "victor",
        "confdir": "/home/victor/.config/earnapp",
        "device_model": "Beelink SER5",
        "vendor": "AZW",
        "product": "SER5",
        "board": "SER5",
        "soc": "Rembrandt",
        "cpu_model": "AMD Ryzen 5 5560U with Radeon Graphics",
        "cpu_cores": 12,
        "memory_total": 1024 * 1024 * 1024,
    }
    identity["device_id"] = UBUNTU_DEVICE_PREFIX + uuid.uuid4().hex
    return identity


def generate_identity(logical_node_id: str, platform: str) -> dict[str, Any]:
    selected = _platform(platform)
    identity = {
        "macos": _mac_identity,
        "ios": _ios_identity,
        "ubuntu": _ubuntu_identity,
    }[selected](logical_node_id)
    validate_identity(identity, selected)
    return identity


def _validate_reference_shape(identity: Mapping[str, Any], platform: str) -> None:
    """Validate optional fields when present without breaking legacy profiles."""
    state = identity.get("new_state")
    if state is not None:
        if not isinstance(state, Mapping):
            raise ValueError("EarnApp new_state must be an object")
        if "idle_state" in state and not isinstance(state.get("idle_state"), Mapping):
            raise ValueError(f"EarnApp {platform} idle_state must be an object")
        if "session_state" in state and str(state.get("session_state") or "") not in {"logged", "active"}:
            raise ValueError(f"EarnApp {platform} session_state is invalid")

    usage = identity.get("usage")
    if usage is not None:
        if not isinstance(usage, Mapping):
            raise ValueError(f"EarnApp {platform} usage must be an object")
        app_bytes = usage.get("app_bytes")
        if app_bytes is not None and not isinstance(app_bytes, (str, int, float)):
            raise ValueError(f"EarnApp {platform} app_bytes is invalid")
        if isinstance(app_bytes, str) and app_bytes:
            try:
                parsed = json.loads(app_bytes)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"EarnApp {platform} app_bytes is invalid") from exc
            if not isinstance(parsed, Mapping):
                raise ValueError(f"EarnApp {platform} app_bytes must encode an object")

    if platform == "ios":
        # Version 1.617.813 is the audited profile generation. Legacy stored
        # profiles remain readable, but newly generated profiles fail closed
        # if any reference field is missing.
        if str(identity.get("version") or "") == "1.617.813":
            missing = sorted(_IOS_REFERENCE_FIELDS - identity.keys())
            if missing:
                raise ValueError(f"EarnApp iOS reference profile is missing: {', '.join(missing)}")
        present = _IOS_REFERENCE_FIELDS.intersection(identity)
        if "device_kind" in present and str(identity.get("device_kind") or "").lower() != "iphone":
            raise ValueError("EarnApp iOS device_kind is invalid")
        if "iface_type" in present and str(identity.get("iface_type") or "").lower() != "wifi":
            raise ValueError("EarnApp iOS iface_type is invalid")
        if "mobile_type" in present and str(identity.get("mobile_type") or "").lower() != "wifi":
            raise ValueError("EarnApp iOS mobile_type is invalid")
        if "is_swift" in present and identity.get("is_swift") is not True:
            raise ValueError("EarnApp iOS is_swift must be true")


def validate_identity(identity: dict[str, Any], platform: str) -> None:
    selected = _platform(platform)
    if not isinstance(identity, dict):
        raise ValueError("EarnApp identity must be an object")
    if selected == "macos":
        earnapp_runtime.validate_identity_contract(identity)
        _validate_reference_shape(identity, selected)
        expected = _device_id(earnapp_runtime.MAC_DEVICE_PREFIX, identity)
        if identity.get("device_id") and identity.get("device_id") != expected:
            raise ValueError("EarnApp Mac device identity is invalid")
        return
    if selected == "ios":
        required = {
            "id",
            "appid",
            "arch",
            "ifname",
            "serial",
            "uname_r",
            "os_version",
            "device_model",
            "perr_os_version",
            "lan_ip",
            "local_hostname",
        }
        missing = sorted(required - identity.keys())
        if missing:
            raise ValueError(f"EarnApp iOS profile is missing: {', '.join(missing)}")
        try:
            major = int(str(identity.get("os_version") or "0").split(".", 1)[0])
        except ValueError:
            major = 0
        makeflags = str(identity.get("makeflags") or "")
        valid = (
            identity.get("appid") == "com.brd.earnapp"
            and identity.get("tv_platform") == "ios"
            and identity.get("arch") == "arm64"
            and str(identity.get("device_model") or "").startswith("iPhone")
            and major >= 14
            and identity.get("idle") is False
            and not identity.get("ipv6_supported")
            and identity.get("bat_platform") == "app_macr_ios_sdk"
            and "app_macr_ios_sdk" in makeflags
            and "IS_IOS=y" in makeflags
            and (not identity.get("device_id") or identity.get("device_id") == _device_id(IOS_DEVICE_PREFIX, identity))
        )
        if not valid:
            raise ValueError("EarnApp iOS Bright Rewards identity is invalid")
        if any(
            term in json.dumps(identity, sort_keys=True).lower() for term in ("2movn", "mac_com.earnapp", "sdk-mac-")
        ):
            raise ValueError("EarnApp iOS identity mixes a Mac or lab profile")
        _validate_reference_shape(identity, selected)
        return
    required = {
        "id",
        "platform",
        "appid",
        "arch",
        "release",
        "ifname",
        "serial",
        "machine_id",
        "hostname",
        "local_hostname",
        "os_version",
        "os_release",
        "device_model",
        "vendor",
        "product",
        "board",
        "soc",
        "conf_user",
        "confdir",
        "lan_ip",
        "mac_address",
        "cpu_model",
        "cpu_cores",
        "memory_total",
        "device_id",
    }
    missing = sorted(required - identity.keys())
    if missing:
        raise ValueError(f"EarnApp Ubuntu profile is missing: {', '.join(missing)}")
    if (
        identity.get("platform") != "ubuntu"
        or identity.get("appid") != earnapp_runtime.UBUNTU_APPID
        or identity.get("arch") != "amd64"
        or identity.get("release") != "ubuntu_22.04_x64"
        or identity.get("ifname") != "enp2s0"
        or not re.fullmatch(r"[0-9a-f]{32}", str(identity.get("id") or ""))
        or not re.fullmatch(r"[0-9a-f]{32}", str(identity.get("serial") or ""))
        or not re.fullmatch(r"[0-9a-f]{32}", str(identity.get("machine_id") or ""))
        or not re.fullmatch(r"sdk-node-[0-9a-f]{32}", str(identity.get("device_id") or ""))
        or not str(identity.get("hostname") or "").startswith("earnapp-")
        or str(identity.get("local_hostname") or "") != str(identity.get("hostname") or "")
    ):
        raise ValueError("EarnApp Ubuntu identity is invalid")


def validate_and_decode_ubuntu_profile(value: str) -> dict[str, Any]:
    """Decode the opaque persisted Ubuntu identity and validate it before use."""
    try:
        identity = json.loads(str(value or ""))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("EarnApp Ubuntu identity profile is invalid") from exc
    if not isinstance(identity, dict):
        raise ValueError("EarnApp Ubuntu identity profile is invalid")
    validate_identity(identity, "ubuntu")
    return identity


def _upgrade_macos_runtime_metadata(identity: dict[str, Any]) -> bool:
    """Migrate legacy persisted profiles to the audited SDK metadata in place."""
    version = str(identity.get("version") or identity.get("sdk_version") or "")
    if version == "1.660.577" and str(identity.get("sdk_version") or "") == "1.660.577":
        return False
    if not version.startswith("1."):
        return False
    identity["version"] = "1.660.577"
    identity["sdk_version"] = "1.660.577"
    identity["lan_ip"] = PROXY_TUN_IP
    ua = str(identity.get("ua") or "")
    if ua.startswith("brdsdk/"):
        identity["ua"] = re.sub(r"^brdsdk/[0-9.]+", "brdsdk/1.660.577", ua)
    identity["bat_platform"] = "app_macr_mac_sdk"
    flags = str(identity.get("makeflags") or "")
    removed = {
        "IS_MAC_BVPN",
        "CONFIG_NOTARIZE_NET_UPDATER",
        "CONFIG_NOTARIZE_EARNAPP_INSTALLER",
        "MAC_MAKE_DMG",
    }
    tokens = [token for token in flags.split() if token and token.split("=", 1)[0] not in removed]
    for required in ("DIST=APP", "RELEASE=y", "AUTO_SIGN=y", "IS_MACOS=y", "MACOS_SDK=y"):
        if required not in tokens:
            tokens.append(required)
    identity["makeflags"] = " ".join(tokens)
    return True


def encrypt_profile(identity: dict[str, Any]) -> str:
    if identity.get("tv_platform") == "ios":
        validate_identity(identity, "ios")
    else:
        validate_identity(identity, "macos")
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    aad = earnapp_runtime.MAC_PROFILE_MAGIC + bytes([earnapp_runtime.MAC_PROFILE_VERSION]) + salt
    plaintext = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ciphertext = AESGCM(earnapp_runtime.MAC_PROFILE_KEY).encrypt(nonce, plaintext, aad)
    return base64.b64encode(aad + nonce + ciphertext).decode("ascii")


def decrypt_profile(value: str, platform: str) -> dict[str, Any]:
    blob = base64.b64decode(str(value or ""), validate=True)
    if (
        len(blob) < 49
        or blob[:4] != earnapp_runtime.MAC_PROFILE_MAGIC
        or blob[4] != earnapp_runtime.MAC_PROFILE_VERSION
    ):
        raise ValueError("invalid EarnApp identity profile envelope")
    plaintext = AESGCM(earnapp_runtime.MAC_PROFILE_KEY).decrypt(blob[21:33], blob[33:], blob[:21])
    identity = json.loads(plaintext.decode())
    validate_identity(identity, platform)
    return identity


async def ensure_identity_profile(logical_node_id: str, platform: str) -> dict[str, str]:
    """Return one durable identity profile and reject platform/collision drift."""
    from app import database

    selected = _platform(platform)
    node_id = str(logical_node_id or "").strip().lower()
    _node_suffix(node_id)
    existing = await database.get_earnapp_identity_profile(node_id)
    if existing:
        stored_platform = str(existing.get("platform") or "").strip().lower()
        stored_kind = str(existing.get("asset_kind") or "").strip().lower()
        if not stored_platform:
            stored_platform = "macos" if stored_kind in {"", earnapp_runtime.MAC_IDENTITY_ASSET_KIND} else ""
        if stored_platform != selected:
            raise ValueError("EarnApp logical node identity platform is immutable")
        value = str(existing["value"])
        if selected in {"macos", "ios"}:
            identity = decrypt_profile(value, selected)
        else:
            identity = json.loads(value)
            validate_identity(identity, selected)
        if device_id_for_identity(identity, selected) != str(existing["device_id"]):
            raise ValueError("EarnApp persisted device identity changed")
        if selected == "macos" and _upgrade_macos_runtime_metadata(identity):
            value = encrypt_profile(identity)
            await database.save_earnapp_identity_profile(
                node_id,
                platform=selected,
                asset_kind=stored_kind or earnapp_runtime.MAC_IDENTITY_ASSET_KIND,
                device_id=str(existing["device_id"]),
                value=value,
            )
        return {
            "asset_id": node_id,
            "asset_kind": stored_kind or earnapp_runtime.MAC_IDENTITY_ASSET_KIND,
            "platform": selected,
            "device_id": str(existing["device_id"]),
            "value": value,
        }

    identity = generate_identity(node_id, selected)
    asset_kind = {
        "macos": earnapp_runtime.MAC_IDENTITY_ASSET_KIND,
        "ios": IOS_PROFILE_ASSET_KIND,
        "ubuntu": UBUNTU_IDENTITY_ASSET_KIND,
    }[selected]
    value = (
        encrypt_profile(identity)
        if selected in {"macos", "ios"}
        else json.dumps(identity, sort_keys=True, separators=(",", ":"))
    )
    await database.save_earnapp_identity_profile(
        node_id,
        platform=selected,
        asset_kind=asset_kind,
        device_id=str(identity["device_id"]),
        value=value,
    )
    return {
        "asset_id": node_id,
        "asset_kind": asset_kind,
        "platform": selected,
        "device_id": str(identity["device_id"]),
        "value": value,
    }
