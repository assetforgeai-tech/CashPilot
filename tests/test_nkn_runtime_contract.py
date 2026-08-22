from __future__ import annotations

import io
import json
import tarfile
from unittest.mock import MagicMock

import pytest

from app import catalog, nkn_runtime, provider_runtime

BENEFICIARY = "NKNFrqAuM6mSv79sjCMBBn4o1d7Bh8TfGqSD"
WALLET_ADDRESS = "NKNa31NDoKZop91uJ8V6F863HaD1H3Jebikq"


def _wallet_json() -> str:
    return json.dumps(
        {
            "Version": 2,
            "IV": "iv",
            "MasterKey": "mk",
            "SeedEncrypted": "seed",
            "Address": WALLET_ADDRESS,
            "Scrypt": {"Salt": "salt", "N": 32768, "R": 8, "P": 1},
        },
        separators=(",", ":"),
    )


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


def _assignment() -> dict[str, object]:
    return {
        "wallet_id": 7,
        "wallet_assignment_version": 3,
        "lease_client_id": "worker-a:nkn:ipv4-001",
        "wallet_json": _wallet_json(),
        "wallet_pswd": "password-value",
        "beneficiary_address": BENEFICIARY,
    }


def test_nkn_catalog_is_official_direct_only_and_hard_limited():
    catalog.load_services()
    service = catalog.get_service("nkn")

    assert service is not None
    assert provider_runtime.supported_modes("nkn") == {"direct"}
    assert service["docker"]["image"] == "nknorg/nkn:latest"
    assert service["egress"]["mode"] == "direct"
    assert service["docker"]["resources"] == {"mem_limit": "1g", "nano_cpus": 1_000_000_000}
    assert service["docker"]["ports"] == []
    assert service["docker"]["critical_volumes"][0]["target"] == "/nkn/data"
    assert service["deploy"]["automation"] == "direct_wallet_slots"
    assert {field["key"] for field in service["deploy"]["credentials"]} == {"beneficiary_address"}
    assert {field["key"] for field in service["collector"]["credentials"]} == {"beneficiary_address"}


def test_seed_archive_preserves_the_exact_tested_config_and_wallet_files():
    raw = nkn_runtime.seed_archive(_wallet_json(), "password-value", BENEFICIARY)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        names = sorted(archive.getnames())
        assert names == ["config.json", "wallet.json", "wallet.pswd"]
        config = json.load(archive.extractfile("config.json"))
        wallet_json = archive.extractfile("wallet.json").read().decode()
        wallet_pswd = archive.extractfile("wallet.pswd").read().decode()
        assert archive.getmember("wallet.json").mode == 0o600
        assert archive.getmember("wallet.pswd").mode == 0o600
    assert config == {
        "BeneficiaryAddr": BENEFICIARY,
        "beneficiaryAddr": BENEFICIARY,
        "SyncMode": "light",
        "PasswordFile": "wallet.pswd",
    }
    assert wallet_json == _wallet_json()
    assert wallet_pswd == "password-value"


def test_deploy_slot_hardcodes_network_ports_resources_and_redacted_labels():
    client = MagicMock()
    client.containers.get.side_effect = nkn_runtime.NotFound("missing")
    client.volumes.get.side_effect = nkn_runtime.NotFound("missing")
    volume = MagicMock()
    volume.attrs = {"Labels": {}}
    client.volumes.create.return_value = volume
    helper = MagicMock()
    client.containers.create.return_value = helper
    main_container = MagicMock(id="container-id")
    client.containers.run.return_value = main_container

    result = nkn_runtime.deploy_slot(_slot(), _assignment(), client=client)

    assert result["container_id"] == "container-id"
    assert result["instance_id"] == "nkn-direct-ipv4-001"
    helper.put_archive.assert_called_once()
    run = client.containers.run.call_args.kwargs
    assert run["image"] == "nknorg/nkn:latest"
    assert run["network"] == "cashpilot-direct-ipv4-001"
    assert run["volumes"] == {"cashpilot-nkn-ipv4-001-data": {"bind": "/nkn/data", "mode": "rw"}}
    assert run["nano_cpus"] == 1_000_000_000
    assert run["mem_limit"] == "1g"
    assert run["restart_policy"] == {"Name": "always"}
    assert run["ports"]["30003/tcp"] == ("10.20.0.4", 30003)
    assert run["ports"]["30005/udp"] == ("10.20.0.4", 30005)
    assert run["labels"]["cashpilot.nkn.wallet_id"] == "7"
    assert run["labels"]["cashpilot.nkn.wallet_assignment_version"] == "3"
    assert "wallet_json" not in json.dumps(run, default=str)
    assert "password-value" not in json.dumps(run, default=str)


