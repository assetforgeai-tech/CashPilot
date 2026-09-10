from __future__ import annotations

import asyncio
from unittest.mock import patch

from app import database


def test_provider_capacity_groups_endpoints_and_active_leases(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "capacity.db"):
            await database.init_db()
            provider = await database.upsert_proxy_provider("Pool A", "residential")
            ids = await database.upsert_proxy_endpoints_returning_ids(
                provider,
                [
                    {
                        "provider_proxy_id": "a",
                        "host": "1.1.1.1",
                        "port": 1,
                        "status": "alive",
                        "exit_ip": "198.51.100.1",
                    },
                    {
                        "provider_proxy_id": "b",
                        "host": "2.2.2.2",
                        "port": 2,
                        "status": "alive",
                        "exit_ip": "198.51.100.2",
                    },
                ],
            )
            groups = await database.get_provider_proxy_capacity()
            row = next(item for item in groups if item["provider_id"] == provider)
            assert row["total"] == 2
            assert row["available"] == 2
            assert row["leased"] == 0
            assert ids

    asyncio.run(run())
