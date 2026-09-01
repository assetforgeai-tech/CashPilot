"""Cross-platform EarnApp identity contracts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
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
IOS_REFERENCE_FIELDS = {
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
UBUNTU_REQUIRED_FIELDS = {
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
    assert first["device_id"] != second["device_id"]
    assert first.keys() >= UBUNTU_REQUIRED_FIELDS
    assert first["os_version"] == "22.04.5"
    assert first["release"] == "ubuntu_22.04_x64"
    assert first["appid"] == "node_earnapp.com"
    assert first["ifname"] == "enp2s0"


@pytest.mark.parametrize("field", sorted(UBUNTU_REQUIRED_FIELDS))
def test_ubuntu_validation_rejects_each_missing_profile_field(field):
    identity = earnapp_identity.generate_identity(f"ubuntu-missing-{field.replace('_', '-')}", "ubuntu")
    identity.pop(field)
    with pytest.raises(ValueError, match="invalid|missing"):
        earnapp_identity.validate_identity(identity, "ubuntu")


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


def test_generated_macos_profile_matches_reference_runtime_state_shape():
    identity = earnapp_identity.generate_identity("parity-mac-node", "macos")

    assert set(identity["new_state"]) == {
        "battery_percentage",
        "full_screen",
        "full_screen_ts",
        "idle_state",
        "monitor_power",
        "power_source",
        "session_state",
        "user_io",
    }
    assert isinstance(identity["new_state"]["idle_state"], dict)
    assert identity["new_state"]["session_state"] == "logged"
    assert isinstance(identity["usage"]["app_bytes"], str)
    usage = json.loads(identity["usage"]["app_bytes"])
    assert isinstance(usage, dict)
    assert usage["wifi_connected"] is False


def test_generated_ios_profile_matches_reference_identity_and_state_shape():
    identity = earnapp_identity.generate_identity("parity-ios-node", "ios")

    assert set(identity) >= {
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
    assert identity["new_state"]["session_state"] == "logged"
    assert isinstance(identity["new_state"]["idle_state"], dict)
    usage = json.loads(identity["usage"]["app_bytes"])
    assert isinstance(usage, dict)
    assert usage["wifi_connected"] is True
    assert identity["ua"].startswith("earnapp/1 ")


@pytest.mark.parametrize("field", sorted(IOS_REFERENCE_FIELDS))
def test_new_ios_reference_profile_rejects_each_missing_field(field):
    identity = earnapp_identity.generate_identity(f"ios-reference-missing-{field.replace('_', '-')}", "ios")
    identity.pop(field)

    with pytest.raises(ValueError, match="missing"):
        earnapp_identity.validate_identity(identity, "ios")


def test_generated_ios_profile_keeps_reference_cp_id_and_distinct_container_uuid():
    first = earnapp_identity.generate_identity("parity-ios-container-a", "ios")
    second = earnapp_identity.generate_identity("parity-ios-container-b", "ios")

    assert first["container_uuid"] in first["confdir"]
    assert first["cp_id"] == "ios_com.brd.earnapp"
    assert second["container_uuid"] in second["confdir"]
    assert first["container_uuid"] != second["container_uuid"]
    assert second["cp_id"] == "ios_com.brd.earnapp"


def test_new_mac_and_ios_tracking_ids_are_valid_uuid4_values():
    mac = earnapp_identity.generate_identity("parity-mac-tracking-shape", "macos")
    ios = earnapp_identity.generate_identity("parity-ios-tracking-shape", "ios")

    uuid_shape = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$")
    assert uuid_shape.fullmatch(mac["platform_uuid"])
    assert mac["platform_uuid"][14] == "4"
    assert uuid_shape.fullmatch(ios["identifier_for_vendor"])
    assert ios["identifier_for_vendor"][14] == "4"
    assert uuid_shape.fullmatch(ios["container_uuid"])
    assert ios["container_uuid"][14] == "4"


def test_new_identity_tracking_ids_and_network_ids_are_unique_per_node():
    macs = [earnapp_identity.generate_identity(f"unique-mac-{index}", "macos") for index in range(16)]
    ios_profiles = [earnapp_identity.generate_identity(f"unique-ios-{index}", "ios") for index in range(16)]

    assert len({profile["platform_uuid"] for profile in macs}) == len(macs)
    assert len({profile["serial_material_mac"] for profile in macs}) == len(macs)
    assert len({profile["identifier_for_vendor"] for profile in ios_profiles}) == len(ios_profiles)
    assert len({profile["container_uuid"] for profile in ios_profiles}) == len(ios_profiles)
    assert len({profile["wifi_mac"] for profile in ios_profiles}) == len(ios_profiles)


def test_generated_macos_profile_uses_observed_runtime_value_types_and_ranges():
    identity = earnapp_identity.generate_identity("parity-mac-runtime-values", "macos")
    state = identity["new_state"]

    assert state["battery_percentage"] == -1
    assert state["power_source"] == "AC"
    assert 0 <= state["idle_state"]["cpu_usage"] <= 4
    assert 0 <= state["idle_state"]["mem_usage"] <= 5
    assert 2_806_000 <= state["user_io"] <= 4_000_000
    assert state["full_screen_ts"] > 1_700_000_000_000
    assert set(identity["perf"]) == {"cpu", "cpu_max", "mem", "mem_free", "mem_max"}
    assert all(isinstance(value, str) for value in identity["perf"].values())
    assert identity["timezone"] in {
        "America/Los_Angeles",
        "America/New_York",
        "Europe/Berlin",
        "Europe/London",
    }


def test_generated_ios_profile_uses_observed_runtime_value_types_and_ranges():
    identity = earnapp_identity.generate_identity("parity-ios-runtime-values", "ios")
    state = identity["new_state"]
    usage = json.loads(identity["usage"]["app_bytes"])

    assert state["battery_percentage"] in {38, 52, 67, 81, 94}
    assert state["power_source"] in {"AC", "battery"}
    assert 2 <= state["idle_state"]["cpu_usage"] <= 12
    assert 8 <= state["idle_state"]["mem_usage"] <= 28
    assert usage["battery_level"] == state["battery_percentage"]
    assert usage["using_battery"] is True
    assert set(identity["perf"]) == {"cpu", "cpu_max", "mem", "mem_free", "mem_max"}
    assert all(isinstance(value, str) for value in identity["perf"].values())
