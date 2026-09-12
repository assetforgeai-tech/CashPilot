from __future__ import annotations

import asyncio
from unittest.mock import patch

from app import database


def test_provider_capacity_signature_supports_scope_filters():
    import inspect

    params = inspect.signature(database.get_provider_proxy_capacity).parameters
    assert "provider_slug" in params
    assert "country_code" in params
    assert "required_ip_type" in params


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
            assert row["eligible"] == 2
            assert row["available"] == 2
            assert row["leased"] == 0
            assert row["sticky_owned"] == 0
            assert row["duplicate_egress"] == 0
            assert ids

    asyncio.run(run())


def test_provider_capacity_filters_country_type_and_provider_mask(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "scoped.db"):
            await database.init_db()
            provider = await database.upsert_proxy_provider("Pool A", "residential")
            ids = await database.upsert_proxy_endpoints_returning_ids(
                provider,
                [
                    {
                        "provider_proxy_id": "vn-res",
                        "host": "1.1.1.1",
                        "port": 1,
                        "status": "alive",
                        "exit_ip": "198.51.100.1",
                        "country_code": "VN",
                        "ip_type": "residential",
                    },
                    {
                        "provider_proxy_id": "us-dch",
                        "host": "2.2.2.2",
                        "port": 2,
                        "status": "alive",
                        "exit_ip": "198.51.100.2",
                        "country_code": "US",
                        "ip_type": "datacenter",
                    },
                ],
            )
            await database.mask_proxy_for_provider(ids[0], "packetstream", "test")

            vn = await database.get_provider_proxy_capacity(
                provider_slug="packetstream", country_code="VN", required_ip_type="residential"
            )
            row = next(item for item in vn if item["provider_id"] == provider)
            assert row["eligible"] == 0
            assert row["available"] == 0

            us = await database.get_provider_proxy_capacity(country_code="US", required_ip_type="datacenter")
            row = next(item for item in us if item["provider_id"] == provider)
            assert row["eligible"] == 1
            assert row["available"] == 1

    asyncio.run(run())
