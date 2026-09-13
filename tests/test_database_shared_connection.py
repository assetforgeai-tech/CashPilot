import asyncio
import sqlite3
from unittest.mock import AsyncMock, patch

import pytest

from app import database


def test_failed_shared_write_does_not_poison_later_heartbeat(tmp_path):
    async def run():
        db_path = tmp_path / "cashpilot.db"
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", db_path):
            await database.init_db()
            await database.upsert_worker("worker-a", "worker-a", "http://worker")

            shared = await database._get_db()
            await shared.execute("PRAGMA busy_timeout=1")
            await shared.close()
            blocker = await database._open_transaction_connection()
            await blocker.execute("PRAGMA busy_timeout=1")
            try:
                await blocker.execute("BEGIN IMMEDIATE")
                await blocker.execute("UPDATE workers SET name = 'blocked-writer' WHERE client_id = 'worker-a'")

                with pytest.raises(sqlite3.OperationalError) as exc_info:
                    await database.confirm_worker_key("worker-a")
                assert exc_info.value.sqlite_errorcode == sqlite3.SQLITE_BUSY

                # A later request can read through the same shared connection
                # before the competing writer finishes.
                worker = await database.get_worker_by_client_id("worker-a")
                assert worker["name"] == "worker-a"

                await blocker.commit()
                worker_id = await database.upsert_worker("worker-a", "worker-a", "http://worker")
                assert worker_id > 0
            finally:
                if blocker.in_transaction:
                    await blocker.rollback()
                await blocker.close()
                await database.close_shared()

    asyncio.run(run())


def test_direct_capacity_slot_is_reusable_after_failed_deploy(tmp_path):
    async def run():
        db_path = tmp_path / "cashpilot.db"
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", db_path):
            await database.init_db()
            await database.upsert_worker("worker-a", "worker-a", "http://worker-a")
            await database.save_provider_instance(
                "earnfm", "node-1", worker_id=1, mode="direct", capacity_slot="ipv4-001", status="failed"
            )
            await database.save_provider_instance(
                "earnfm", "node-2", worker_id=1, mode="direct", capacity_slot="ipv4-001", status="planned"
            )
            assert await database.get_provider_instance("node-2")
            await database.close_shared()

    asyncio.run(run())


def test_direct_slot_is_reusable_by_different_providers_on_one_worker(tmp_path):
    async def run():
        db_path = tmp_path / "cashpilot.db"
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", db_path):
            await database.init_db()
            await database.upsert_worker("worker-a", "worker-a", "http://worker-a")
            await database.save_provider_instance(
                "nkn", "nkn-a", worker_id=1, mode="direct", capacity_slot="ipv4-001", status="planned"
            )
            await database.save_provider_instance(
                "mysterium", "mysterium-a", worker_id=1, mode="direct", capacity_slot="ipv4-001", status="planned"
            )
            assert await database.get_provider_instance("nkn-a")
            assert await database.get_provider_instance("mysterium-a")
            await database.close_shared()

    asyncio.run(run())


def test_provider_proxy_lease_migration_backfills_proxy_lane(tmp_path):
    async def run():
        db_path = tmp_path / "cashpilot.db"
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", db_path):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("legacy", "Legacy")
            (proxy_id,) = await database.upsert_proxy_endpoints_returning_ids(
                provider_id,
                [{"provider_proxy_id": "one", "host": "198.51.100.20", "port": 8080}],
            )
            worker_id = await database.upsert_worker("worker-a", "worker-a", "http://worker-a")
            db = await database._get_db()
            await db.execute(
                "INSERT INTO provider_proxy_leases "
                "(provider_slug, worker_id, instance_id, proxy_id, exit_ip) VALUES (?, ?, ?, ?, ?)",
                ("earnfm", worker_id, "earnfm-proxy-w1-proxy-001", proxy_id, "198.51.100.21"),
            )
            await db.commit()
            await db.close()
            await database.close_shared()

            connection = sqlite3.connect(db_path)
            connection.executescript(
                """
                DROP INDEX IF EXISTS idx_provider_proxy_leases_active_instance;
                DROP INDEX IF EXISTS idx_provider_proxy_leases_active_proxy;
                DROP INDEX IF EXISTS idx_provider_proxy_leases_active_exit;
                ALTER TABLE provider_proxy_leases RENAME TO provider_proxy_leases_current;
                CREATE TABLE provider_proxy_leases AS
                    SELECT id, provider_slug, worker_id, instance_id, proxy_id, exit_ip,
                           leased_at, released_at, release_reason
                    FROM provider_proxy_leases_current;
                DROP TABLE provider_proxy_leases_current;
                """
            )
            connection.commit()
            connection.close()

            await database.init_db()
            db = await database._get_db()
            try:
                row = await (await db.execute("SELECT lane FROM provider_proxy_leases WHERE id = 1")).fetchone()
                assert row["lane"] == "proxy"
            finally:
                await db.close()
                await database.close_shared()

    asyncio.run(run())


