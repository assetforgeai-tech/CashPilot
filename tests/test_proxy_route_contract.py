from pathlib import Path

ROOT = Path(__file__).parents[1]
ROUTE_CONTRACT = ROOT / "docs" / "architecture" / "proxy-route-contract.md"
STATE_MACHINE = ROOT / "docs" / "architecture" / "proxy-pool-state-machine.md"
POLICY_MATRIX = ROOT / "docs" / "architecture" / "provider-policy-matrix.md"


def test_route_contract_freezes_lane_and_watchdog_boundaries():
    text = ROUTE_CONTRACT.read_text(encoding="utf-8")
    for phrase in (
        "Direct-only",
        "Hybrid",
        "Proxy-only",
        "Proxy Pool Probe",
        "Route watchdog",
        "ACK",
        "observed egress",
        "no direct fallback",
    ):
        assert phrase in text
    assert "must not release a lease" in text
    assert "must not mark an upstream proxy dead" in text
    assert "EarnApp" in text and "Pawns" in text


def test_proxy_pool_state_machine_freezes_thresholds_and_recovery_rules():
    text = STATE_MACHINE.read_text(encoding="utf-8")
    for state in ("unknown", "alive", "suspect", "dead", "rotation_pending", "quarantined"):
        assert f"`{state}`" in text
    for phrase in ("30 seconds", "90 seconds", "three consecutive", "1,024", "500", "inconclusive", "old lease", "CAS"):
        assert phrase in text


def test_provider_policy_matrix_freezes_all_provider_lanes():
    text = POLICY_MATRIX.read_text(encoding="utf-8")
    expected_groups = {
        "Direct-only": ("Mysterium", "NKN"),
        "Hybrid": (
            "EarnFM",
            "ProxyBase",
            "ProxyBase.xyz",
            "ProxyRack",
            "Repocket",
            "Spide",
            "TraffMonetizer",
            "URNetwork",
        ),
        "Proxy-only": ("EarnApp", "IPRoyal Pawns", "PacketStream", "Proxies.sx", "UpRock", "Wipter"),
    }
    for group, providers in expected_groups.items():
        assert group in text
        for provider in providers:
            assert provider in text
    assert "EarnApp and Pawns/IPRoyal allocator lanes never share" in text
    assert "Mysterium/NKN never receive proxy leases" in text
    assert "insufficient proxy capacity" in text
    assert "silent count reduction" in text
