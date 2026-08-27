"""Secret-free helpers for the verified EarnApp platform wire contracts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAC_IDENTITY_ASSET_KIND = "mac_identity_profile"
MAC_PLATFORM = "darwin"
MAC_APPID = "mac_com.earnapp"
MAC_DEVICE_PREFIX = "sdk-mac-"
IOS_PLATFORM = "ios"
IOS_APPID = "com.brd.earnapp"
IOS_DEVICE_PREFIX = "sdk-ios-"

# These are the only runtime artifacts copied into the canary image.  The
# binaries remain outside Git; the hashes pin the exact local source bundle
# used by the image build helper.
MAC_RUNTIME_ARTIFACT_HASHES = {
    "boot.js": "c58e9f8276e4cc25a94f73fb6b11048477792e57d2f3839445982626bb8a77c2",
    "earn-supervisor": "550204505e47a29ca7d4b3853aefb8d05982a566744809fa65c10edf6c2531a2",
    "earnapp-mac": "977483ef03f1967c2a6fda07e978000a12218c46855c5d86ccb1e09b2fefe757",
    "entrypoint.sh": "c7b922bc4e47c2b87bfee3fdbfc32ac4582bcb6b3d7db54ab78be2d212a02af9",
}

IOS_RUNTIME_ARTIFACT_HASHES = {
    "boot.js": "5de4b51eecdaf4b8b01bd5a2cafd019c701f877b9add727f405d6409f0c1793d",
    "earn-supervisor": "170c39c7821b7fd6110b96242b703fd6a0541dee29cf6c4525c3a70b67d42a25",
    "earnapp-bootstrap": "be9c4f6865134c87dbae373304e4b20bc55e91f60d2744ac03ebb864ca7fc2ee",
    "entrypoint.sh": "50b32e6f7280da75a7568cd25b6e4e43797f254517b1ee316f5b359f24e4144e",
}

_PLATFORM_CONTRACTS = {
    "macos": {
        "artifact_hashes": MAC_RUNTIME_ARTIFACT_HASHES,
        "runtime": "earnapp_mac_canary",
        "platform": MAC_PLATFORM,
        "appid": MAC_APPID,
        "device_prefix": MAC_DEVICE_PREFIX,
        "image": "cashpilot/earnapp-mac-canary",
    },
    "ios": {
        "artifact_hashes": IOS_RUNTIME_ARTIFACT_HASHES,
        "runtime": "earnapp_ios",
        "platform": IOS_PLATFORM,
        "appid": IOS_APPID,
        "device_prefix": IOS_DEVICE_PREFIX,
        "image": "cashpilot/earnapp-ios",
    },
}


def _image_platform(platform: str) -> str:
    value = str(platform or "macos").strip().lower()
    if value not in _PLATFORM_CONTRACTS:
        raise ValueError("unsupported EarnApp image platform")
    return value


def runtime_asset_manifest(
    artifact_hashes: Mapping[str, str] | None = None,
    *,
    platform: str = "macos",
) -> dict[str, Any]:
    """Return the canonical manifest used to pin one emulated runtime build."""
    selected = _image_platform(platform)
    hashes = artifact_hashes or _PLATFORM_CONTRACTS[selected]["artifact_hashes"]
    return {
        "version": 1,
        "artifacts": [{"path": str(path), "sha256": str(digest).lower()} for path, digest in sorted(hashes.items())],
    }


def runtime_asset_manifest_bytes(
    artifact_hashes: Mapping[str, str] | None = None,
    *,
    platform: str = "macos",
) -> bytes:
    payload = json.dumps(
        runtime_asset_manifest(artifact_hashes, platform=platform),
        sort_keys=True,
        separators=(",", ":"),
    )
    return (payload + "\n").encode("utf-8")


def runtime_asset_manifest_sha256(
    artifact_hashes: Mapping[str, str] | None = None,
    *,
    platform: str = "macos",
) -> str:
    return hashlib.sha256(runtime_asset_manifest_bytes(artifact_hashes, platform=platform)).hexdigest()


MAC_RUNTIME_ASSET_MANIFEST_SHA256 = runtime_asset_manifest_sha256()
MAC_RUNTIME_IMAGE = f"cashpilot/earnapp-mac-canary:asset-{MAC_RUNTIME_ASSET_MANIFEST_SHA256[:12]}"
MAC_RUNTIME_HOST = "earnapp_mac_canary"
IOS_RUNTIME_ASSET_MANIFEST_SHA256 = runtime_asset_manifest_sha256(platform="ios")
IOS_RUNTIME_IMAGE = f"cashpilot/earnapp-ios:asset-{IOS_RUNTIME_ASSET_MANIFEST_SHA256[:12]}"
IOS_RUNTIME_HOST = "earnapp_ios"
MAC_PROFILE_MAGIC = b"ESPF"
MAC_PROFILE_VERSION = 1
# Keep this precomputed key in lock-step with the official ``boot.js`` fallback
# derivation. It is a protocol compatibility value, never a credential hash.
MAC_PROFILE_KEY_HEX = "c0f6e9049acba2e1980b0dfd3dbe0fdbde5df4706235f814651722592bd6fa55"
MAC_PROFILE_KEY = bytes.fromhex(MAC_PROFILE_KEY_HEX)


def runtime_image(platform: str = "macos") -> str:
    selected = _image_platform(platform)
    contract = _PLATFORM_CONTRACTS[selected]
    digest = runtime_asset_manifest_sha256(platform=selected)
    return f"{contract['image']}:asset-{digest[:12]}"


def required_image_labels(platform: str = "macos") -> dict[str, str]:
    selected = _image_platform(platform)
    contract = _PLATFORM_CONTRACTS[selected]
    return {
        "com.cashpilot.earnapp.runtime": str(contract["runtime"]),
        "com.cashpilot.earnapp.platform": str(contract["platform"]),
        "com.cashpilot.earnapp.appid": str(contract["appid"]),
        "com.cashpilot.earnapp.device-prefix": str(contract["device_prefix"]),
        "com.cashpilot.earnapp.assets-sha256": runtime_asset_manifest_sha256(platform=selected),
    }


def validate_image_labels(labels: Any, platform: str = "macos") -> None:
    actual = labels if isinstance(labels, dict) else {}
    missing = [
        key for key, expected in required_image_labels(platform).items() if str(actual.get(key) or "") != expected
    ]
    if missing:
        raise ValueError(f"EarnApp image is missing verified labels: {', '.join(missing)}")


def validate_canary_spec(spec: dict[str, Any]) -> None:
    """Fail closed on the worker boundary for the owner-only Mac lane."""
    if str(spec.get("provider_slug") or "") != "earnapp":
        raise ValueError("EarnApp canary provider is required")
    if str(spec.get("host_runtime") or "") != MAC_RUNTIME_HOST:
        raise ValueError("EarnApp Mac canary host runtime is required")
    if str(spec.get("image") or "") != MAC_RUNTIME_IMAGE:
        raise ValueError("EarnApp image is not the verified Mac canary image")
    if spec.get("privileged") or spec.get("cap_add") or spec.get("devices"):
        raise ValueError("EarnApp canary cannot request privilege, capabilities, or devices")
    if spec.get("network_mode") not in (None, "", "bridge"):
        raise ValueError("EarnApp canary network mode is invalid")
    if str(spec.get("egress_mode") or "") != "proxy":
        raise ValueError("EarnApp canary must use proxy egress")
    contract = spec.get("runtime_contract") or {}
    if contract != {"platform": MAC_PLATFORM, "appid": MAC_APPID, "device_id_prefix": MAC_DEVICE_PREFIX}:
        raise ValueError("EarnApp Mac runtime contract is not verified")
    labels = spec.get("labels") or {}
    for key, expected in {
        "cashpilot.provider": "earnapp",
        "cashpilot.earnapp.platform": MAC_PLATFORM,
        "cashpilot.earnapp.runtime_contract": MAC_APPID,
    }.items():
        if str(labels.get(key) or "") != expected:
            raise ValueError(f"EarnApp canary label {key} is invalid")
    device_id = validate_device_id(str(spec.get("env", {}).get("EARNAPP_DEVICE_ID") or ""))
    if not str(labels.get("cashpilot.earnapp.device_id") or "") == device_id:
        raise ValueError("EarnApp device label does not match the runtime identity")
    assets = spec.get("runtime_assets") or []
    if len(assets) != 1:
        raise ValueError("EarnApp canary requires exactly one encrypted Mac profile")
    asset = assets[0]
    if (
        str(asset.get("provider") or "") != "earnapp"
        or str(asset.get("asset_kind") or "") != MAC_IDENTITY_ASSET_KIND
        or str(asset.get("target") or "") != "/etc/earnapp-spoof/profile.json.enc"
        or str(asset.get("encoding") or "") != "base64"
        or not str(asset.get("asset_id") or "").strip()
    ):
        raise ValueError("EarnApp Mac profile asset reference is invalid")
    for source, mount in (spec.get("volumes") or {}).items():
        if str(source).startswith("/"):
            raise ValueError("EarnApp canary cannot use host system mounts")
        if str(mount.get("bind") or "") == "/etc/earnapp" and str(mount.get("mode") or "") != "rw":
            raise ValueError("EarnApp state volume must be writable")
    proxy = spec.get("proxy") or {}
    if not str(proxy.get("host") or "").strip() or not 1 <= int(proxy.get("port") or 0) <= 65535:
        raise ValueError("EarnApp canary proxy is incomplete")
    if str(proxy.get("protocol") or "").lower() not in {"http", "socks5"}:
        raise ValueError("EarnApp canary proxy protocol is invalid")


def validate_runtime_spec(spec: dict[str, Any]) -> None:
    labels = spec.get("labels") or {}
    platform_label = str(labels.get("cashpilot.earnapp.platform") or "").strip().lower()
    selected = "macos" if platform_label == MAC_PLATFORM else platform_label
    if selected == "macos":
        validate_canary_spec(spec)
        return
    if selected != "ios":
        raise ValueError("EarnApp Docker runtime supports only MacOS or iOS")
    if str(spec.get("provider_slug") or "") != "earnapp":
        raise ValueError("EarnApp provider is required")
    if str(spec.get("host_runtime") or "") != IOS_RUNTIME_HOST:
        raise ValueError("EarnApp iOS runtime is required")
    if str(spec.get("image") or "") != IOS_RUNTIME_IMAGE:
        raise ValueError("EarnApp image is not the verified iOS image")
    if spec.get("privileged") or spec.get("cap_add") or spec.get("devices"):
        raise ValueError("EarnApp iOS runtime cannot request host privilege")
    if spec.get("network_mode") not in (None, "", "bridge") or str(spec.get("egress_mode") or "") != "proxy":
        raise ValueError("EarnApp iOS runtime must use proxy bridge egress")
    contract = spec.get("runtime_contract") or {}
    expected_contract = {
        "platform": IOS_PLATFORM,
        "appid": IOS_APPID,
        "device_id_prefix": IOS_DEVICE_PREFIX,
    }
    if contract != expected_contract:
        raise ValueError("EarnApp iOS runtime contract is not verified")
    device_id = str((spec.get("env") or {}).get("EARNAPP_DEVICE_ID") or "")
    if not re.fullmatch(r"sdk-ios-[A-Za-z0-9-]{4,96}", device_id):
        raise ValueError("EarnApp iOS device identity is invalid")
    if str(labels.get("cashpilot.earnapp.device_id") or "") != device_id:
        raise ValueError("EarnApp iOS device label does not match")
    assets = spec.get("runtime_assets") or []
    if len(assets) != 1:
        raise ValueError("EarnApp iOS runtime requires one identity profile")
    asset = assets[0]
    if (
        str(asset.get("provider") or "") != "earnapp"
        or str(asset.get("asset_kind") or "") != "ios_identity_profile"
        or str(asset.get("target") or "") != "/etc/earnapp-spoof/profile.json.enc"
        or str(asset.get("encoding") or "") != "base64"
        or not str(asset.get("asset_id") or "").strip()
    ):
        raise ValueError("EarnApp iOS identity asset is invalid")


def encrypt_mac_profile(identity: dict[str, Any]) -> str:
    """Encode the official ESPF v1 profile consumed by ``boot.js``."""
    import base64
    import os

    plaintext = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    salt = os.urandom(16)
    nonce = os.urandom(12)
    aad = MAC_PROFILE_MAGIC + bytes([MAC_PROFILE_VERSION]) + salt
    ciphertext = AESGCM(MAC_PROFILE_KEY).encrypt(nonce, plaintext, aad)
    blob = aad + nonce + ciphertext
    return base64.b64encode(blob).decode("ascii")


def decrypt_mac_profile(value: str) -> dict[str, Any]:
    import base64

    blob = base64.b64decode(str(value or ""), validate=True)
    minimum = 4 + 1 + 16 + 12 + 16
    if len(blob) < minimum or blob[:4] != MAC_PROFILE_MAGIC or blob[4] != MAC_PROFILE_VERSION:
        raise ValueError("invalid EarnApp Mac profile envelope")
    nonce = blob[21:33]
    ciphertext = blob[33:]
    plaintext = AESGCM(MAC_PROFILE_KEY).decrypt(nonce, ciphertext, blob[:21])
    identity = json.loads(plaintext.decode("utf-8"))
    if not isinstance(identity, dict):
        raise ValueError("EarnApp Mac profile is not an object")
    validate_identity_contract(identity)
    return identity


def validate_identity_contract(identity: dict[str, Any]) -> None:
    required = {
        "id",
        "platform",
        "appid",
        "arch",
        "release",
        "ifname",
        "serial",
        "confdir",
        "uname_r",
        "os_version",
        "device_model",
        "ua",
        "perr_os_version",
        "makeflags",
        "lan_ip",
        "local_hostname",
    }
    missing = sorted(key for key in required if key not in identity)
    if missing:
        raise ValueError(f"EarnApp Mac profile is missing: {', '.join(missing)}")
    if identity.get("platform") != MAC_PLATFORM or identity.get("appid") != MAC_APPID:
        raise ValueError("EarnApp profile is not the Mac wire contract")
    if identity.get("idle") is not False or identity.get("ipv6_supported"):
        raise ValueError("EarnApp Mac profile has unsafe runtime flags")
    if "2movn" in json.dumps(identity, sort_keys=True).lower():
        raise ValueError("EarnApp lab identity is not allowed")


def validate_identity_asset_kind(asset_kind: str) -> str:
    value = str(asset_kind or "").strip().lower()
    if value != MAC_IDENTITY_ASSET_KIND:
        raise ValueError(f"EarnApp identity asset must be {MAC_IDENTITY_ASSET_KIND}")
    return value


def ensure_mac_identity(root: str | Path, *, seed: str) -> dict[str, str]:
    """Create a stable per-node identity marker without storing account secrets."""
    directory = Path(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "identity-contract.json"
    if path.is_file():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and value.get("platform") == MAC_PLATFORM:
                return {str(k): str(v) for k, v in value.items()}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
    digest = hashlib.sha256(str(seed).encode("utf-8")).hexdigest()[:32]
    value = {
        "platform": MAC_PLATFORM,
        "appid": MAC_APPID,
        "device_id": MAC_DEVICE_PREFIX + digest,
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
    return value


def validate_device_id(device_id: str) -> str:
    value = str(device_id or "").strip()
    if not re.fullmatch(r"sdk-mac-[A-Za-z0-9-]{4,96}", value):
        raise ValueError("EarnApp Mac device_id must use the sdk-mac- prefix")
    return value


def redacted_evidence(value: dict[str, Any] | None = None) -> dict[str, Any]:
    """Keep heartbeat evidence non-secret even if a caller passes raw metadata."""
    value = value if isinstance(value, dict) else {}
    blocked = {
        "password",
        "proxy_password",
        "proxy_username",
        "username",
        "oauth-refresh-token",
        "xsrf-token",
        "credentials",
        "token",
        "identity",
        "machine_id",
        "serial",
    }

    def clean(item: Any) -> Any:
        if isinstance(item, dict):
            return {str(key): clean(child) for key, child in item.items() if str(key).lower() not in blocked}
        if isinstance(item, list):
            return [clean(child) for child in item]
        return item

    return clean(value)
