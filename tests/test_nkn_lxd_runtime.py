from __future__ import annotations

from unittest.mock import patch

from app import nkn_lxd_runtime


def _slot() -> dict[str, object]:
    return {
        "slot_id": "ipv4-001",
        "public_ip": "8.8.8.8",
        "private_ip": "10.20.0.4",
        "route_ready": True,
    }


def _assignment() -> dict[str, object]:
    return {
        "wallet_id": 7,
        "wallet_assignment_version": 3,
        "lease_client_id": "worker-a:nkn:ipv4-001",
        "wallet_json": '{"Address":"NKNwalletAddress"}',
        "wallet_pswd": "password-value",
        "beneficiary_address": "NKNBeneficiaryAddress",
    }


def test_lxd_deploy_sends_slot_assignment_and_hard_limits_without_returning_secrets():
    with patch.object(
        nkn_lxd_runtime, "_request", return_value={"instance_id": "cashpilot-nkn-w7-ipv4-001"}
    ) as request:
        result = nkn_lxd_runtime.deploy_slot(
            _slot(),
            _assignment(),
            settings={"cpu": 2, "memory_mib": 2048},
        )

    assert result["instance_id"] == "cashpilot-nkn-w7-ipv4-001"
    payload = request.call_args.kwargs["payload"]
    assert payload["lxd_cpu"] == 2
    assert payload["lxd_memory_mib"] == 2048
    assert payload["wallet_json"] == '{"Address":"NKNwalletAddress"}'
    assert "password-value" not in str(result)


def test_lxd_deploy_can_forward_the_exact_canary_adoption_guard():
    with patch.object(nkn_lxd_runtime, "_request", return_value={"instance_id": "cashpilot-nkn-ipv4-001"}) as request:
        nkn_lxd_runtime.deploy_slot(
            _slot(),
            _assignment(),
            settings={"cpu": 1, "memory_mib": 1024},
            adopt_instance="cashpilot-nkn-lxd-canary",
            expected_node_id="a" * 64,
        )

    payload = request.call_args.kwargs["payload"]
    assert payload["adopt_instance"] == "cashpilot-nkn-lxd-canary"
    assert payload["expected_node_id"] == "a" * 64


def test_lxd_deploy_forwards_only_redacted_snapshot_contract():
    snapshot = {
        "manifest": {
            "schema_version": 1,
            "provider": "nkn",
            "network": "mainnet",
            "archive_key": "nkn/chaindb/snapshots/1-20260823T120000Z-" + "a" * 64 + ".tar.zst",
            "sha256": "a" * 64,
            "size_bytes": 123,
            "block_height": 1,
            "created_at": "2026-08-23T12:00:00Z",
            "image": "nknorg/nkn:latest",
            "chain_db_root": "ChainDB",
        },
        "archive_url": "https://example.invalid/signed-object",
        "prefix": "nkn/chaindb",
        "max_age_seconds": 48 * 60 * 60,
    }
    with patch.object(nkn_lxd_runtime, "_request", return_value={"instance_id": "nkn"}) as request:
        nkn_lxd_runtime.deploy_slot(_slot(), _assignment(), settings={"cpu": 1, "memory_mib": 1024}, snapshot=snapshot)
    payload = request.call_args.kwargs["payload"]
    assert payload["chaindb_snapshot"] == snapshot
    assert "wallet_pswd" in payload
    assert "secret" not in str(payload["chaindb_snapshot"])


def test_lxd_snapshot_deploy_uses_extended_socket_timeout():
    snapshot = {
        "manifest": {"archive_key": "nkn/chaindb/snapshots/1-20260823T120000Z-" + "a" * 64 + ".tar.zst"},
        "archive_url": "https://example.invalid/signed-object",
        "prefix": "nkn/chaindb",
        "max_age_seconds": 48 * 60 * 60,
    }
    with patch.object(nkn_lxd_runtime, "_request", return_value={"instance_id": "nkn"}) as request:
        nkn_lxd_runtime.deploy_slot(_slot(), _assignment(), settings={"cpu": 1, "memory_mib": 1024}, snapshot=snapshot)
    assert request.call_args.kwargs["timeout"] == 6 * 60 * 60


def test_lxd_lifecycle_requests_are_assignment_cas_scoped():
    with patch.object(nkn_lxd_runtime, "_request", return_value={"status": "ok"}) as request:
        nkn_lxd_runtime.suspend_slot(
            "ipv4-001",
            wallet_id=7,
            wallet_assignment_version=3,
            lease_client_id="worker-a:nkn:ipv4-001",
        )
        nkn_lxd_runtime.resume_slot(
            "ipv4-001",
            wallet_id=7,
            wallet_assignment_version=3,
            lease_client_id="worker-a:nkn:ipv4-001",
        )
        nkn_lxd_runtime.remove_slot(
            "ipv4-001",
            wallet_id=7,
            wallet_assignment_version=3,
            lease_client_id="worker-a:nkn:ipv4-001",
        )

    assert [call.args[:2] for call in request.call_args_list] == [
        ("POST", "/v1/slots/ipv4-001/suspend"),
        ("POST", "/v1/slots/ipv4-001/resume"),
        ("DELETE", "/v1/slots/ipv4-001"),
    ]


def test_lxd_evidence_is_redacted_and_preserves_online_fields():
    with patch.object(
        nkn_lxd_runtime,
        "_request",
        return_value={"running": True, "online": True, "sync_state": "PERSIST_FINISHED", "node_id": "node"},
    ):
        evidence = nkn_lxd_runtime.node_evidence({"slot_id": "ipv4-001", "wallet_pswd": "secret"})

    assert evidence["online"] is True
    assert evidence["sync_state"] == "PERSIST_FINISHED"
    assert "secret" not in str(evidence)
