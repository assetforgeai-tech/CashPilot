from __future__ import annotations

import io
import json
import tarfile
from unittest.mock import MagicMock, patch

from app import myst_runtime, orchestrator

RAW_WALLET = json.dumps({"address": "0x57143ba62ee95ac60abdb0aab1b3fdfe9f4bf5b1", "crypto": {}})
RAW_WALLET_BARE_ADDRESS = json.dumps({"address": "57143ba62ee95ac60abdb0aab1b3fdfe9f4bf5b1", "crypto": {}})

def _tar_names(blob: bytes) -> set[str]:
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r") as tf:
        return set(tf.getnames())

def test_myst_state_archive_contains_wallet_remember_and_mmn_config():
    blob = myst_runtime.state_archive(RAW_WALLET, mmn_api_key="mmn-key")
    names = _tar_names(blob)

    assert "keystore/remember.json" in names
    assert "config-mainnet.toml" in names
    assert any(name.startswith("keystore/UTC--") for name in names)


def test_wallet_address_accepts_myst_keystore_bare_hex_address():
    assert myst_runtime.wallet_address(RAW_WALLET_BARE_ADDRESS) == "0x57143ba62ee95ac60abdb0aab1b3fdfe9f4bf5b1"

def test_myst_state_archive_refuses_wallet_without_address():
    try:
        myst_runtime.state_archive("not-json", mmn_api_key="mmn-key")
    except ValueError as exc:
        assert "address" in str(exc)
    else:
        raise AssertionError("expected invalid wallet to fail")

def test_apply_direct_wallet_stops_patches_restarts_sets_password_and_mmn():
    container = MagicMock()
    wallet = {"raw_wallet": RAW_WALLET, "wallet_assignment_version": 3}
    client = MagicMock()

    with patch.object(myst_runtime.docker, "from_env", return_value=client):
        myst_runtime.apply_direct_wallet(container, wallet, dashboard_password="pw", mmn_api_key="mmn-key")

    container.stop.assert_called_once()
    container.put_archive.assert_called_once()
    assert container.put_archive.call_args.args[0] == "/var/lib/mysterium-node"
    container.restart.assert_called_once()
    execs = [" ".join(call.args[0]) for call in container.exec_run.call_args_list]
    assert any("myst cli mmn" in cmd for cmd in execs)
    client.containers.run.assert_called_once()
    helper = client.containers.run.call_args.kwargs
    assert helper["image"] == "curlimages/curl:8.10.1"
    assert helper["network_mode"] == "host"
    assert helper["environment"] == {"NEW_PASSWORD": "pw"}
    assert "oldPassword" in helper["command"][2]
    assert "newPassword" in helper["command"][2]
    assert 'if [ "$old" = "$NEW_PASSWORD" ]; then exit 0; fi' in helper["command"][2]

def test_apply_direct_wallet_keeps_deploy_alive_when_password_reset_fails():
    container = MagicMock()
    with patch.object(myst_runtime.docker, "from_env") as docker_from_env:
        docker_from_env.return_value.containers.run.side_effect = myst_runtime.docker.errors.ContainerError(
            container="curl",
            exit_status=22,
            command="curl",
            image="curlimages/curl",
            stderr=b"401",
        )

        address = myst_runtime.apply_direct_wallet(container, {"raw_wallet": RAW_WALLET}, dashboard_password="pw", mmn_api_key="mmn")

    assert address == "0x57143ba62ee95ac60abdb0aab1b3fdfe9f4bf5b1"
    container.exec_run.assert_any_call(["sh", "-lc", "myst cli mmn 'mmn' >/dev/null 2>&1 || true"])

def test_registration_status_parses_myst_cli_output():
    container = MagicMock()
    container.exec_run.return_value = MagicMock(output=b"Registration Status: Registered\nBalance: 0.1 MYST\n")

    assert myst_runtime.registration_status(container, "0xabc") == "Registered"

def test_deploy_raw_applies_myst_wallet_after_container_create():
    client = MagicMock()
    client.containers.get.side_effect = orchestrator.NotFound("nope")
    container = MagicMock(short_id="abc123", id="container-id")
    client.containers.run.return_value = container

    with (
        patch.object(orchestrator, "_get_client", return_value=client),
        patch.object(orchestrator.myst_runtime, "apply_direct_wallet") as apply_wallet,
    ):
        orchestrator.deploy_raw(
            slug="mysterium",
            image="img:1",
            deploy_credentials={
                "myst_wallet_raw": RAW_WALLET,
                "myst_dashboard_password": "pw",
                "myst_mmn_api_key": "mmn-key",
            },
        )

    apply_wallet.assert_called_once()

def test_deploy_raw_applies_myst_wallet_for_direct_instance_slug():
    client = MagicMock()
    client.containers.get.side_effect = orchestrator.NotFound("nope")
    container = MagicMock(short_id="abc123", id="container-id")
    client.containers.run.return_value = container

    with (
        patch.object(orchestrator, "_get_client", return_value=client),
        patch.object(orchestrator.myst_runtime, "apply_direct_wallet") as apply_wallet,
    ):
        orchestrator.deploy_raw(
            slug="mysterium-direct",
            provider_slug="mysterium",
            image="img:1",
            deploy_credentials={
                "myst_wallet_raw": RAW_WALLET,
                "myst_dashboard_password": "pw",
                "myst_mmn_api_key": "mmn-key",
            },
        )

    apply_wallet.assert_called_once()
