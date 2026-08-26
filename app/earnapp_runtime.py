"""Small, secret-free helpers for the verified EarnApp Mac wire contract."""

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

# These are the only runtime artifacts copied into the canary image.  The
# binaries remain outside Git; the hashes pin the exact local source bundle
# used by the image build helper.
MAC_RUNTIME_ARTIFACT_HASHES = {
    "boot.js": "c58e9f8276e4cc25a94f73fb6b11048477792e57d2f3839445982626bb8a77c2",
    "earn-supervisor": "550204505e47a29ca7d4b3853aefb8d05982a566744809fa65c10edf6c2531a2",
    "earnapp-mac": "977483ef03f1967c2a6fda07e978000a12218c46855c5d86ccb1e09b2fefe757",
    "entrypoint.sh": "13497536e56a8eeb204c697ed7ca89de11017d0daf49cab49e63f2984682a6c2",
}


def runtime_asset_manifest(artifact_hashes: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Return the canonical manifest used to pin the Mac runtime build."""
    hashes = artifact_hashes or MAC_RUNTIME_ARTIFACT_HASHES
    return {
        "version": 1,
        "artifacts": [{"path": str(path), "sha256": str(digest).lower()} for path, digest in sorted(hashes.items())],
    }


def runtime_asset_manifest_bytes(artifact_hashes: Mapping[str, str] | None = None) -> bytes:
    payload = json.dumps(
        runtime_asset_manifest(artifact_hashes),
        sort_keys=True,
        separators=(",", ":"),
    )
    return (payload + "\n").encode("utf-8")


def runtime_asset_manifest_sha256(artifact_hashes: Mapping[str, str] | None = None) -> str:
    return hashlib.sha256(runtime_asset_manifest_bytes(artifact_hashes)).hexdigest()


MAC_RUNTIME_ASSET_MANIFEST_SHA256 = runtime_asset_manifest_sha256()
MAC_RUNTIME_IMAGE = f"cashpilot/earnapp-mac-canary:asset-{MAC_RUNTIME_ASSET_MANIFEST_SHA256[:12]}"
MAC_RUNTIME_HOST = "earnapp_mac_canary"
MAC_PROFILE_MAGIC = b"ESPF"
MAC_PROFILE_VERSION = 1
# Keep this precomputed key in lock-step with the official ``boot.js`` fallback
# derivation. It is a protocol compatibility value, never a credential hash.
MAC_PROFILE_KEY_HEX = "c0f6e9049acba2e1980b0dfd3dbe0fdbde5df4706235f814651722592bd6fa55"
MAC_PROFILE_KEY = bytes.fromhex(MAC_PROFILE_KEY_HEX)


def required_image_labels() -> dict[str, str]:
    return {
        "com.cashpilot.earnapp.runtime": MAC_RUNTIME_HOST,
        "com.cashpilot.earnapp.platform": MAC_PLATFORM,
        "com.cashpilot.earnapp.appid": MAC_APPID,
        "com.cashpilot.earnapp.device-prefix": MAC_DEVICE_PREFIX,
        "com.cashpilot.earnapp.assets-sha256": MAC_RUNTIME_ASSET_MANIFEST_SHA256,
    }


def validate_image_labels(labels: Any) -> None:
    actual = labels if isinstance(labels, dict) else {}
    missing = [key for key, expected in required_image_labels().items() if str(actual.get(key) or "") != expected]
    if missing:
        raise ValueError(f"EarnApp image is missing verified Mac labels: {', '.join(missing)}")


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
    blocked = {"password", "proxy_password", "oauth-refresh-token", "xsrf-token", "credentials", "token"}
    return {str(k): v for k, v in value.items() if str(k).lower() not in blocked}
