from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

from app import worker_api


def test_myst_state_file_round_trips_without_raw_wallet(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    state = {
        "myst_wallet_id": 7,
        "myst_wallet_client_id": "worker-a",
        "myst_wallet_assignment_version": 3,
        "myst_node_identity": "0xnode",
    }
    worker_api._save_myst_wallet_state(state)
    saved = json.loads(Path(tmp_path, "myst-wallet.json").read_text(encoding="utf-8"))
    assert saved["myst_wallet_id"] == 7
    assert "myst_wallet_raw" not in saved


def test_myst_provider_state_includes_registration_status(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))

    async def run():
        worker_api._save_myst_wallet_state(
            {
                "myst_wallet_id": 7,
                "myst_wallet_client_id": "worker-a",
                "myst_wallet_assignment_version": 3,
                "myst_registration_status": "Registered",
                "container_id": "abc",
            }
        )
        return await worker_api._myst_provider_state()

    state = asyncio.run(run())
    assert state["wallet_assignment_version"] == 3
    assert state["evidence"]["registration_status"] == "Registered"

def test_myst_wallet_sync_after_deploy_persists_state_for_worker_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_UI_URL", "https://ui.example")
    monkeypatch.setenv("CASHPILOT_API_KEY", "fleet-key")
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))

    class _Container:
        def exec_run(self, *_args, **_kwargs):
            return type("R", (), {"output": b"Registration Status: Registered\n"})()

    async def run():
        deploy_credentials = {
            "myst_wallet_id": 7,
            "myst_wallet_client_id": "worker-a",
            "myst_wallet_assignment_version": 3,
            "myst_wallet_raw": "{\"address\":\"0x57143ba62ee95ac60abdb0aab1b3fdfe9f4bf5b1\"}",
        }
        with patch.object(worker_api.orchestrator, "_find_container", return_value=_Container()):
            await worker_api._sync_myst_wallet_after_deploy(deploy_credentials, "container-id")

    asyncio.run(run())
    saved = json.loads(Path(tmp_path, "myst-wallet.json").read_text(encoding="utf-8"))
    assert saved["myst_wallet_id"] == 7
    assert saved["myst_registration_status"] == "Registered"
    assert "myst_wallet_raw" not in saved

def test_myst_sync_after_deploy_uses_worker_heartbeat_only(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))

    async def run():
        await worker_api._sync_myst_wallet_after_deploy(
            {
                "myst_wallet_id": 7,
                "myst_wallet_client_id": "worker-a",
                "myst_wallet_assignment_version": 3,
                "myst_wallet_raw": "{\"address\":\"0x57143ba62ee95ac60abdb0aab1b3fdfe9f4bf5b1\"}",
            },
            "container-id",
        )

    asyncio.run(run())
    saved = json.loads(Path(tmp_path, "myst-wallet.json").read_text(encoding="utf-8"))
    assert saved["myst_wallet_id"] == 7

def test_myst_provider_state_returns_public_ip_guard_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))

    async def run():
        worker_api._save_myst_wallet_state(
            {
                "myst_wallet_id": 7,
                "myst_wallet_client_id": "worker-a",
                "myst_wallet_assignment_version": 3,
                "myst_wallet_address": "0x57143ba62ee95ac60abdb0aab1b3fdfe9f4bf5b1",
                "myst_registration_status": "Registered",
                "myst_public_ip": "8.8.8.8",
            }
        )
        return await worker_api._myst_provider_state()

    state = asyncio.run(run())
    assert state["evidence"]["public_ip"] == "8.8.8.8"
