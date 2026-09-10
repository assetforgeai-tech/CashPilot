from __future__ import annotations

import asyncio
from unittest.mock import patch

from app import database


def test_read_only_earnapp_reconciliation_reports_missing_and_untracked(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "reconcile.db"):
            await database.init_db()
            worker_id = await database.upsert_worker("w", "worker", "http://worker")
            await database.save_provider_instance(
                "earnapp", "node-db", worker_id=worker_id, mode="proxy", container_id="container-db", status="running"
            )
            report = await database.get_earnapp_reconciliation_report(
                worker_id, reported_instance_ids={"node-worker"}, inventory_confirmed=True
            )
            assert report == {
                "worker_id": worker_id,
                "db_instances": ["node-db"],
                "reported_instances": ["node-worker"],
                "missing_from_worker": ["node-db"],
                "untracked_on_worker": ["node-worker"],
                "inventory_confirmed": True,
            }
            assert (await database.get_provider_instance("node-db"))["status"] == "running"

    asyncio.run(run())
