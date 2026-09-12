from app.provider_network_audit import validate_provider_egress, validate_provider_network_evidence


def test_direct_lane_requires_matching_observed_egress():
    result = validate_provider_egress("nkn", mode="direct", expected_egress_ip="198.51.100.10", observed_egress_ip="")
    assert result == {"status": "attention", "findings": ["missing observed direct egress"]}


def test_each_lane_requires_authoritative_expected_egress():
    direct = validate_provider_egress("nkn", mode="direct", expected_egress_ip="", observed_egress_ip="198.51.100.10")
    proxy = validate_provider_egress(
        "earnapp", mode="proxy", expected_egress_ip="", observed_egress_ip="198.51.100.10", proxy_lease_id="lease-1"
    )
    assert direct["findings"] == ["missing expected direct egress"]
    assert proxy["findings"] == ["missing expected proxy egress"]


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


def test_network_evidence_requires_dns_isolation_and_ipv6_udp_blocking():
    result = validate_provider_network_evidence(mode="proxy", dns_via_proxy=True, ipv6_blocked=True, udp_blocked=True)
    assert result == {"status": "pass", "findings": []}


def test_network_evidence_fails_closed_on_missing_or_leaking_controls():
    result = validate_provider_network_evidence(mode="proxy", dns_via_proxy=None, ipv6_blocked=False, udp_blocked=None)
    assert result["status"] == "attention"
    assert "dns_isolation_unverified" in result["findings"]
    assert "ipv6_not_blocked" in result["findings"]
    assert "udp_isolation_unverified" in result["findings"]
