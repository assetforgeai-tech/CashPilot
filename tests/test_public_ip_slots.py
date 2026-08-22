from __future__ import annotations

import json

from app import public_ip_slots


def _addresses(*, private_ips: tuple[str, ...] = ("10.20.0.4",)) -> list[dict[str, object]]:
    return [
        {
            "ifname": "eth0",
            "address": "00:11:22:33:44:55",
            "addr_info": [{"family": "inet", "local": private_ip, "prefixlen": 24} for private_ip in private_ips],
        },
        {
            "ifname": "lo",
            "address": "00:00:00:00:00:00",
            "addr_info": [{"family": "inet", "local": "127.0.0.1", "prefixlen": 8}],
        },
    ]


def _routes() -> list[dict[str, object]]:
    return [
        {"dst": "default", "gateway": "10.20.0.1", "dev": "eth0"},
        {"dst": "10.20.0.0/24", "dev": "eth0", "prefsrc": "10.20.0.4"},
    ]


def _azure_metadata() -> dict[str, object]:
    return {
        "interface": [
            {
                "macAddress": "001122334455",
                "ipv4": {
                    "ipAddress": [
                        {"privateIpAddress": "10.20.0.4", "publicIpAddress": "8.8.8.8"},
                        {"privateIpAddress": "10.20.0.5", "publicIpAddress": "1.1.1.1"},
                    ],
                    "subnet": [{"address": "10.20.0.0", "prefix": "24"}],
                },
            }
        ]
    }


def test_azure_imds_maps_every_public_ip_to_one_stable_route_ready_slot():
    slots = public_ip_slots.discover_slots(_azure_metadata(), _addresses(), _routes())

    assert [slot["public_ip"] for slot in slots] == ["1.1.1.1", "8.8.8.8"]
    assert [slot["slot_id"] for slot in slots] == ["ipv4-001", "ipv4-002"]
    assert slots[0] == {
        "slot_id": "ipv4-001",
        "public_ip": "1.1.1.1",
        "private_ip": "10.20.0.5",
        "interface": "eth0",
        "subnet": "10.20.0.0/24",
        "gateway": "10.20.0.1",
        "docker_network": "cashpilot-direct-ipv4-001",
        "bridge_subnet": "10.253.1.0/24",
        "bridge_gateway": "10.253.1.1",
        "source": "azure_imds",
        "route_ready": True,
    }


def test_existing_slot_ids_survive_metadata_reordering_and_new_addresses():
    previous = [
        {
            "slot_id": "ipv4-007",
            "public_ip": "8.8.8.8",
            "private_ip": "10.20.0.4",
        }
    ]
    metadata = _azure_metadata()
    metadata["interface"][0]["ipv4"]["ipAddress"].reverse()  # type: ignore[index]

    slots = public_ip_slots.discover_slots(metadata, _addresses(), _routes(), previous_slots=previous)

    assert {slot["public_ip"]: slot["slot_id"] for slot in slots} == {
        "1.1.1.1": "ipv4-008",
        "8.8.8.8": "ipv4-007",
    }


def test_single_ip_fallback_requires_one_unambiguous_default_route_address():
    slots = public_ip_slots.discover_slots({}, _addresses(), _routes(), fallback_public_ip="9.9.9.9")
    assert len(slots) == 1
    assert slots[0]["source"] == "single_ip_fallback"
    assert slots[0]["private_ip"] == "10.20.0.4"

    ambiguous = public_ip_slots.discover_slots(
        {},
        _addresses(private_ips=("10.20.0.4", "10.20.0.5")),
        _routes(),
        fallback_public_ip="9.9.9.9",
    )
    assert ambiguous == []


def test_invalid_or_duplicate_public_addresses_are_not_turned_into_slots():
    metadata = _azure_metadata()
    addresses = metadata["interface"][0]["ipv4"]["ipAddress"]  # type: ignore[index]
    addresses.extend(
        [
            {"privateIpAddress": "10.20.0.6", "publicIpAddress": "not-an-ip"},
            {"privateIpAddress": "10.20.0.7", "publicIpAddress": "8.8.8.8"},
            {"privateIpAddress": "10.20.0.8", "publicIpAddress": "10.0.0.8"},
        ]
    )

    slots = public_ip_slots.discover_slots(metadata, _addresses(), _routes())

    assert [slot["public_ip"] for slot in slots] == ["1.1.1.1", "8.8.8.8"]


def test_load_slots_rejects_unversioned_or_malformed_state(tmp_path):
    path = tmp_path / "slots.json"
    path.write_text(
        json.dumps({"version": 1, "slots": public_ip_slots.discover_slots(_azure_metadata(), _addresses(), _routes())})
    )
    assert len(public_ip_slots.load_slots(path)) == 2

    path.write_text(json.dumps({"slots": []}))
    assert public_ip_slots.load_slots(path) == []

    path.write_text("not json")
    assert public_ip_slots.load_slots(path) == []
