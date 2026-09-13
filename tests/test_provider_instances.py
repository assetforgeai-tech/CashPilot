from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

from app import database, main


def _request(path: str) -> Request:
    return Request({"type": "http", "method": "POST", "path": path, "headers": []})


def test_wipter_migration_commits_instance_only_after_worker_success(monkeypatch):
    lease = {"proxy_id": 7, "exit_ip": "1.2.3.4", "host": "proxy", "port": 1080, "protocol": "socks5"}
    monkeypatch.setattr(main, "_require_owner", lambda request: {})
    monkeypatch.setattr(database, "lease_proxy_for_provider_instance", AsyncMock(return_value=lease))
    monkeypatch.setattr(database, "release_proxy_for_provider_instance", AsyncMock())
    monkeypatch.setattr(database, "save_provider_instance", AsyncMock())
    monkeypatch.setattr(
        main,
        "_proxy_to_worker",
        AsyncMock(return_value={"ok": True, "container_id": "new", "observed_egress_ip": "1.2.3.4"}),
    )

    result = asyncio.run(
        main.api_migrate_wipter_proxy(
            _request("/api/admin/providers/wipter/migrate-proxy"), main.WipterMigrationRequest(worker_id=3)
        )
    )

    assert result["status"] == "migrated"
    database.save_provider_instance.assert_awaited_once()
    database.release_proxy_for_provider_instance.assert_not_awaited()


