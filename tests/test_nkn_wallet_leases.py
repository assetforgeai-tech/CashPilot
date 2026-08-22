from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from app import database


def _wallet(address: str, folder: str) -> dict[str, str]:
    return {
        "folder_name": folder,
        "wallet_json": json.dumps({"Address": address}),
        "wallet_pswd": f"password-{folder}",
    }


def test_nkn_wallet_lease_is_exclusive_per_slot_and_retry_keeps_assignment(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "nkn.db"):
            await database.init_db()
            await database.import_nkn_wallet_records(
                [_wallet("NKNwalletAddressOne", "1000001"), _wallet("NKNwalletAddressTwo", "1000002")]
            )
            first = await database.lease_nkn_wallet("worker-a:nkn:ipv4-001", worker_id=7, public_ip="8.8.8.8")
            retry = await database.lease_nkn_wallet("worker-a:nkn:ipv4-001", worker_id=7, public_ip="8.8.8.8")
            second = await database.lease_nkn_wallet("worker-a:nkn:ipv4-002", worker_id=7, public_ip="1.1.1.1")
            assert first is not None and second is not None
            assert retry["id"] == first["id"]
            assert retry["wallet_assignment_version"] == first["wallet_assignment_version"] == 1
            assert second["id"] != first["id"]
            assert first["wallet_json"] and first["wallet_pswd"]
            public_rows = await database.list_nkn_wallets()
            assert "wallet_json" not in public_rows[0]
            assert "wallet_pswd" not in public_rows[0]

    asyncio.run(run())


def test_nkn_wallet_lease_concurrency_never_assigns_one_wallet_twice(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "nkn.db"):
            await database.init_db()
            await database.import_nkn_wallet_records([_wallet("NKNwalletAddressOne", "1000001")])
            results = await asyncio.gather(
                database.lease_nkn_wallet("worker-a:nkn:ipv4-001", worker_id=7, public_ip="8.8.8.8"),
                database.lease_nkn_wallet("worker-b:nkn:ipv4-001", worker_id=8, public_ip="1.1.1.1"),
            )
            assert sum(result is not None for result in results) == 1

    asyncio.run(run())


def test_failed_deploy_does_not_release_but_deliberate_remove_uses_cas(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "nkn.db"):
            await database.init_db()
            await database.import_nkn_wallet_records([_wallet("NKNwalletAddressOne", "1000001")])
            lease = await database.lease_nkn_wallet("worker-a:nkn:ipv4-001", worker_id=7, public_ip="8.8.8.8")
            assert lease is not None
            assert (
                await database.release_nkn_wallet(
                    lease["id"],
                    "worker-a:nkn:ipv4-001",
                    release_reason="REMOVED",
                    wallet_assignment_version=lease["wallet_assignment_version"] + 1,
                )
                is False
            )
            assert (await database.list_nkn_wallets())[0]["state"] == "LEASED"
            assert (
                await database.release_nkn_wallet(
                    lease["id"],
                    "worker-a:nkn:ipv4-001",
                    release_reason="REMOVED",
                    wallet_assignment_version=lease["wallet_assignment_version"],
                )
                is True
            )
            row = (await database.list_nkn_wallets())[0]
            assert row["state"] == "AVAILABLE"
            assert row["release_reason"] == "REMOVED"
            assert row["wallet_assignment_version"] == lease["wallet_assignment_version"] + 1

    asyncio.run(run())


def test_sync_runtime_is_cas_guarded_and_updates_redacted_evidence(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "nkn.db"):
            await database.init_db()
            await database.import_nkn_wallet_records([_wallet("NKNwalletAddressOne", "1000001")])
            lease = await database.lease_nkn_wallet("worker-a:nkn:ipv4-001", worker_id=7, public_ip="8.8.8.8")
            assert lease is not None
            assert (
                await database.sync_nkn_wallet_runtime(
                    lease["id"],
                    "worker-a:nkn:ipv4-001",
                    wallet_assignment_version=999,
                    node_identity="NKNnode",
                    runtime_status="running",
                    public_ip="8.8.8.8",
                    evidence={"sync_state": "PERSIST_FINISHED", "online": True},
                )
                is False
            )
            assert (
                await database.sync_nkn_wallet_runtime(
                    lease["id"],
                    "worker-a:nkn:ipv4-001",
                    wallet_assignment_version=lease["wallet_assignment_version"],
                    node_identity="NKNnode",
                    runtime_status="running",
                    public_ip="8.8.8.8",
                    evidence={"sync_state": "PERSIST_FINISHED", "online": True},
                )
                is True
            )
            row = (await database.list_nkn_wallets())[0]
            assert row["node_identity"] == "NKNnode"
            assert row["runtime_status"] == "running"
            assert row["public_ip"] == "8.8.8.8"

    asyncio.run(run())


def test_reclaim_stale_nkn_wallets_waits_15_minutes_and_returns_versioned_cleanup(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "nkn.db"):
            await database.init_db()
            worker_id = await database.upsert_worker("worker-a", name="worker-a")
            await database.import_nkn_wallet_records([_wallet("NKNwalletAddressOne", "1000001")])
            lease = await database.lease_nkn_wallet("worker-a:nkn:ipv4-001", worker_id=worker_id, public_ip="8.8.8.8")
            assert lease is not None
            db = await database._get_db()
            try:
                await db.execute(
                    "UPDATE workers SET status='offline', last_heartbeat=datetime('now', '-14 minutes') WHERE id=?",
                    (worker_id,),
                )
                await db.commit()
            finally:
                await db.close()
            assert await database.reclaim_stale_nkn_wallets(stale_after_seconds=900) == []

            db = await database._get_db()
            try:
                await db.execute(
                    "UPDATE workers SET last_heartbeat=datetime('now', '-16 minutes') WHERE id=?",
                    (worker_id,),
                )
                await db.commit()
            finally:
                await db.close()
            reclaimed = await database.reclaim_stale_nkn_wallets(stale_after_seconds=900)
            assert reclaimed == [
                {
                    "wallet_id": lease["id"],
                    "wallet_assignment_version": lease["wallet_assignment_version"] + 1,
                    "previous_wallet_assignment_version": lease["wallet_assignment_version"],
                    "lease_client_id": "worker-a:nkn:ipv4-001",
                    "worker_id": worker_id,
                    "slot_id": "ipv4-001",
                }
            ]
            row = (await database.list_nkn_wallets())[0]
            assert row["state"] == "AVAILABLE"
            assert row["release_reason"] == "WORKER_HEARTBEAT_STALE_15M"

    asyncio.run(run())


def test_delete_worker_refuses_to_strand_an_active_nkn_wallet_lease(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "nkn.db"):
            await database.init_db()
            worker_id = await database.upsert_worker("worker-a", name="worker-a")
            await database.import_nkn_wallet_records([_wallet("NKNwalletAddressOne", "1000001")])
            lease = await database.lease_nkn_wallet(
                "worker-a:nkn:ipv4-001",
                worker_id=worker_id,
                public_ip="8.8.8.8",
            )
            assert lease is not None

            with pytest.raises(database.NknWalletLeaseActive):
                await database.delete_worker(worker_id)

            assert await database.get_worker(worker_id) is not None
            row = (await database.list_nkn_wallets())[0]
            assert row["state"] == "LEASED"
            assert row["leased_to_worker_id"] == worker_id

    asyncio.run(run())
