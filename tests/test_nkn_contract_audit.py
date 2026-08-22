from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import database, main, worker_api


def _request(method: str = "POST", path: str = "/api/deploy/nkn") -> Request:
    return Request({"type": "http", "method": method, "path": path, "headers": []})


def test_nkn_database_instance_id_is_scoped_to_worker():
    first = main._nkn_record_instance_id(7, "ipv4-001")
    second = main._nkn_record_instance_id(8, "ipv4-001")
    assert first != second
    assert first.endswith("ipv4-001")


def test_worker_delete_returns_conflict_when_nkn_lease_is_still_active():
    async def run():
        with (
            patch.object(main, "_require_owner"),
            patch.object(main.database, "get_worker", AsyncMock(return_value={"id": 7, "name": "worker-a"})),
            patch.object(
                main.database,
                "delete_worker",
                AsyncMock(side_effect=database.NknWalletLeaseActive("active lease")),
            ) as delete,
            pytest.raises(HTTPException) as exc,
        ):
            await main.api_delete_worker(_request("DELETE", "/api/workers/7"), 7)
        assert exc.value.status_code == 409
        assert "NKN slots" in str(exc.value.detail)
        delete.assert_awaited_once_with(7)

    asyncio.run(run())


def test_generic_nkn_deploy_uses_slot_scheduler_and_never_global_deploy_row():
    async def run():
        with (
            patch.object(main, "_resolve_worker_id", AsyncMock(return_value=7)),
            patch.object(
                main.database,
                "get_config",
                AsyncMock(return_value={"nkn_beneficiary_address": "NKNBeneficiaryAddress"}),
            ),
            patch.object(
                main, "_deploy_nkn_slots", AsyncMock(return_value={"slots": 1, "deployed": ["ipv4-001"], "failed": []})
            ) as scheduler,
            patch.object(main.database, "save_deployment", AsyncMock()) as save,
            patch.object(main, "_proxy_worker_deploy", AsyncMock()) as generic,
        ):
            result = await main.api_deploy(
                _request(), "nkn", main.DeployRequest(mode="direct"), worker_id=7, _auth={"r": "owner"}
            )
        scheduler.assert_awaited_once_with(7, beneficiary_address="NKNBeneficiaryAddress")
        generic.assert_not_awaited()
        save.assert_not_awaited()
        assert result["status"] == "deployed"

    asyncio.run(run())


def test_nkn_is_not_backfilled_as_a_global_collection_deployment():
    async def run():
        with (
            patch.object(
                main.database, "get_config", AsyncMock(return_value={"nkn_beneficiary_address": "configured"})
            ),
            patch.object(main.database, "get_deployments", AsyncMock(return_value=[])),
            patch.object(main.catalog, "get_services", return_value=[{"slug": "nkn", "status": "active"}]),
            patch.object(main.database, "save_deployment", AsyncMock()) as save,
        ):
            assert await main._track_fully_configured_services() == 0
        save.assert_not_awaited()

    asyncio.run(run())


def test_nkn_reclaim_clears_identity_and_evidence(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "nkn.db"):
            await database.init_db()
            worker_id = await database.upsert_worker("worker-a", name="worker-a")
            await database.import_nkn_wallet_records(
                [
                    {
                        "folder_name": "1000001",
                        "wallet_json": json.dumps({"Address": "NKNwalletAddressOne"}),
                        "wallet_pswd": "password",
                    }
                ]
            )
            lease = await database.lease_nkn_wallet("worker-a:nkn:ipv4-001", worker_id=worker_id, public_ip="8.8.8.8")
            assert lease is not None
            await database.sync_nkn_wallet_runtime(
                lease["id"],
                lease["leased_to_client_id"],
                wallet_assignment_version=lease["wallet_assignment_version"],
                node_identity="old-node",
                runtime_status="running",
                evidence={"online": True},
            )
            db = await database._get_db()
            try:
                await db.execute(
                    "UPDATE workers SET status='offline', last_heartbeat=datetime('now', '-16 minutes') WHERE id=?",
                    (worker_id,),
                )
                await db.commit()
            finally:
                await db.close()
            assert await database.reclaim_stale_nkn_wallets()  # noqa: S101 - regression assertion
            row = (await database.list_nkn_wallets())[0]
            assert row["node_identity"] == ""
            assert row["runtime_status"] == ""
            assert row["evidence_json"] == "{}"

    asyncio.run(run())


