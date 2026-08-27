from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app import database, main, worker_api


def _body():
    return main.WorkerHeartbeat(
        name="worker-a",
        client_id="worker-a",
        provider_states={
            "nkn": {
                "instances": [
                    {
                        "slot_id": "ipv4-001",
                        "instance_id": "nkn-direct-ipv4-001",
                        "wallet_id": 7,
                        "wallet_assignment_version": 3,
                        "lease_client_id": "worker-a:nkn:ipv4-001",
                        "node_identity": "NKNnode",
                        "runtime_status": "running",
                        "public_ip": "8.8.8.8",
                        "evidence": {"sync_state": "PERSIST_FINISHED", "online": True},
                    }
                ]
            }
        },
    )


def test_nkn_heartbeat_syncs_each_instance_with_cas_and_rejects_secrets():
    async def run():
        def discard(coro):
            coro.close()

        with (
            patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
            patch.object(database, "upsert_worker", AsyncMock(return_value=11)),
            patch.object(database, "sync_nkn_wallet_runtime", AsyncMock(return_value=True)) as sync,
            patch.object(database, "confirm_worker_key", AsyncMock()),
            patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
            patch.object(main, "_spawn", side_effect=discard),
            patch.object(main.metrics, "record_heartbeat"),
        ):
            response = await main.api_worker_heartbeat(
                type("Request", (), {"headers": {"authorization": "Bearer key"}})(), _body()
            )
        assert response["status"] == "ok"
        assert response["nkn_assignment_acks"] == [
            {
                "slot_id": "ipv4-001",
                "wallet_id": 7,
                "wallet_assignment_version": 3,
                "lease_client_id": "worker-a:nkn:ipv4-001",
            }
        ]
        args, kwargs = sync.await_args
        assert args == (7, "worker-a:nkn:ipv4-001")
        assert kwargs["wallet_assignment_version"] == 3
        assert kwargs["public_ip"] == "8.8.8.8"
        assert kwargs["evidence"]["online"] is True
        assert "wallet_json" not in json.dumps(kwargs)
        assert "wallet_pswd" not in json.dumps(kwargs)

    asyncio.run(run())