def test_deploy_rejects_an_existing_container_with_a_different_wallet_assignment():
    existing = MagicMock()
    existing.labels = {
        "cashpilot.nkn.wallet_id": "6",
        "cashpilot.nkn.wallet_assignment_version": "2",
    }
    client = MagicMock()
    client.containers.get.return_value = existing

    with pytest.raises(nkn_runtime.NknAssignmentConflict):
        nkn_runtime.deploy_slot(_slot(), _assignment(), client=client)

    existing.remove.assert_not_called()
    client.volumes.create.assert_not_called()


def test_route_unready_slot_fails_before_docker_is_touched():
    slot = _slot()
    slot["route_ready"] = False
    client = MagicMock()
    with pytest.raises(ValueError, match="route-ready"):
        nkn_runtime.deploy_slot(slot, _assignment(), client=client)
    client.images.pull.assert_not_called()


def test_deploy_keeps_an_existing_running_assignment_and_does_not_reseed_identity():
    existing = MagicMock()
    existing.id = "existing-container"
    existing.status = "running"
    existing.labels = {
        "cashpilot.nkn.wallet_id": "7",
        "cashpilot.nkn.wallet_assignment_version": "3",
        "cashpilot.nkn.lease_client_id": "worker-a:nkn:ipv4-001",
    }
    client = MagicMock()
    client.containers.get.return_value = existing

    result = nkn_runtime.deploy_slot(_slot(), _assignment(), client=client)

    assert result["container_id"] == "existing-container"
    existing.stop.assert_not_called()
    existing.remove.assert_not_called()
    client.containers.run.assert_not_called()


def test_remove_slot_requires_assignment_and_removes_only_nkn_resources():
    container = MagicMock()
    container.labels = {
        "cashpilot.nkn.wallet_id": "7",
        "cashpilot.nkn.wallet_assignment_version": "3",
        "cashpilot.nkn.lease_client_id": "worker-a:nkn:ipv4-001",
    }
    volume = MagicMock()
    volume.attrs = {"Labels": container.labels}
    client = MagicMock()
    client.containers.get.return_value = container
    client.volumes.get.return_value = volume

    result = nkn_runtime.remove_slot(
        "ipv4-001",
        wallet_id=7,
        wallet_assignment_version=3,
        lease_client_id="worker-a:nkn:ipv4-001",
        client=client,
    )

    assert result["deleted_volume"] is True
    container.stop.assert_called_once()
    container.remove.assert_called_once_with(force=True)
    volume.remove.assert_called_once_with(force=True)


def test_failed_seed_removes_the_new_empty_volume_before_retry():
    client = MagicMock()
    client.containers.get.side_effect = nkn_runtime.NotFound("missing")
    client.volumes.get.side_effect = nkn_runtime.NotFound("missing")
    volume = MagicMock()
    volume.attrs = {"Labels": {}}
    client.volumes.create.return_value = volume
    client.containers.create.side_effect = RuntimeError("seed helper failed")

    with pytest.raises(RuntimeError, match="seed helper failed"):
        nkn_runtime.deploy_slot(_slot(), _assignment(), client=client)

    volume.remove.assert_called_once_with(force=True)
    client.containers.run.assert_not_called()