def test_wipter_migration_releases_lease_when_worker_fails(monkeypatch):
    monkeypatch.setattr(main, "_require_owner", lambda request: {})
    monkeypatch.setattr(
        database,
        "lease_proxy_for_provider_instance",
        AsyncMock(return_value={"proxy_id": 7, "exit_ip": "1.2.3.4"}),
    )
    release = AsyncMock()
    monkeypatch.setattr(database, "release_proxy_for_provider_instance", release)
    monkeypatch.setattr(main, "_proxy_to_worker", AsyncMock(side_effect=RuntimeError("worker failed")))

    try:
        asyncio.run(
            main.api_migrate_wipter_proxy(
                _request("/api/admin/providers/wipter/migrate-proxy"), main.WipterMigrationRequest(worker_id=3)
            )
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("worker failure must propagate")

    release.assert_awaited_once_with("wipter", 3, "wipter-proxy", reason="MIGRATION_FAILED")


def test_provider_instances_round_trip_and_encrypt_spec(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "instances.db"):
            await database.init_db()
            worker_id = await database.upsert_worker("worker-a", "worker-a", "http://worker")
            await database.save_provider_instance(
                slug="earnfm",
                instance_id="earnfm-direct",
                worker_id=worker_id,
                mode="direct",
                container_id="cid",
                status="running",
                spec={"image": "fazalfarhan01/earnfm-client:latest", "env": {"EARNFM_PASSWORD": "secret"}},
            )

            rows = await database.list_provider_instances()
            assert rows[0]["instance_id"] == "earnfm-direct"
            assert rows[0]["mode"] == "direct"
            assert "secret" not in rows[0]["spec_encrypted"]
            assert await database.get_provider_instance("earnfm-direct")
            assert (await database.get_provider_instance_spec("earnfm-direct"))["env"]["EARNFM_PASSWORD"] == "secret"

    asyncio.run(run())


def test_provider_instances_filter_by_worker_and_slug(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "instances.db"):
            await database.init_db()
            worker_a = await database.upsert_worker("worker-a", "worker-a", "http://a")
            worker_b = await database.upsert_worker("worker-b", "worker-b", "http://b")
            await database.save_provider_instance("earnfm", "earnfm-direct", worker_id=worker_a, mode="direct")
            await database.save_provider_instance("earnfm", "earnfm-proxy", worker_id=worker_b, mode="proxy")
            await database.save_provider_instance(
                "demo-provider", "demo-provider-proxy", worker_id=worker_a, mode="proxy"
            )

            assert [r["instance_id"] for r in await database.list_provider_instances(slug="earnfm")] == [
                "earnfm-direct",
                "earnfm-proxy",
            ]
            assert [r["instance_id"] for r in await database.list_provider_instances(worker_id=worker_a)] == [
                "demo-provider-proxy",
                "earnfm-direct",
            ]

    asyncio.run(run())


def test_earnapp_missing_runtime_requires_two_authoritative_heartbeats_before_cleanup(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "instances.db"):
            await database.init_db()
            worker_id = await database.upsert_worker("worker-a", "worker-a", "http://worker")
            await database.save_provider_instance(
                "earnapp",
                "earnapp-stale-node",
                worker_id=worker_id,
                mode="proxy",
                container_id="old-container",
                status="verification_pending",
            )
            await database.save_provider_instance(
                "earnfm",
                "earnfm-live-node",
                worker_id=worker_id,
                mode="proxy",
                container_id="other-container",
                status="running",
            )

            first = await database.reconcile_earnapp_provider_instances(
                worker_id,
                reported_instance_ids=(),
                inventory_confirmed=True,
            )
            assert first == {"marked_missing": ["earnapp-stale-node"], "removed": []}
            assert (await database.get_provider_instance("earnapp-stale-node"))["status"] == "missing_once"

            second = await database.reconcile_earnapp_provider_instances(
                worker_id,
                reported_instance_ids=(),
                inventory_confirmed=True,
            )
            assert second == {"marked_missing": [], "removed": ["earnapp-stale-node"]}
            assert await database.get_provider_instance("earnapp-stale-node") is None
            assert await database.get_provider_instance("earnfm-live-node") is not None

    asyncio.run(run())


def test_earnapp_runtime_reappearance_cancels_missing_cleanup(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "instances.db"):
            await database.init_db()
            worker_id = await database.upsert_worker("worker-a", "worker-a", "http://worker")
            await database.save_provider_instance(
                "earnapp",
                "earnapp-live-node",
                worker_id=worker_id,
                container_id="container-a",
                status="verification_pending",
            )

            await database.reconcile_earnapp_provider_instances(
                worker_id,
                reported_instance_ids=(),
                inventory_confirmed=True,
            )
            result = await database.reconcile_earnapp_provider_instances(
                worker_id,
                reported_instance_ids=("earnapp-live-node",),
                inventory_confirmed=True,
            )

            assert result == {"marked_missing": [], "removed": []}
            assert (await database.get_provider_instance("earnapp-live-node"))["status"] == "verification_pending"

    asyncio.run(run())


def test_unconfirmed_container_inventory_never_marks_earnapp_runtime_missing(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "instances.db"):
            await database.init_db()
            worker_id = await database.upsert_worker("worker-a", "worker-a", "http://worker")
            await database.save_provider_instance(
                "earnapp",
                "earnapp-live-node",
                worker_id=worker_id,
                container_id="container-a",
                status="running",
            )

            result = await database.reconcile_earnapp_provider_instances(
                worker_id,
                reported_instance_ids=(),
                inventory_confirmed=False,
            )

            assert result == {"marked_missing": [], "removed": []}
            assert (await database.get_provider_instance("earnapp-live-node"))["status"] == "running"

    asyncio.run(run())


def test_generic_provider_missing_runtime_requires_two_confirmed_inventories(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "generic.db"):
            await database.init_db()
            worker_id = await database.upsert_worker("worker-a", "worker-a", "http://worker")
            await database.save_provider_instance(
                "earnfm",
                "earnfm-proxy-w1-proxy-001",
                worker_id=worker_id,
                mode="proxy",
                container_id="old-container",
                status="running",
            )

            first = await database.reconcile_provider_instances(
                worker_id,
                reported_instance_ids=(),
                inventory_confirmed=True,
            )
            assert first == {"marked_missing": ["earnfm-proxy-w1-proxy-001"], "removed": []}
            assert (await database.get_provider_instance("earnfm-proxy-w1-proxy-001"))["status"] == "missing_once"

            second = await database.reconcile_provider_instances(
                worker_id,
                reported_instance_ids=(),
                inventory_confirmed=True,
            )
            assert second == {"marked_missing": [], "removed": ["earnfm-proxy-w1-proxy-001"]}
            assert await database.get_provider_instance("earnfm-proxy-w1-proxy-001") is None

    asyncio.run(run())


def test_generic_runtime_reappearance_cancels_cleanup_and_keeps_proxy_lease(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "generic.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            (proxy_id,) = await database.upsert_proxy_endpoints_returning_ids(
                provider_id, [{"provider_proxy_id": "one", "host": "1.1.1.1", "port": 1000}]
            )
            await database.save_proxy_probe_result(
                proxy_id,
                profile="generic",
                probe_status="alive",
                verdict="ALIVE",
                eligibility="eligible",
                reason="",
                exit_ip="8.8.8.8",
                latency_ms=10,
                probe_version="test",
            )
            worker_id = await database.upsert_worker("worker-a", "worker-a", "http://worker")
            instance_id = "earnfm-proxy-w1-proxy-001"
            lease = await database.lease_proxy_for_provider_instance("earnfm", worker_id, instance_id)
            assert lease
            await database.save_provider_instance(
                "earnfm",
                instance_id,
                worker_id=worker_id,
                mode="proxy",
                proxy_id=proxy_id,
                status="running",
            )

            await database.reconcile_provider_instances(
                worker_id,
                reported_instance_ids=(),
                inventory_confirmed=True,
            )
            result = await database.reconcile_provider_instances(
                worker_id,
                reported_instance_ids=(instance_id,),
                inventory_confirmed=True,
            )

            assert result == {"marked_missing": [], "removed": []}
            assert (await database.get_provider_instance(instance_id))["status"] == "verification_pending"
            assert await database.get_active_provider_proxy_lease("earnfm", worker_id, instance_id)

    asyncio.run(run())


def test_generic_reconciliation_excludes_earnapp_and_unconfirmed_inventory(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "safe.db"):
            await database.init_db()
            worker_id = await database.upsert_worker("worker-a", "worker-a", "http://worker")
            await database.save_provider_instance(
                "earnapp", "earnapp-node", worker_id=worker_id, mode="proxy", status="running"
            )
            await database.save_provider_instance(
                "earnfm", "earnfm-node", worker_id=worker_id, mode="direct", status="running"
            )

            result = await database.reconcile_provider_instances(
                worker_id,
                reported_instance_ids=(),
                inventory_confirmed=False,
            )
            assert result == {"marked_missing": [], "removed": []}
            assert (await database.get_provider_instance("earnfm-node"))["status"] == "running"

            await database.reconcile_provider_instances(
                worker_id,
                reported_instance_ids=(),
                inventory_confirmed=True,
            )
            assert (await database.get_provider_instance("earnapp-node"))["status"] == "running"

    asyncio.run(run())