def test_nkn_deliberate_release_clears_identity_and_evidence(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "nkn.db"):
            await database.init_db()
            await database.import_nkn_wallet_records(
                [
                    {
                        "folder_name": "1000001",
                        "wallet_json": json.dumps({"Address": "NKNwalletAddressOne"}),
                        "wallet_pswd": "password",
                    }
                ]
            )
            lease = await database.lease_nkn_wallet("worker-a:nkn:ipv4-001", worker_id=7, public_ip="8.8.8.8")
            assert lease is not None
            await database.sync_nkn_wallet_runtime(
                lease["id"],
                lease["leased_to_client_id"],
                wallet_assignment_version=lease["wallet_assignment_version"],
                node_identity="old-node",
                runtime_status="running",
                evidence={"online": True},
            )
            assert await database.release_nkn_wallet(
                lease["id"],
                lease["leased_to_client_id"],
                wallet_assignment_version=lease["wallet_assignment_version"],
            )
            row = (await database.list_nkn_wallets())[0]
            assert row["node_identity"] == ""
            assert row["runtime_status"] == ""
            assert row["evidence_json"] == "{}"

    asyncio.run(run())


def test_nkn_heartbeat_rejects_public_ip_rebinding(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "nkn.db"):
            await database.init_db()
            await database.import_nkn_wallet_records(
                [
                    {
                        "folder_name": "1000001",
                        "wallet_json": json.dumps({"Address": "NKNwalletAddressOne"}),
                        "wallet_pswd": "password",
                    }
                ]
            )
            lease = await database.lease_nkn_wallet("worker-a:nkn:ipv4-001", worker_id=7, public_ip="8.8.8.8")
            assert lease is not None
            assert not await database.sync_nkn_wallet_runtime(
                lease["id"],
                lease["leased_to_client_id"],
                wallet_assignment_version=lease["wallet_assignment_version"],
                public_ip="1.1.1.1",
                evidence={"online": True},
            )
            assert (await database.list_nkn_wallets())[0]["public_ip"] == "8.8.8.8"

    asyncio.run(run())


def test_worker_nkn_deploy_closes_docker_client(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    spec = worker_api.NknDeploySpec(
        wallet_id=7,
        wallet_assignment_version=1,
        lease_client_id="worker-a:nkn:ipv4-001",
        wallet_json=json.dumps({"Address": "NKNwalletAddress"}),
        wallet_pswd="password-value",
        beneficiary_address="NKNBeneficiaryAddress",
    )
    client = MagicMock()

    async def run():
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(
                worker_api, "_load_public_ip_slots", return_value=[{"slot_id": "ipv4-001", "public_ip": "8.8.8.8"}]
            ),
            patch.object(
                worker_api.nkn_runtime,
                "deploy_slot",
                return_value={"container_id": "cid", "instance_id": "nkn-direct-ipv4-001"},
            ),
            patch.object(worker_api.orchestrator, "_get_client", return_value=client),
        ):
            await worker_api.api_deploy_nkn_slot(_request(path="/api/nkn/slots/ipv4-001/deploy"), "ipv4-001", spec)

    asyncio.run(run())
    client.close.assert_called_once()


def test_worker_nkn_remove_closes_docker_client(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    worker_api._save_nkn_wallet_state(
        "ipv4-001",
        {
            "wallet_id": 7,
            "wallet_assignment_version": 1,
            "lease_client_id": "worker-a:nkn:ipv4-001",
        },
    )
    spec = worker_api.NknRemoveSpec(
        wallet_id=7,
        wallet_assignment_version=1,
        lease_client_id="worker-a:nkn:ipv4-001",
    )
    client = MagicMock()

    async def run():
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(worker_api.nkn_runtime, "remove_slot", return_value={"deleted_volume": True}),
            patch.object(worker_api.orchestrator, "_get_client", return_value=client),
        ):
            await worker_api.api_remove_nkn_slot(_request("DELETE", "/api/nkn/slots/ipv4-001"), "ipv4-001", spec)

    asyncio.run(run())
    client.close.assert_called_once()


