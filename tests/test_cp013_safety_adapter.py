"""CP-013 deploy evidence must classify an unsafe proxy route."""

from app.rollout_safety import classify_rollout_result, enrich_rollout_result


def test_missing_probe_is_pending_not_fatal():
    result = enrich_rollout_result(
        {"status": "deployed", "instances": [{"instance_id": "earnfm-proxy-001", "status": "running"}]},
        instances=[
            {
                "instance_id": "earnfm-proxy-001",
                "mode": "proxy",
                "expected_egress_ip": "203.0.113.20",
                "proxy_lease_id": "lease-1",
                "status": "running",
            }
        ],
        probes=[],
    )

    assert result["status"] == "verification_pending"
    assert result["safety"] == {}
    assert result["safety_evidence"]["missing_probes"] == 1
    assert classify_rollout_result(result).stop_round is False


def test_proxy_egress_mismatch_is_fatal():
    result = enrich_rollout_result(
        {"status": "deployed", "instances": [{"instance_id": "earnfm-proxy-001", "status": "running"}]},
        instances=[
            {
                "instance_id": "earnfm-proxy-001",
                "mode": "proxy",
                "expected_egress_ip": "203.0.113.20",
                "proxy_lease_id": "lease-1",
            }
        ],
        probes=[{"instance_id": "earnfm-proxy-001", "probe_ok": True, "observed_egress_ip": "198.51.100.8"}],
    )

    assert result["safety"]["egress_mismatch"] is True


def test_proxy_without_lease_is_fatal_even_when_egress_is_missing():
    result = enrich_rollout_result(
        {"status": "deployed", "instances": [{"instance_id": "earnapp-001", "status": "running"}]},
        instances=[{"instance_id": "earnapp-001", "mode": "proxy"}],
        probes=[
            {
                "instance_id": "earnapp-001",
                "probe_ok": True,
                "observed_egress_ip": "",
            }
        ],
    )

    assert result["safety"]["wrong_lease"] is True
    assert classify_rollout_result(result).code == "wrong_lease"


def test_proxy_lease_must_match_provider_proxy_id():
    result = enrich_rollout_result(
        {"status": "deployed", "instances": [{"instance_id": "earnapp-002", "status": "running"}]},
        instances=[
            {
                "instance_id": "earnapp-002",
                "mode": "proxy",
                "proxy_id": 10,
                "proxy_lease_id": "lease-2",
                "proxy_lease_proxy_id": 11,
                "expected_egress_ip": "198.51.100.11",
            }
        ],
        probes=[
            {
                "instance_id": "earnapp-002",
                "probe_ok": True,
                "observed_egress_ip": "198.51.100.11",
            }
        ],
    )

    assert result["safety"]["wrong_lease"] is True
    assert classify_rollout_result(result).code == "wrong_lease"


def test_missing_authoritative_instance_is_pending_not_success():
    result = enrich_rollout_result(
        {"status": "deployed", "instances": [{"instance_id": "earnfm-proxy-001", "status": "running"}]},
        instances=[],
        probes=[
            {
                "instance_id": "earnfm-proxy-001",
                "probe_ok": True,
                "observed_egress_ip": "198.51.100.8",
            }
        ],
    )

    assert result["status"] == "verification_pending"
    assert result["safety"] == {}
    assert result["safety_evidence"]["missing_instances"] == 1


def test_missing_expected_egress_is_pending_not_success():
    result = enrich_rollout_result(
        {"status": "deployed", "instances": [{"instance_id": "earnfm-direct-001", "status": "running"}]},
        instances=[{"instance_id": "earnfm-direct-001", "mode": "direct"}],
        probes=[
            {
                "instance_id": "earnfm-direct-001",
                "probe_ok": True,
                "observed_egress_ip": "198.51.100.9",
            }
        ],
    )

    assert result["status"] == "verification_pending"
    assert result["safety"] == {}
    assert result["safety_evidence"]["missing_expected_egress"] == 1


def test_missing_probe_does_not_mask_deploy_failure():
    result = enrich_rollout_result(
        {"status": "failed", "failed": 1, "instances": [{"instance_id": "earnfm-001", "status": "running"}]},
        instances=[{"instance_id": "earnfm-001", "mode": "direct", "expected_egress_ip": "198.51.100.10"}],
        probes=[],
    )

    assert result["status"] == "failed"
