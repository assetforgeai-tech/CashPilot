"""Cross-platform EarnApp identity contracts."""

from __future__ import annotations

import asyncio
import hashlib
import json
from unittest.mock import patch

import pytest

from app import database, earnapp_identity

MAC_REQUIRED_FIELDS = {
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
IOS_REQUIRED_FIELDS = {
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


def test_generate_macos_identity_is_complete_and_unique():
    first = earnapp_identity.generate_identity("node-mac-a", "macos")
    second = earnapp_identity.generate_identity("node-mac-b", "macos")

    earnapp_identity.validate_identity(first, "macos")
    earnapp_identity.validate_identity(second, "macos")
    assert first["platform"] == "darwin"
    assert first["appid"] == "mac_com.earnapp"
    assert first["device_id"].startswith("sdk-mac-")
    assert first["device_id"] != second["device_id"]
    assert first["id"] != second["id"]
    assert first.keys() >= MAC_REQUIRED_FIELDS


def test_generate_ios_identity_matches_bright_rewards_contract():
    identity = earnapp_identity.generate_identity("node-ios-a", "ios")

    earnapp_identity.validate_identity(identity, "ios")
    assert identity["appid"] == "com.brd.earnapp"
    assert identity["tv_platform"] == "ios"
    assert identity["arch"] == "arm64"
    assert identity["device_model"].startswith("iPhone")
    assert identity["device_id"].startswith("sdk-ios-")
    expected = "sdk-ios-" + hashlib.sha256((identity["id"] + identity["serial"]).encode()).hexdigest()[:32]
    assert identity["device_id"] == expected
    assert identity.keys() >= IOS_REQUIRED_FIELDS
    assert "app_macr_ios_sdk" in identity["makeflags"]
    assert "IS_IOS=y" in identity["makeflags"]


@pytest.mark.parametrize("field", sorted(MAC_REQUIRED_FIELDS))
def test_macos_validation_rejects_each_missing_wire_field(field):
    identity = earnapp_identity.generate_identity(f"mac-missing-{field.replace('_', '-')}", "macos")
    identity.pop(field)
    with pytest.raises(ValueError, match="missing"):
        earnapp_identity.validate_identity(identity, "macos")


@pytest.mark.parametrize("field", sorted(IOS_REQUIRED_FIELDS))
def test_ios_validation_rejects_each_missing_wire_field(field):
    identity = earnapp_identity.generate_identity(f"ios-missing-{field.replace('_', '-')}", "ios")
    identity.pop(field)
    with pytest.raises(ValueError, match="missing"):
        earnapp_identity.validate_identity(identity, "ios")


def test_generate_ubuntu_identity_is_stable_shape_and_unique():
    first = earnapp_identity.generate_identity("node-ubuntu-a", "ubuntu")
    second = earnapp_identity.generate_identity("node-ubuntu-b", "ubuntu")

    earnapp_identity.validate_identity(first, "ubuntu")
    assert first["platform"] == "ubuntu"
    assert first["device_id"].startswith("sdk-node-")
    assert first["machine_id"] != second["machine_id"]


def test_identity_profile_round_trip_supports_mac_and_ios_without_secrets():
    for platform in ("macos", "ios"):
        identity = earnapp_identity.generate_identity(f"roundtrip-{platform}", platform)
        encrypted = earnapp_identity.encrypt_profile(identity)
        restored = earnapp_identity.decrypt_profile(encrypted, platform)
        assert restored == identity
        assert "oauth-refresh-token" not in json.dumps(restored)
        assert "xsrf-token" not in json.dumps(restored)


def test_unknown_platform_and_cross_platform_validation_fail_closed():
    with pytest.raises(ValueError, match="platform"):
        earnapp_identity.generate_identity("node-invalid", "android")
    mac = earnapp_identity.generate_identity("node-mac", "macos")
    with pytest.raises(ValueError, match="iOS"):
        earnapp_identity.validate_identity(mac, "ios")


def test_persisted_identity_profile_is_stable_and_platform_immutable(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            first = await earnapp_identity.ensure_identity_profile("persisted-ios-node", "ios")
            retry = await earnapp_identity.ensure_identity_profile("persisted-ios-node", "ios")
            other = await earnapp_identity.ensure_identity_profile("persisted-ios-other", "ios")

            assert retry == first
            assert other["device_id"] != first["device_id"]
            assert earnapp_identity.decrypt_profile(first["value"], "ios")["device_id"] == first["device_id"]
            with pytest.raises(ValueError, match="platform"):
                await earnapp_identity.ensure_identity_profile("persisted-ios-node", "macos")

    asyncio.run(run())
