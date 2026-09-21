import asyncio
from unittest.mock import patch

from app import database, provider_automation, provider_topology


def test_proxy_heartbeat_groups_keep_earnapp_and_pawns_isolated():
    instances = [
        {"slug": "earnapp", "mode": "proxy", "instance_id": "earnapp-a"},
        {"slug": "iproyal", "mode": "proxy", "instance_id": "pawns-a"},
        {"slug": "packetstream", "mode": "proxy", "instance_id": "packet-a"},
        {"slug": "earnfm", "mode": "direct", "instance_id": "earnfm-direct"},
    ]

    assert provider_topology.group_proxy_heartbeat_targets(instances) == {
        "earnapp": ["earnapp-a"],
        "pawns": ["pawns-a"],
        "shared-proxy": ["packet-a"],
    }


def test_proxy_heartbeat_grouping_is_deterministic_and_deduplicated():
    instances = [
        {"slug": "packetstream", "mode": "proxy", "instance_id": "packet-b"},
        {"slug": "packetstream", "mode": "proxy", "instance_id": "packet-a"},
        {"slug": "packetstream", "mode": "direct", "instance_id": "direct"},
        {"slug": "packetstream", "mode": "proxy", "instance_id": "packet-a"},
        {"slug": "unknown", "mode": "proxy", "instance_id": "unknown"},
    ]

    assert provider_topology.group_proxy_heartbeat_targets(instances) == {
        "shared-proxy": ["packet-a", "packet-b", "unknown"],
    }


def test_capacity_counters_are_authority_derived_and_concise():
    assert provider_automation.capacity_counters(
        {"total": 10, "eligible": 8, "available": 3, "leased": 5, "duplicate_egress": 2}
    ) == {
        "total": 10,
        "eligible": 8,
        "used": 5,
        "available": 3,
        "duplicates": 2,
    }


def test_capacity_counters_do_not_invent_unknown_values():
    assert provider_automation.capacity_counters(None) == {
        "total": None,
        "eligible": None,
        "used": None,
        "available": None,
        "duplicates": None,
    }


def test_database_capacity_exposes_used_and_remaining_aliases(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "capacity.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("Pool A", "residential")
            await database.upsert_proxy_endpoints_returning_ids(
                provider_id,
                [
                    {
                        "provider_proxy_id": "a",
                        "host": "1.1.1.1",
                        "port": 1000,
                        "status": "alive",
                        "exit_ip": "198.51.100.1",
                    }
                ],
            )

            row = (await database.get_provider_proxy_capacity())[0]

            assert row["used"] == row["leased"] == 0
            assert row["remaining"] == row["available"] == 1

    asyncio.run(run())


def test_proxy_lease_reconciliation_is_read_only_and_idempotent(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "reconcile.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("Pool A", "residential")
            proxy_ids = await database.upsert_proxy_endpoints_returning_ids(
                provider_id,
                [
                    {
                        "provider_proxy_id": "a",
                        "host": "1.1.1.1",
                        "port": 1000,
                        "status": "alive",
                        "exit_ip": "198.51.100.1",
                    },
                    {
                        "provider_proxy_id": "b",
                        "host": "2.2.2.2",
                        "port": 1000,
                        "status": "alive",
                        "exit_ip": "198.51.100.2",
                    },
                ],
            )
            worker_id = await database.upsert_worker("worker-a", "worker-a", "http://worker")
            await database.save_provider_instance(
                "packetstream", "packet-a", worker_id=worker_id, mode="proxy", proxy_id=proxy_ids[0], status="running"
            )
            assert await database.lease_proxy_for_provider_instance("packetstream", worker_id, "packet-a")
            before = await database.list_provider_proxy_leases(provider_slug="packetstream")

            first = await database.reconcile_provider_proxy_leases(provider_slug="packetstream")
            second = await database.reconcile_provider_proxy_leases(provider_slug="packetstream")

            assert first == second
            assert first["active_leases"] == 1
            assert first["orphan_leases"] == []
            assert first["capacity"][0]["used"] == 1
            assert await database.list_provider_proxy_leases(provider_slug="packetstream") == before

    asyncio.run(run())