def test_worker_ack_resumes_a_locally_suspended_nkn_assignment(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    assignment = {
        "slot_id": "ipv4-001",
        "instance_id": "nkn-direct-ipv4-001",
        "wallet_id": 7,
        "wallet_assignment_version": 3,
        "lease_client_id": "worker-a:nkn:ipv4-001",
        "lease_guard_suspended": True,
        "last_server_ack_at": 100.0,
    }
    worker_api._save_nkn_wallet_state("ipv4-001", assignment)
    client = type("Client", (), {"close": lambda self: None})()

    async def run():
        with (
            patch.object(worker_api.orchestrator, "_get_client", return_value=client),
            patch.object(worker_api.nkn_runtime, "resume_slot", return_value={"status": "running"}) as resume,
        ):
            await worker_api._reconcile_nkn_assignment_acks([assignment], acknowledged_at=1_000.0)
        resume.assert_called_once_with(
            "ipv4-001",
            wallet_id=7,
            wallet_assignment_version=3,
            lease_client_id="worker-a:nkn:ipv4-001",
            client=client,
        )

    asyncio.run(run())
    saved = json.loads(Path(tmp_path, "nkn-wallets", "ipv4-001.json").read_text(encoding="utf-8"))
    assert saved["last_server_ack_at"] == 1_000.0
    assert saved["lease_guard_suspended"] is False
    assert saved["runtime_status"] == "running"


def test_worker_lease_guard_suspends_nkn_after_fifteen_minutes_without_deleting_state(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    assignment = {
        "slot_id": "ipv4-001",
        "instance_id": "nkn-direct-ipv4-001",
        "wallet_id": 7,
        "wallet_assignment_version": 3,
        "lease_client_id": "worker-a:nkn:ipv4-001",
        "last_server_ack_at": 100.0,
    }
    worker_api._save_nkn_wallet_state("ipv4-001", assignment)
    client = type("Client", (), {"close": lambda self: None})()

    async def run():
        with (
            patch.object(worker_api.orchestrator, "_get_client", return_value=client),
            patch.object(worker_api.nkn_runtime, "suspend_slot", return_value={"status": "stopped"}) as suspend,
        ):
            await worker_api._enforce_nkn_lease_guard(now=1_000.0)
        suspend.assert_called_once_with(
            "ipv4-001",
            wallet_id=7,
            wallet_assignment_version=3,
            lease_client_id="worker-a:nkn:ipv4-001",
            client=client,
        )

    asyncio.run(run())
    state_path = Path(tmp_path, "nkn-wallets", "ipv4-001.json")
    assert state_path.exists()
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["lease_guard_suspended"] is True
    assert saved["runtime_status"] == "lease_guard_suspended"
    assert saved["last_server_ack_at"] == 100.0


def test_worker_lease_guard_does_not_suspend_before_its_local_deadline(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    worker_api._save_nkn_wallet_state(
        "ipv4-001",
        {
            "slot_id": "ipv4-001",
            "wallet_id": 7,
            "wallet_assignment_version": 3,
            "lease_client_id": "worker-a:nkn:ipv4-001",
            "last_server_ack_at": 100.0,
        },
    )

    async def run():
        with patch.object(worker_api.nkn_runtime, "suspend_slot") as suspend:
            await worker_api._enforce_nkn_lease_guard(now=939.0)
        suspend.assert_not_called()

    asyncio.run(run())


def test_worker_lease_guard_precedes_the_server_fifteen_minute_reclaim():
    assert worker_api.NKN_LEASE_GUARD_SECONDS == 14 * 60
    assert worker_api.NKN_LEASE_GUARD_SECONDS < 15 * 60


def test_worker_lease_guard_suspends_pre_guard_state_until_server_ack(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    worker_api._save_nkn_wallet_state(
        "ipv4-001",
        {
            "slot_id": "ipv4-001",
            "wallet_id": 7,
            "wallet_assignment_version": 3,
            "lease_client_id": "worker-a:nkn:ipv4-001",
        },
    )
    client = type("Client", (), {"close": lambda self: None})()

    async def run():
        with (
            patch.object(worker_api.orchestrator, "_get_client", return_value=client),
            patch.object(worker_api.nkn_runtime, "suspend_slot", return_value={"status": "stopped"}) as suspend,
        ):
            await worker_api._enforce_nkn_lease_guard(now=1_000.0)
        suspend.assert_called_once()

    asyncio.run(run())
    saved = json.loads(Path(tmp_path, "nkn-wallets", "ipv4-001.json").read_text(encoding="utf-8"))
    assert saved["lease_guard_suspended"] is True


def test_worker_lease_guard_keeps_a_suspended_assignment_stopped_after_docker_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    assignment = {
        "slot_id": "ipv4-001",
        "wallet_id": 7,
        "wallet_assignment_version": 3,
        "lease_client_id": "worker-a:nkn:ipv4-001",
        "last_server_ack_at": 100.0,
        "lease_guard_suspended": True,
    }
    worker_api._save_nkn_wallet_state("ipv4-001", assignment)
    client = type("Client", (), {"close": lambda self: None})()

    async def run():
        with (
            patch.object(worker_api.orchestrator, "_get_client", return_value=client),
            patch.object(worker_api.nkn_runtime, "suspend_slot", return_value={"status": "stopped"}) as suspend,
        ):
            await worker_api._enforce_nkn_lease_guard(now=1_001.0)
        suspend.assert_called_once()

    asyncio.run(run())


def test_nkn_heartbeat_does_not_sync_another_workers_lease():
    async def run():
        body = _body()
        body.provider_states["nkn"]["instances"][0]["lease_client_id"] = "other:nkn:ipv4-001"

        def discard(coro):
            coro.close()

        with (
            patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
            patch.object(database, "upsert_worker", AsyncMock(return_value=11)),
            patch.object(database, "sync_nkn_wallet_runtime", AsyncMock()) as sync,
            patch.object(database, "confirm_worker_key", AsyncMock()),
            patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
            patch.object(main, "_spawn", side_effect=discard),
            patch.object(main.metrics, "record_heartbeat"),
        ):
            response = await main.api_worker_heartbeat(
                type("Request", (), {"headers": {"authorization": "Bearer key"}})(), body
            )
        assert response["status"] == "ok"
        sync.assert_not_awaited()

    asyncio.run(run())


def test_stale_worker_check_reclaims_nkn_only_after_fifteen_minutes():
    async def run():
        def discard(coro):
            coro.close()

        with (
            patch.object(database, "list_workers", AsyncMock(return_value=[])),
            patch.object(database, "reclaim_stale_nkn_wallets", AsyncMock(return_value=[])) as reclaim,
            patch.object(main, "_spawn", side_effect=discard),
        ):
            await main._check_stale_workers()
        reclaim.assert_awaited_once_with(stale_after_seconds=900)

    asyncio.run(run())


def test_worker_provider_states_include_nkn_instances_without_wallet_material():
    async def run():
        worker = {"id": 3, "client_id": "worker-a"}
        with (
            patch.object(database, "get_worker_proxy_assignment", AsyncMock(return_value=None)),
            patch.object(
                database,
                "list_myst_wallets",
                AsyncMock(return_value=[]),
            ),
            patch.object(
                database,
                "list_nkn_wallets",
                AsyncMock(
                    return_value=[
                        {
                            "id": 7,
                            "state": "LEASED",
                            "leased_to_client_id": "worker-a:nkn:ipv4-001",
                            "wallet_assignment_version": 3,
                            "node_identity": "NKNnode",
                            "runtime_status": "running",
                            "public_ip": "8.8.8.8",
                            "evidence_json": '{"online": true}',
                        }
                    ]
                ),
            ),
            patch.object(database, "list_earnapp_logical_nodes", AsyncMock(return_value=[])),
        ):
            states = await main._worker_provider_states(worker)
        assert states["nkn"]["online"] == 1
        assert states["nkn"]["offline"] == 0
        assert states["nkn"]["instances"][0]["wallet_id"] == 7
        assert "wallet_json" not in json.dumps(states)

    asyncio.run(run())


def test_worker_nkn_state_uses_authoritative_node_evidence_and_container_id(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    worker_api._save_nkn_wallet_state(
        "ipv4-001",
        {
            "slot_id": "ipv4-001",
            "instance_id": "nkn-direct-ipv4-001",
            "container_id": "container-123",
            "wallet_id": 7,
            "wallet_assignment_version": 3,
            "lease_client_id": "worker-a:nkn:ipv4-001",
            "evidence": {"online": False},
        },
    )
    container = type("Container", (), {"status": "running"})()

    async def run():
        with (
            patch.object(
                worker_api.orchestrator,
                "get_status",
                return_value=[{"instance_id": "nkn-direct-ipv4-001", "status": "running"}],
            ),
            patch.object(worker_api.orchestrator, "_get_client") as get_client,
            patch.object(
                worker_api.nkn_runtime,
                "node_evidence",
                return_value={"running": True, "sync_state": "PERSIST_FINISHED", "online": True},
            ) as evidence,
        ):
            get_client.return_value.containers.get.return_value = container
            state = await worker_api._nkn_provider_state()
            evidence.assert_called_once_with(container)
            get_client.return_value.close.assert_called_once_with()
            return state

    state = asyncio.run(run())
    assert state["online"] == 1
    assert state["instances"][0]["container_id"] == "container-123"
    assert state["instances"][0]["evidence"]["sync_state"] == "PERSIST_FINISHED"


def test_worker_nkn_lxd_state_uses_host_helper_without_opening_docker(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    worker_api._save_nkn_wallet_state(
        "ipv4-001",
        {
            "slot_id": "ipv4-001",
            "instance_id": "cashpilot-nkn-w7-ipv4-001",
            "runtime_backend": "lxd",
            "wallet_id": 7,
            "wallet_assignment_version": 3,
            "lease_client_id": "worker-a:nkn:ipv4-001",
        },
    )

    async def run():
        with (
            patch.object(
                worker_api.nkn_lxd_runtime,
                "node_evidence",
                return_value={
                    "running": True,
                    "online": True,
                    "sync_state": "PERSIST_FINISHED",
                    "node_id": "NKNnode-id",
                },
            ) as evidence,
            patch.object(worker_api.orchestrator, "_get_client") as docker,
        ):
            state = await worker_api._nkn_provider_state()
        evidence.assert_called_once()
        docker.assert_not_called()
        return state

    state = asyncio.run(run())
    assert state["online"] == 1
    assert state["instances"][0]["runtime_status"] == "running"
    assert state["instances"][0]["node_identity"] == "NKNnode-id"


def test_worker_lease_guard_suspends_lxd_without_opening_docker(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    worker_api._save_nkn_wallet_state(
        "ipv4-001",
        {
            "slot_id": "ipv4-001",
            "runtime_backend": "lxd",
            "wallet_id": 7,
            "wallet_assignment_version": 3,
            "lease_client_id": "worker-a:nkn:ipv4-001",
            "last_server_ack_at": 100.0,
        },
    )

    async def run():
        with (
            patch.object(worker_api.nkn_lxd_runtime, "suspend_slot", return_value={"status": "stopped"}) as suspend,
            patch.object(worker_api.orchestrator, "_get_client") as docker,
        ):
            await worker_api._enforce_nkn_lease_guard(now=1_000.0)
        suspend.assert_called_once_with(
            "ipv4-001",
            wallet_id=7,
            wallet_assignment_version=3,
            lease_client_id="worker-a:nkn:ipv4-001",
        )
        docker.assert_not_called()

    asyncio.run(run())
