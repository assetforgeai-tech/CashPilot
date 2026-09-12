from app.provider_network_audit import validate_provider_egress


def test_direct_lane_requires_matching_observed_egress():
    result = validate_provider_egress("nkn", mode="direct", expected_egress_ip="198.51.100.10", observed_egress_ip="")
    assert result == {"status": "attention", "findings": ["missing observed direct egress"]}


def test_proxy_lane_requires_lease_and_matching_egress():
    result = validate_provider_egress(
        "earnapp", mode="proxy", expected_egress_ip="198.51.100.11", observed_egress_ip="198.51.100.12"
    )
    assert result["status"] == "attention"
    assert "missing proxy lease" in result["findings"]
    assert "proxy egress mismatch" in result["findings"]


def test_hybrid_lane_does_not_allow_implicit_fallback():
    result = validate_provider_egress(
        "earnfm",
        mode="proxy",
        expected_egress_ip="198.51.100.11",
        observed_egress_ip="198.51.100.11",
        proxy_lease_id="lease-1",
        fallback_mode="direct",
    )
    assert result == {"status": "attention", "findings": ["unsafe egress fallback: direct"]}
