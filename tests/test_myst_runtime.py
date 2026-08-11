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

    myst_runtime.apply_direct_wallet(container, wallet, dashboard_password="pw", mmn_api_key="mmn-key")

    container.stop.assert_called_once()
    container.put_archive.assert_called_once()
    assert container.put_archive.call_args.args[0] == "/var/lib/mysterium-node"
    container.restart.assert_called_once()
    execs = [" ".join(call.args[0]) for call in container.exec_run.call_args_list]
    assert any("auth/password" in cmd for cmd in execs)
    assert any("myst cli mmn" in cmd for cmd in execs)

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
