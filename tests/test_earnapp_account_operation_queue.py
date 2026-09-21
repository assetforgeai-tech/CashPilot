import asyncio
from datetime import UTC, datetime, timedelta

from app import database


async def _seed_accounts(*account_ids: int) -> None:
    db = await database._open_transaction_connection()
    await db.execute("BEGIN IMMEDIATE")
    for account_id in account_ids:
        await db.execute(
            """
            INSERT INTO earnapp_accounts
                (id, profile_key, account_name, auth_method, credentials_enc)
            VALUES (?, ?, ?, 'google', 'test-only')
            """,
            (account_id, f"profile-{account_id}", f"account-{account_id}"),
        )
    await db.commit()
    await db.close()


def test_account_operation_queue_serializes_per_account_and_allows_other_accounts(tmp_path):
    async def run():
        db_path = tmp_path / "cashpilot.db"
        from unittest.mock import patch

        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", db_path):
            await database.init_db()
            await _seed_accounts(10, 11)
            first = await database.enqueue_earnapp_account_operation(10, "link", "node-a", operation_key="link:node-a")
            second = await database.enqueue_earnapp_account_operation(10, "link", "node-b", operation_key="link:node-b")
            other = await database.enqueue_earnapp_account_operation(11, "link", "node-c", operation_key="link:node-c")
            assert first["id"] != second["id"]
            claim = await database.claim_earnapp_account_operation(10, "worker-a")
            assert claim["id"] == first["id"]
            assert await database.claim_earnapp_account_operation(10, "worker-b") is None
            other_claim = await database.claim_earnapp_account_operation(11, "worker-b")
            assert other_claim["id"] == other["id"]

    asyncio.run(run())


def test_account_operation_queue_persists_cooldown_and_idempotency(tmp_path):
    async def run():
        db_path = tmp_path / "cashpilot.db"
        from unittest.mock import patch

        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", db_path):
            await database.init_db()
            await _seed_accounts(10)
            item = await database.enqueue_earnapp_account_operation(10, "link", "node-a", operation_key="link:node-a")
            duplicate = await database.enqueue_earnapp_account_operation(
                10, "link", "node-a", operation_key="link:node-a"
            )
            assert duplicate["id"] == item["id"]
            claim = await database.claim_earnapp_account_operation(10, "worker-a")
            await database.complete_earnapp_account_operation(claim["id"], cooldown_seconds=300)

            await database.init_db()
            assert await database.claim_earnapp_account_operation(10, "worker-b") is None

    asyncio.run(run())


def test_expired_account_operation_lease_is_reclaimable(tmp_path):
    async def run():
        db_path = tmp_path / "cashpilot.db"
        from unittest.mock import patch

        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", db_path):
            await database.init_db()
            await _seed_accounts(10)
            item = await database.enqueue_earnapp_account_operation(10, "link", "node-a", operation_key="link:node-a")
            claim = await database.claim_earnapp_account_operation(10, "worker-a", lease_seconds=1)
            assert claim["id"] == item["id"]
            db = await database._open_transaction_connection()
            expired = (datetime.now(UTC) - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                "UPDATE earnapp_account_operations SET lease_expires_at = ? WHERE id = ?",
                (expired, item["id"]),
            )
            await db.commit()
            await db.close()
            reclaimed = await database.claim_earnapp_account_operation(10, "worker-b")
            assert reclaimed["id"] == item["id"]

    asyncio.run(run())


def test_successful_account_operation_persists_five_second_spacing(tmp_path):
    async def run():
        db_path = tmp_path / "cashpilot.db"
        from unittest.mock import patch

        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", db_path):
            await database.init_db()
            await _seed_accounts(10)
            item = await database.enqueue_earnapp_account_operation(10, "link", "node-a", operation_key="link:node-a")
            claim = await database.claim_earnapp_account_operation(10, "worker-a")
            assert claim["id"] == item["id"]
            await database.complete_earnapp_account_operation(claim["id"], cooldown_seconds=5)
            assert await database.claim_earnapp_account_operation(10, "worker-b") is None

    asyncio.run(run())


def test_completed_collector_operation_can_run_again(tmp_path):
    async def run():
        db_path = tmp_path / "cashpilot.db"
        from unittest.mock import patch

        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", db_path):
            await database.init_db()
            await _seed_accounts(10)
            first = await database.enqueue_earnapp_account_operation(10, "collect", operation_key="collector:10")
            claimed = await database.claim_earnapp_account_operation(10, "worker-a")
            assert claimed["id"] == first["id"]
            await database.complete_earnapp_account_operation(claimed["id"])
            second = await database.enqueue_earnapp_account_operation(10, "collect", operation_key="collector:10")
            assert second["id"] == first["id"]
            next_claim = await database.claim_earnapp_account_operation(10, "worker-b")
            assert next_claim["id"] == first["id"]

    asyncio.run(run())


def test_failed_account_operation_remains_retryable_after_cooldown(tmp_path):
    async def run():
        db_path = tmp_path / "cashpilot.db"
        from unittest.mock import patch

        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", db_path):
            await database.init_db()
            await _seed_accounts(10)
            item = await database.enqueue_earnapp_account_operation(
                10, "delete_device", "node-a", operation_key="delete:node-a"
            )
            claim = await database.claim_earnapp_account_operation(10, "worker-a")
            assert claim["id"] == item["id"]
            assert await database.fail_earnapp_account_operation(
                claim["id"], error_kind="remote_delete_failed", cooldown_seconds=300
            )
            row = await database._get_db()
            try:
                failed = await (
                    await row.execute(
                        "SELECT state, last_error_kind FROM earnapp_account_operations WHERE id = ?", (item["id"],)
                    )
                ).fetchone()
            finally:
                await row.close()
            assert failed["state"] == "COOLDOWN"
            assert failed["last_error_kind"] == "remote_delete_failed"

    asyncio.run(run())
