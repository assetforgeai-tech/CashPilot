from __future__ import annotations

import asyncio
from unittest.mock import patch

from app import database


def test_provider_instances_round_trip_and_encrypt_spec(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "instances.db"):
            await database.init_db()
            worker_id = await database.upsert_worker("worker-a", "worker-a", "http://worker")
            await database.save_provider_instance(
                slug="bitping",
                instance_id="bitping-direct",
                worker_id=worker_id,
                mode="direct",
                container_id="cid",
                status="running",
                spec={"image": "bitping/bitpingd:latest", "env": {"BITPING_PASSWORD": "secret"}},
            )

            rows = await database.list_provider_instances()
            assert rows[0]["instance_id"] == "bitping-direct"
            assert rows[0]["mode"] == "direct"
            assert "secret" not in rows[0]["spec_encrypted"]
            assert await database.get_provider_instance("bitping-direct")
            assert (await database.get_provider_instance_spec("bitping-direct"))["env"]["BITPING_PASSWORD"] == "secret"

    asyncio.run(run())


def test_provider_instances_filter_by_worker_and_slug(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "instances.db"):
            await database.init_db()
            worker_a = await database.upsert_worker("worker-a", "worker-a", "http://a")
            worker_b = await database.upsert_worker("worker-b", "worker-b", "http://b")
            await database.save_provider_instance("bitping", "bitping-direct", worker_id=worker_a, mode="direct")
            await database.save_provider_instance("bitping", "bitping-proxy", worker_id=worker_b, mode="proxy")
            await database.save_provider_instance("grass", "grass-proxy", worker_id=worker_a, mode="proxy")

            assert [r["instance_id"] for r in await database.list_provider_instances(slug="bitping")] == [
                "bitping-direct",
                "bitping-proxy",
            ]
            assert [r["instance_id"] for r in await database.list_provider_instances(worker_id=worker_a)] == [
                "bitping-direct",
                "grass-proxy",
            ]

    asyncio.run(run())