def test_shared_connection_borrow_serializes_transactions_across_tasks(tmp_path):
    async def run():
        db_path = tmp_path / "cashpilot.db"
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", db_path):
            await database.init_db()
            await database.upsert_worker("worker-a", "worker-a", "http://worker")
            first_write_done = asyncio.Event()
            release_first_writer = asyncio.Event()

            async def first_writer():
                db = await database._get_db()
                try:
                    await db.execute("UPDATE workers SET name = 'first-writer' WHERE client_id = 'worker-a'")
                    first_write_done.set()
                    await release_first_writer.wait()
                    await db.commit()
                finally:
                    await db.close()

            async def second_writer():
                await first_write_done.wait()
                return await database.upsert_worker("worker-b", "worker-b", "http://worker")

            first_task = asyncio.create_task(first_writer())
            second_task = asyncio.create_task(second_writer())
            await first_write_done.wait()
            await asyncio.sleep(0.05)
            assert not second_task.done()

            release_first_writer.set()
            await first_task
            assert await second_task > 0
            worker = await database.get_worker_by_client_id("worker-a")
            assert worker["name"] == "first-writer"
            await database.close_shared()

    asyncio.run(run())


def test_shared_connection_borrow_is_reentrant_within_one_task(tmp_path):
    async def run():
        db_path = tmp_path / "cashpilot.db"
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", db_path):
            await database.init_db()
            await database.upsert_worker("worker-a", "worker-a", "http://worker")

            outer = await database._get_db()
            try:
                await outer.execute("UPDATE workers SET name = 'outer-writer' WHERE client_id = 'worker-a'")
                async with asyncio.timeout(0.2):
                    inner = await database._get_db()
                await inner.close()

                other_task = asyncio.create_task(database.upsert_worker("worker-b", "worker-b", "http://worker"))
                await asyncio.sleep(0.05)
                assert not other_task.done()

                await outer.commit()
            finally:
                await outer.close()

            assert await other_task > 0
            worker = await database.get_worker_by_client_id("worker-a")
            assert worker["name"] == "outer-writer"
            await database.close_shared()

    asyncio.run(run())


def test_shared_connection_close_releases_lock_when_rollback_fails(tmp_path):
    async def run():
        db_path = tmp_path / "cashpilot.db"
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", db_path):
            await database.init_db()
            borrowed = await database._get_db()
            conn = object.__getattribute__(borrowed, "_conn")
            key = object.__getattribute__(borrowed, "_key")
            await borrowed.execute("BEGIN")

            with (
                patch.object(conn, "rollback", side_effect=RuntimeError("rollback failed")),
                pytest.raises(RuntimeError, match="rollback failed"),
            ):
                await borrowed.close()

            assert key not in database._shared_conn_owners
            assert key not in database._shared_conn_depths
            assert not database._shared_conn_locks[key].locked()

            next_borrow = await asyncio.wait_for(database._get_db(), timeout=0.2)
            await next_borrow.close()
            await database.close_shared()

    asyncio.run(run())


def test_close_shared_releases_lock_when_connection_close_fails(tmp_path):
    async def run():
        db_path = tmp_path / "cashpilot.db"
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", db_path):
            await database.init_db()
            borrowed = await database._get_db()
            conn = object.__getattribute__(borrowed, "_conn")
            key = object.__getattribute__(borrowed, "_key")
            await borrowed.close()

            try:
                with (
                    patch.object(conn, "close", AsyncMock(side_effect=RuntimeError("close failed"))),
                    pytest.raises(RuntimeError, match="close failed"),
                ):
                    await database.close_shared()

                assert key not in database._shared_conns
                assert key not in database._shared_conn_locks
                assert key not in database._shared_conn_owners
                assert key not in database._shared_conn_depths
            finally:
                database._shared_conns.pop(key, None)
                lock = database._shared_conn_locks.pop(key, None)
                database._shared_conn_owners.pop(key, None)
                database._shared_conn_depths.pop(key, None)
                if lock is not None and lock.locked():
                    lock.release()
                await conn.close()

    asyncio.run(run())
