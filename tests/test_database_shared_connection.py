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