def test_worker_reconciles_a_rejected_assignment_with_label_guarded_remove(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    item = {
        "slot_id": "ipv4-001",
        "wallet_id": 7,
        "wallet_assignment_version": 1,
        "lease_client_id": "worker-a:nkn:ipv4-001",
    }
    worker_api._save_nkn_wallet_state("ipv4-001", item)
    client = MagicMock()

    async def run():
        with (
            patch.object(worker_api.orchestrator, "_get_client", return_value=client),
            patch.object(worker_api.nkn_runtime, "remove_slot", return_value={"deleted_volume": True}) as remove,
        ):
            await worker_api._reconcile_nkn_assignment_rejections([item])
        remove.assert_called_once_with(
            "ipv4-001",
            wallet_id=7,
            wallet_assignment_version=1,
            lease_client_id="worker-a:nkn:ipv4-001",
            client=client,
            delete_volume=True,
        )

    asyncio.run(run())
    client.close.assert_called_once()
    assert not Path(tmp_path, "nkn-wallets", "ipv4-001.json").exists()


def test_nkn_auto_deploy_does_not_mark_zero_slot_worker_complete():
    async def run():
        main._NKN_AUTO_DEPLOY_DONE.discard(7)
        main._WORKER_HEARTBEAT_STREAKS[7] = 2
        spawned: list[object] = []

        def capture(coro):
            spawned.append(coro)
            return None

        with (
            patch.object(
                main.database,
                "get_config",
                AsyncMock(
                    return_value={
                        "nkn_beneficiary_address": "NKNBeneficiaryAddress",
                        "cashpilot_auto_deploy_enabled": "true",
                    }
                ),
            ),
            patch.object(
                main.database,
                "get_worker",
                AsyncMock(return_value={"id": 7, "name": "worker-a", "client_id": "worker-a"}),
            ),
            patch.object(main, "_worker_public_ip_slots", AsyncMock(return_value=[])),
            patch.object(main, "_deploy_nkn_slots", AsyncMock(return_value={"slots": 0, "failed": []})),
            patch.object(main, "_spawn", side_effect=capture),
            patch.object(main.database, "get_deployments", AsyncMock(return_value=[])),
            patch.object(main.catalog, "get_services", return_value=[]),
        ):
            await main._maybe_auto_deploy_after_heartbeat(7)
        assert spawned
        await spawned.pop(0)
        assert 7 not in main._NKN_AUTO_DEPLOY_DONE

    asyncio.run(run())


@pytest.mark.parametrize("compose", ["docker-compose.yml", "docker-compose.fleet.yml", "docker-compose.build.yml"])
def test_worker_compose_mounts_bootstrap_slot_state(compose):
    text = Path(compose).read_text(encoding="utf-8")
    assert "cashpilot_public_ip_slots:/network:ro" in text
    assert "CASHPILOT_PUBLIC_IP_SLOTS_FILE=/network/public-ip-slots.json" in text
    assert "name: cashpilot_public_ip_slots" in text
    assert "/etc/cashpilot/public-ip-slots.json:/etc/cashpilot/public-ip-slots.json:ro" not in text


def test_bootstrap_publishes_slots_to_the_worker_named_volume_without_deploying_a_provider():
    text = Path("scripts/bootstrap-worker.sh").read_text(encoding="utf-8")
    assert "cashpilot_public_ip_slots" in text
    assert "docker volume create" in text
    assert "docker volume inspect" in text
    assert 'public-ip-slots.json"' in text
    assert "docker run" not in text


def test_nkn_worker_heartbeat_response_carries_rejected_assignments():
    async def run():
        body = main.WorkerHeartbeat(
            name="worker-a",
            client_id="worker-a",
            provider_states={
                "nkn": {
                    "instances": [
                        {
                            "wallet_id": 7,
                            "wallet_assignment_version": 1,
                            "lease_client_id": "worker-a:nkn:ipv4-001",
                            "slot_id": "ipv4-001",
                        }
                    ]
                }
            },
        )

        def discard(coro):
            coro.close()

        with (
            patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
            patch.object(database, "upsert_worker", AsyncMock(return_value=7)),
            patch.object(database, "sync_nkn_wallet_runtime", AsyncMock(return_value=False)),
            patch.object(database, "confirm_worker_key", AsyncMock()),
            patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
            patch.object(main, "_spawn", side_effect=discard),
            patch.object(main.metrics, "record_heartbeat"),
        ):
            response = await main.api_worker_heartbeat(_request(), body)
        assert response["nkn_assignment_rejections"] == [
            {
                "slot_id": "ipv4-001",
                "wallet_id": 7,
                "wallet_assignment_version": 1,
                "lease_client_id": "worker-a:nkn:ipv4-001",
            }
        ]

    asyncio.run(run())


def test_scoped_instance_slug_routes_remove_to_the_original_worker_slot():
    async def run():
        with patch.object(main, "_remove_nkn_slot", AsyncMock(return_value={"status": "removed"})) as remove:
            result = await main._svc_remove(
                _request("DELETE", "/api/remove/nkn-direct-w7-ipv4-001"),
                "nkn-direct-w7-ipv4-001",
                worker_id=None,
                delete_volumes=False,
            )
            assert remove.await_args.args[1] == "ipv4-001"
            assert remove.await_args.kwargs["worker_id"] == 7
        assert result["status"] == "removed"

    asyncio.run(run())


def test_raw_worker_command_cannot_bypass_the_nkn_slot_scheduler():
    async def run():
        command = main.WorkerCommand(command="deploy", slug="nkn", spec={"image": "nknorg/nkn:latest"})
        with (
            patch.object(main, "_require_owner"),
            patch.object(main, "_proxy_to_worker", AsyncMock()) as proxy,
            pytest.raises(HTTPException) as exc,
        ):
            await main.api_worker_command(_request(), 7, command)
        assert exc.value.status_code == 409
        proxy.assert_not_awaited()

    asyncio.run(run())
