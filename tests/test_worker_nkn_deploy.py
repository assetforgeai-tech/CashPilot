from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from app import worker_api


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/api/nkn/slots/ipv4-001/deploy", "headers": []})


def _delete_request() -> Request:
    return Request({"type": "http", "method": "DELETE", "path": "/api/nkn/slots/ipv4-001", "headers": []})


def _slot() -> dict[str, object]:
    return {
        "slot_id": "ipv4-001",
        "public_ip": "8.8.8.8",
        "private_ip": "10.20.0.4",
        "interface": "eth0",
        "subnet": "10.20.0.0/24",
        "gateway": "10.20.0.1",
        "docker_network": "cashpilot-direct-ipv4-001",
        "bridge_subnet": "10.253.1.0/24",
        "bridge_gateway": "10.253.1.1",
        "source": "azure_imds",
        "route_ready": True,
    }


def test_worker_nkn_deploy_persists_only_redacted_assignment_state(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    spec = worker_api.NknDeploySpec(
        wallet_id=7,
        wallet_assignment_version=3,
        lease_client_id="worker-a:nkn:ipv4-001",
        wallet_json=json.dumps({"Address": "NKNwalletAddress"}),
        wallet_pswd="password-value",
        beneficiary_address="NKNBeneficiaryAddress",
        runtime_backend="lxd",
        lxd_cpu=2,
        lxd_memory_mib=2048,
    )

    async def run():
        with (
            patch.object(worker_api, "_verify_api_key", return_value=None),
            patch.object(worker_api, "_load_public_ip_slots", return_value=[_slot()]),
            patch.object(
                worker_api.nkn_lxd_runtime,
                "deploy_slot",
                return_value={"container_id": "container-id", "instance_id": "nkn-direct-ipv4-001"},
            ),
        ):
            return await worker_api.api_deploy_nkn_slot(_request(), "ipv4-001", spec)

    response = asyncio.run(run())
    assert response == {
        "status": "deployed",
        "container_id": "container-id",
        "instance_id": "nkn-direct-ipv4-001",
        "slot_id": "ipv4-001",
    }
    saved = json.loads(Path(tmp_path, "nkn-wallets", "ipv4-001.json").read_text(encoding="utf-8"))
    assert saved["wallet_id"] == 7
    assert saved["wallet_assignment_version"] == 3
    assert saved["wallet_address"] == "NKNwalletAddress"
    assert saved["public_ip"] == "8.8.8.8"
    assert saved["last_server_ack_at"] > 0
    assert saved["lease_guard_suspended"] is False
    assert saved["runtime_backend"] == "lxd"
    assert saved["lxd_cpu"] == 2
    assert saved["lxd_memory_mib"] == 2048
    assert "wallet_json" not in saved
    assert "wallet_pswd" not in saved
    assert "password-value" not in json.dumps(saved)


def test_worker_nkn_deploy_forwards_canary_adoption_and_persists_lxd_target(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    spec = worker_api.NknDeploySpec(
        wallet_id=7,
        wallet_assignment_version=3,
        lease_client_id="worker-a:nkn:ipv4-001",
        wallet_json=json.dumps({"Address": "NKNwalletAddress"}),
        wallet_pswd="password-value",
        beneficiary_address="NKNBeneficiaryAddress",
        runtime_backend="lxd",
        lxd_cpu=1,
        lxd_memory_mib=1024,
        adopt_instance="cashpilot-nkn-lxd-canary",
        expected_node_id="a" * 64,
    )

    async def run():
        with (
            patch.object(worker_api, "_verify_api_key", return_value=None),
            patch.object(worker_api, "_load_public_ip_slots", return_value=[_slot()]),
            patch.object(
                worker_api.nkn_lxd_runtime,
                "deploy_slot",
                return_value={"container_id": "cashpilot-nkn-ipv4-001", "instance_id": "cashpilot-nkn-ipv4-001"},
            ) as deploy,
        ):
            response = await worker_api.api_deploy_nkn_slot(_request(), "ipv4-001", spec)
        return response, deploy

    response, deploy = asyncio.run(run())
    assert response["instance_id"] == "cashpilot-nkn-ipv4-001"
    assert deploy.call_args.kwargs["adopt_instance"] == "cashpilot-nkn-lxd-canary"
    assert deploy.call_args.kwargs["expected_node_id"] == "a" * 64
    saved = json.loads(Path(tmp_path, "nkn-wallets", "ipv4-001.json").read_text(encoding="utf-8"))
    assert saved["instance_id"] == "cashpilot-nkn-ipv4-001"
    assert saved["runtime_backend"] == "lxd"


@pytest.mark.parametrize(
    "overrides",
    [
        {"adopt_instance": "cashpilot-nkn-lxd-canary"},
        {"expected_node_id": "a" * 64},
        {
            "runtime_backend": "docker",
            "adopt_instance": "cashpilot-nkn-lxd-canary",
            "expected_node_id": "a" * 64,
        },
    ],
)
def test_worker_nkn_deploy_rejects_incomplete_or_non_lxd_adoption(overrides):
    with pytest.raises(ValidationError):
        worker_api.NknDeploySpec(
            wallet_id=7,
            wallet_assignment_version=3,
            lease_client_id="worker-a:nkn:ipv4-001",
            wallet_json=json.dumps({"Address": "NKNwalletAddress"}),
            wallet_pswd="password-value",
            beneficiary_address="NKNBeneficiaryAddress",
            **overrides,
        )


def test_nkn_state_path_is_normalized_and_confined_to_state_root(tmp_path, monkeypatch):
    (tmp_path / "state").mkdir()
    raw_root = tmp_path / "state" / ".." / "state"
    monkeypatch.setattr(worker_api, "_nkn_state_dir", lambda: raw_root)

    path = worker_api._nkn_state_path("ipv4-001")

    assert path == (tmp_path / "state" / "ipv4-001.json").resolve()
    assert path.parent == raw_root.resolve()


def test_worker_nkn_deploy_rejects_unknown_slot_without_touching_docker():
    spec = worker_api.NknDeploySpec(
        wallet_id=7,
        wallet_assignment_version=3,
        lease_client_id="worker-a:nkn:ipv4-999",
        wallet_json=json.dumps({"Address": "NKNwalletAddress"}),
        wallet_pswd="password-value",
        beneficiary_address="NKNBeneficiaryAddress",
    )

    async def run():
        with (
            patch.object(worker_api, "_verify_api_key", return_value=None),
            patch.object(worker_api, "_load_public_ip_slots", return_value=[_slot()]),
            patch.object(worker_api.nkn_runtime, "deploy_slot") as deploy,
        ):
            response = await worker_api.api_deploy_nkn_slot(_request(), "ipv4-999", spec)
        return response, deploy

    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        asyncio.run(run())
    assert exc.value.status_code == 404


def test_worker_nkn_remove_deletes_state_only_after_assignment_guarded_remove(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    state = {
        "slot_id": "ipv4-001",
        "instance_id": "nkn-direct-ipv4-001",
        "wallet_id": 7,
        "wallet_assignment_version": 3,
        "lease_client_id": "worker-a:nkn:ipv4-001",
    }
    worker_api._save_nkn_wallet_state("ipv4-001", state)
    spec = worker_api.NknRemoveSpec(
        wallet_id=7,
        wallet_assignment_version=3,
        lease_client_id="worker-a:nkn:ipv4-001",
    )

    async def run():
        with (
            patch.object(worker_api, "_verify_api_key", return_value=None),
            patch.object(worker_api.nkn_runtime, "remove_slot", return_value={"deleted_volume": True}),
            patch.object(worker_api.orchestrator, "_get_client", return_value=MagicMock()),
        ):
            return await worker_api.api_remove_nkn_slot(_delete_request(), "ipv4-001", spec)

    result = asyncio.run(run())
    assert result["status"] == "removed"
    assert not Path(tmp_path, "nkn-wallets", "ipv4-001.json").exists()


def test_worker_nkn_remove_rejects_a_stale_assignment_without_deleting_state(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    worker_api._save_nkn_wallet_state(
        "ipv4-001",
        {
            "wallet_id": 7,
            "wallet_assignment_version": 3,
            "lease_client_id": "worker-a:nkn:ipv4-001",
        },
    )
    spec = worker_api.NknRemoveSpec(
        wallet_id=7,
        wallet_assignment_version=2,
        lease_client_id="worker-a:nkn:ipv4-001",
    )

    import pytest
    from fastapi import HTTPException

    with patch.object(worker_api, "_verify_api_key", return_value=None), pytest.raises(HTTPException) as exc:
        asyncio.run(worker_api.api_remove_nkn_slot(_delete_request(), "ipv4-001", spec))
    assert exc.value.status_code == 409
    assert Path(tmp_path, "nkn-wallets", "ipv4-001.json").exists()


def test_nkn_runtime_suspend_and_resume_are_assignment_guarded():
    from app import nkn_runtime

    labels = {
        "cashpilot.nkn.wallet_id": "7",
        "cashpilot.nkn.wallet_assignment_version": "3",
        "cashpilot.nkn.lease_client_id": "worker-a:nkn:ipv4-001",
    }
    container = MagicMock(labels=labels, status="running")
    client = MagicMock()
    client.containers.get.return_value = container

    stopped = nkn_runtime.suspend_slot(
        "ipv4-001",
        wallet_id=7,
        wallet_assignment_version=3,
        lease_client_id="worker-a:nkn:ipv4-001",
        client=client,
    )
    assert stopped["status"] == "stopped"
    container.update.assert_called_once_with(restart_policy={"Name": "no"})
    container.stop.assert_called_once_with(timeout=30)
    container.remove.assert_not_called()
    client.volumes.get.assert_not_called()

    container.status = "exited"
    resumed = nkn_runtime.resume_slot(
        "ipv4-001",
        wallet_id=7,
        wallet_assignment_version=3,
        lease_client_id="worker-a:nkn:ipv4-001",
        client=client,
    )
    assert resumed["status"] == "running"
    assert container.update.call_args_list[-1].kwargs == {"restart_policy": {"Name": "always"}}
    container.start.assert_called_once_with()


def test_nkn_runtime_suspend_rejects_a_different_assignment():
    import pytest

    from app import nkn_runtime

    container = MagicMock(
        labels={
            "cashpilot.nkn.wallet_id": "8",
            "cashpilot.nkn.wallet_assignment_version": "3",
            "cashpilot.nkn.lease_client_id": "worker-b:nkn:ipv4-001",
        },
        status="running",
    )
    client = MagicMock()
    client.containers.get.return_value = container

    with pytest.raises(nkn_runtime.NknAssignmentConflict):
        nkn_runtime.suspend_slot(
            "ipv4-001",
            wallet_id=7,
            wallet_assignment_version=3,
            lease_client_id="worker-a:nkn:ipv4-001",
            client=client,
        )
    container.stop.assert_not_called()
