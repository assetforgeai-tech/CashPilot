from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app import database, earnapp_accounts, earnapp_collection, earnapp_recovery, main


def _account(profile: str) -> dict[str, object]:
    return {
        "profile_key": profile,
        "account_name": f"{profile}@example.com",
        "email": f"{profile}@example.com",
        "auth_method": "google",
        "cookies": {
            "oauth-refresh-token": {"value": "opaque-refresh-token"},
            "xsrf-token": {"value": f"xsrf-{profile}"},
        },
    }


async def _seed_proxy(
    database_module,
    provider_id: int,
    suffix: int,
    *,
    ip_type: str = "residential",
    country_code: str = "VN",
) -> int:
    (proxy_id,) = await database_module.upsert_proxy_endpoints_returning_ids(
        provider_id,
        [
            {
                "provider_proxy_id": f"proxy-{suffix}",
                "endpoint": f"10.0.0.{suffix}:10{suffix:02d}",
                "host": f"10.0.0.{suffix}",
                "port": 1000 + suffix,
                "protocol": "socks5",
                "status": "alive",
                "exit_ip": f"198.51.100.{suffix}",
                "ip_type": ip_type,
            }
        ],
    )
    await database_module.update_proxy_endpoint_intelligence(
        proxy_id,
        {
            "ip_type": ip_type,
            "ip_type_source": "test",
            "ip_type_confidence": "high",
            "country_code": country_code,
            "country_name": country_code,
            "geo_source": "test",
            "geo_confidence": "high",
        },
    )
    await database_module.save_proxy_probe_result(
        proxy_id,
        profile="earnapp_wss",
        probe_status="alive",
        verdict="CID_SET",
        eligibility="eligible",
        reason="",
        exit_ip=f"198.51.100.{suffix}",
        latency_ms=20,
        probe_version="test",
    )
    return proxy_id


async def _setup(tmp_path, proxy_count: int = 3):
    await database.init_db()
    await earnapp_accounts.import_account(_account("profile-a"))
    provider_id = await database.upsert_proxy_provider("manual", "manual")
    proxies = [await _seed_proxy(database, provider_id, index) for index in range(1, proxy_count + 1)]
    old_worker = await database.upsert_worker("worker-old", "old-worker", "http://old")
    new_worker = await database.upsert_worker("worker-new", "new-worker", "http://new")
    return old_worker, new_worker, proxies


async def _provision_node(
    logical_node_id: str,
    worker_id: int,
    *,
    device_id: str,
    platform: str = "macos",
    proxy_country_code: str = "VN",
) -> dict[str, object]:
    return await earnapp_recovery.provision_node(
        logical_node_id,
        worker_id,
        device_id=device_id,
        proxy_country_code=proxy_country_code,
        platform=platform,
    )


_provision_macos_node = _provision_node


def _db_patch(tmp_path):
    return (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", tmp_path / "earnapp.db"),
    )


def test_recovery_constants_are_fifteen_minutes_then_exactly_one_hour():
    assert earnapp_recovery.STALE_WORKER_SECONDS == 15 * 60
    assert earnapp_recovery.RECOVERY_HOLD_SECONDS == 60 * 60


def test_stale_sweep_waits_fifteen_minutes_and_holds_proxy_for_one_hour(tmp_path):
    async def run():
        db_dir, db_path = _db_patch(tmp_path)
        with db_dir, db_path:
            old_worker, _, proxies = await _setup(tmp_path)
            node = await _provision_macos_node("earnapp-node-a", old_worker, device_id="device-a")
            assert node["proxy_id"] == proxies[0]

            db = await database._get_db()
            await db.execute(
                "UPDATE workers SET status='offline', last_heartbeat=datetime('now', '-14 minutes') WHERE id=?",
                (old_worker,),
            )
            await db.commit()
            assert await earnapp_recovery.sweep_stale_nodes() == {"held": [], "released": []}

            await db.execute(
                "UPDATE workers SET last_heartbeat=datetime('now', '-16 minutes') WHERE id=?",
                (old_worker,),
            )
            await db.commit()
            swept = await earnapp_recovery.sweep_stale_nodes()
            assert swept["released"] == []
            assert [row["logical_node_id"] for row in swept["held"]] == ["earnapp-node-a"]
            held = (await database.list_earnapp_logical_nodes())[0]
            assert held["state"] == "RECOVERY_HOLD"
            started = datetime.fromisoformat(held["recovery_started_at"]).replace(tzinfo=UTC)
            until = datetime.fromisoformat(held["recovery_hold_until"]).replace(tzinfo=UTC)
            assert (until - started).total_seconds() == 3600
            lease = await database.get_active_provider_proxy_lease("earnapp", old_worker, "earnapp-node-a")
            assert lease is not None and lease["proxy_id"] == proxies[0]

    asyncio.run(run())


def test_recovery_hold_keeps_proxy_exclusive_then_preserves_affinity_after_release(tmp_path):
    async def run():
        db_dir, db_path = _db_patch(tmp_path)
        with db_dir, db_path:
            old_worker, _, proxies = await _setup(tmp_path)
            first = await _provision_macos_node("earnapp-node-a", old_worker, device_id="device-a")
            await database.begin_earnapp_recovery_hold("earnapp-node-a", hold_seconds=3600)

            other_worker = await database.upsert_worker("worker-other", "other-worker", "http://other")
            other = await _provision_macos_node("earnapp-node-b", other_worker, device_id="device-b")
            assert other["proxy_id"] != first["proxy_id"]

            db = await database._get_db()
            await db.execute(
                "UPDATE earnapp_logical_nodes SET recovery_hold_until=datetime('now', '-1 second') WHERE logical_node_id=?",
                ("earnapp-node-a",),
            )
            await db.commit()
            swept = await earnapp_recovery.sweep_stale_nodes()
            assert [row["logical_node_id"] for row in swept["released"]] == ["earnapp-node-a"]
            released = next(
                row for row in await database.list_earnapp_logical_nodes() if row["logical_node_id"] == "earnapp-node-a"
            )
            assert released["state"] == "RECOVERABLE"
            assert released["current_proxy_id"] is None
            assert released["preferred_proxy_id"] == proxies[0]

            recovered = await earnapp_recovery.claim_node(
                "earnapp-node-a",
                old_worker,
                expected_generation=first["generation"],
            )
            assert recovered["proxy_id"] == proxies[0]
            assert recovered["device_id"] == "device-a"

    asyncio.run(run())


def test_new_worker_needs_one_time_ticket_and_generation_blocks_old_worker(tmp_path):
    async def run():
        db_dir, db_path = _db_patch(tmp_path)
        with db_dir, db_path:
            old_worker, new_worker, _ = await _setup(tmp_path)
            provisioned = await _provision_macos_node("earnapp-node-a", old_worker, device_id="device-a")
            await database.begin_earnapp_recovery_hold("earnapp-node-a", hold_seconds=3600)

            with pytest.raises(earnapp_recovery.RecoveryClaimDenied, match="replacement ticket"):
                await earnapp_recovery.claim_node(
                    "earnapp-node-a",
                    new_worker,
                    expected_generation=provisioned["generation"],
                )

            ticket = await earnapp_recovery.issue_replacement_ticket("earnapp-node-a", new_worker)
            replacement = await earnapp_recovery.claim_node(
                "earnapp-node-a",
                new_worker,
                expected_generation=provisioned["generation"],
                replacement_ticket=ticket,
            )
            assert replacement["generation"] == provisioned["generation"] + 1
            assert replacement["device_id"] == "device-a"
            assert (
                await earnapp_recovery.heartbeat_node(
                    "earnapp-node-a",
                    old_worker,
                    generation=provisioned["generation"],
                    device_id=provisioned["device_id"],
                    proxy_id=provisioned["proxy_id"],
                )
                is False
            )
            assert (
                await earnapp_recovery.heartbeat_node(
                    "earnapp-node-a",
                    new_worker,
                    generation=replacement["generation"],
                    device_id=replacement["device_id"],
                    proxy_id=replacement["proxy_id"],
                )
                is True
            )

            with pytest.raises(earnapp_recovery.RecoveryClaimDenied):
                await earnapp_recovery.claim_node(
                    "earnapp-node-a",
                    new_worker,
                    expected_generation=provisioned["generation"],
                    replacement_ticket=ticket,
                )

    asyncio.run(run())


def test_original_worker_heartbeat_cancels_hold_and_revokes_an_outstanding_replacement_ticket(tmp_path):
    async def run():
        db_dir, db_path = _db_patch(tmp_path)
        with db_dir, db_path:
            old_worker, new_worker, _ = await _setup(tmp_path)
            provisioned = await _provision_macos_node("earnapp-node-a", old_worker, device_id="device-a")
            await database.begin_earnapp_recovery_hold("earnapp-node-a", hold_seconds=3600)
            ticket = await earnapp_recovery.issue_replacement_ticket("earnapp-node-a", new_worker)

            assert await earnapp_recovery.heartbeat_node(
                "earnapp-node-a",
                old_worker,
                generation=provisioned["generation"],
                device_id=provisioned["device_id"],
                proxy_id=provisioned["proxy_id"],
            )
            recovered = await database.get_earnapp_logical_node("earnapp-node-a")
            assert recovered is not None
            assert recovered["state"] == "ACTIVE"
            assert recovered["recovery_started_at"] is None
            assert recovered["recovery_hold_until"] is None

            with pytest.raises(earnapp_recovery.RecoveryClaimDenied):
                await earnapp_recovery.claim_node(
                    "earnapp-node-a",
                    new_worker,
                    expected_generation=provisioned["generation"],
                    replacement_ticket=ticket,
                )

    asyncio.run(run())


def test_heartbeat_requires_the_exact_device_and_proxy_assignment(tmp_path):
    async def run():
        db_dir, db_path = _db_patch(tmp_path)
        with db_dir, db_path:
            worker_id, _, _ = await _setup(tmp_path)
            provisioned = await earnapp_recovery.provision_node(
                "earnapp-node-a",
                worker_id,
                device_id="device-a",
            )

            assert not await earnapp_recovery.heartbeat_node(
                "earnapp-node-a",
                worker_id,
                generation=provisioned["generation"],
                device_id="device-b",
                proxy_id=provisioned["proxy_id"],
            )
            assert not await earnapp_recovery.heartbeat_node(
                "earnapp-node-a",
                worker_id,
                generation=provisioned["generation"],
                device_id=provisioned["device_id"],
                proxy_id=provisioned["proxy_id"] + 1,
            )
            assert await earnapp_recovery.heartbeat_node(
                "earnapp-node-a",
                worker_id,
                generation=provisioned["generation"],
                device_id=provisioned["device_id"],
                proxy_id=provisioned["proxy_id"],
            )

    asyncio.run(run())


def test_replacement_ticket_requires_an_existing_target_worker(tmp_path):
    async def run():
        db_dir, db_path = _db_patch(tmp_path)
        with db_dir, db_path:
            old_worker, _, _ = await _setup(tmp_path)
            await _provision_macos_node("earnapp-node-a", old_worker, device_id="device-a")
            await database.begin_earnapp_recovery_hold("earnapp-node-a", hold_seconds=3600)

            with pytest.raises(earnapp_recovery.RecoveryClaimDenied, match="target worker"):
                await earnapp_recovery.issue_replacement_ticket("earnapp-node-a", 999999)

    asyncio.run(run())


def test_new_worker_still_needs_a_ticket_after_the_one_hour_hold_expires(tmp_path):
    async def run():
        db_dir, db_path = _db_patch(tmp_path)
        with db_dir, db_path:
            old_worker, new_worker, _ = await _setup(tmp_path)
            provisioned = await _provision_macos_node("earnapp-node-a", old_worker, device_id="device-a")
            await database.begin_earnapp_recovery_hold("earnapp-node-a", hold_seconds=3600)
            db = await database._get_db()
            await db.execute(
                "UPDATE earnapp_logical_nodes SET recovery_hold_until=datetime('now', '-1 second') WHERE logical_node_id=?",
                ("earnapp-node-a",),
            )
            await db.commit()
            await earnapp_recovery.sweep_stale_nodes()

            with pytest.raises(earnapp_recovery.RecoveryClaimDenied, match="replacement ticket"):
                await earnapp_recovery.claim_node(
                    "earnapp-node-a",
                    new_worker,
                    expected_generation=provisioned["generation"],
                )

            ticket = await earnapp_recovery.issue_replacement_ticket("earnapp-node-a", new_worker)
            replacement = await earnapp_recovery.claim_node(
                "earnapp-node-a",
                new_worker,
                expected_generation=provisioned["generation"],
                replacement_ticket=ticket,
            )
            assert replacement["worker_id"] == new_worker
            assert replacement["generation"] == provisioned["generation"] + 1

    asyncio.run(run())


def test_recovery_falls_back_when_preferred_proxy_is_no_longer_healthy(tmp_path):
    async def run():
        db_dir, db_path = _db_patch(tmp_path)
        with db_dir, db_path:
            old_worker, _, proxies = await _setup(tmp_path)
            provisioned = await _provision_macos_node("earnapp-node-a", old_worker, device_id="device-a")
            await database.begin_earnapp_recovery_hold("earnapp-node-a", hold_seconds=3600)
            db = await database._get_db()
            await db.execute(
                "UPDATE earnapp_logical_nodes SET recovery_hold_until=datetime('now', '-1 second') WHERE logical_node_id=?",
                ("earnapp-node-a",),
            )
            await db.commit()
            await earnapp_recovery.sweep_stale_nodes()
            await database.update_proxy_pool_check_results({proxies[0]: "dead"})

            recovered = await earnapp_recovery.claim_node(
                "earnapp-node-a",
                old_worker,
                expected_generation=provisioned["generation"],
            )
            assert recovered["proxy_id"] == proxies[1]
            assert recovered["preferred_proxy_id"] == proxies[1]

    asyncio.run(run())


@pytest.mark.parametrize(
    ("platform", "initial_country", "incompatible_country"),
    [("macos", "VN", "US"), ("ubuntu", "US", "VN"), ("ubuntu", "US", "")],
)
def test_recovery_never_changes_the_immutable_platform_country_contract(
    tmp_path,
    platform,
    initial_country,
    incompatible_country,
):
    async def run():
        db_dir, db_path = _db_patch(tmp_path)
        with db_dir, db_path:
            await database.init_db()
            await earnapp_accounts.import_account(_account("profile-a"))
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            initial_proxy = await _seed_proxy(
                database,
                provider_id,
                1,
                country_code=initial_country,
            )
            await _seed_proxy(
                database,
                provider_id,
                2,
                country_code=incompatible_country,
            )
            worker_id = await database.upsert_worker("worker-old", "old-worker", "http://old")
            provisioned = await _provision_node(
                "earnapp-node-a",
                worker_id,
                device_id="device-a",
                platform=platform,
                proxy_country_code=initial_country,
            )
            assert provisioned["proxy_id"] == initial_proxy

            await database.begin_earnapp_recovery_hold("earnapp-node-a", hold_seconds=3600)
            db = await database._get_db()
            await db.execute(
                "UPDATE earnapp_logical_nodes SET recovery_hold_until=datetime('now', '-1 second') "
                "WHERE logical_node_id=?",
                ("earnapp-node-a",),
            )
            await db.commit()
            await earnapp_recovery.sweep_stale_nodes()
            await database.update_proxy_pool_check_results({initial_proxy: "dead"})

            with pytest.raises(earnapp_recovery.RecoveryClaimDenied, match="no proxy is available"):
                await earnapp_recovery.claim_node(
                    "earnapp-node-a",
                    worker_id,
                    expected_generation=provisioned["generation"],
                )

    asyncio.run(run())


def test_recovery_does_not_reuse_preferred_proxy_after_a_legacy_worker_claims_it(tmp_path):
    async def run():
        db_dir, db_path = _db_patch(tmp_path)
        with db_dir, db_path:
            old_worker, _, proxies = await _setup(tmp_path)
            provisioned = await _provision_macos_node("earnapp-node-a", old_worker, device_id="device-a")
            await database.begin_earnapp_recovery_hold("earnapp-node-a", hold_seconds=3600)
            db = await database._get_db()
            await db.execute(
                "UPDATE earnapp_logical_nodes SET recovery_hold_until=datetime('now', '-1 second') WHERE logical_node_id=?",
                ("earnapp-node-a",),
            )
            await db.commit()
            await earnapp_recovery.sweep_stale_nodes()

            legacy_worker = await database.upsert_worker("worker-legacy", "legacy", "http://legacy")
            assert await database.set_worker_proxy_assignment(legacy_worker, proxies[0])

            recovered = await earnapp_recovery.claim_node(
                "earnapp-node-a",
                old_worker,
                expected_generation=provisioned["generation"],
            )
            assert recovered["proxy_id"] == proxies[1]
            assert (await database.get_worker_proxy_assignment(legacy_worker))["proxy_id"] == proxies[0]

    asyncio.run(run())


def test_recovery_does_not_reuse_preferred_proxy_after_another_account_controls_it(tmp_path):
    async def run():
        db_dir, db_path = _db_patch(tmp_path)
        with db_dir, db_path:
            old_worker, _, proxies = await _setup(tmp_path)
            provisioned = await _provision_macos_node("earnapp-node-a", old_worker, device_id="device-a")
            await database.begin_earnapp_recovery_hold("earnapp-node-a", hold_seconds=3600)
            db = await database._get_db()
            await db.execute(
                "UPDATE earnapp_logical_nodes SET recovery_hold_until=datetime('now', '-1 second') WHERE logical_node_id=?",
                ("earnapp-node-a",),
            )
            await db.commit()
            await earnapp_recovery.sweep_stale_nodes()

            other_account = await earnapp_accounts.import_account(_account("profile-b"))
            route = await earnapp_collection.ensure_collection_route(other_account)
            assert route is not None and route["proxy_id"] == proxies[0]

            recovered = await earnapp_recovery.claim_node(
                "earnapp-node-a",
                old_worker,
                expected_generation=provisioned["generation"],
            )
            assert recovered["proxy_id"] == proxies[1]
            assert (await database.get_earnapp_account_control_route(other_account))["proxy_id"] == proxies[0]

    asyncio.run(run())


def test_earnapp_never_leases_a_non_residential_proxy(tmp_path):
    async def run():
        db_dir, db_path = _db_patch(tmp_path)
        with db_dir, db_path:
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            datacenter = await _seed_proxy(database, provider_id, 1, ip_type="datacenter")
            residential = await _seed_proxy(database, provider_id, 2, ip_type="residential")
            worker = await database.upsert_worker("worker-a", "worker-a", "http://a")
            lease = await database.lease_proxy_for_provider_instance("earnapp", worker, "earnapp-node-a")
            assert lease is not None
            assert lease["proxy_id"] == residential
            assert lease["proxy_id"] != datacenter

    asyncio.run(run())


def test_main_stale_worker_job_runs_earnapp_recovery_with_fifteen_minute_threshold():
    async def run():
        with (
            patch.object(database, "list_workers", AsyncMock(return_value=[])),
            patch.object(database, "reclaim_stale_nkn_wallets", AsyncMock(return_value=[])),
            patch.object(
                earnapp_recovery, "sweep_stale_nodes", AsyncMock(return_value={"held": [], "released": []})
            ) as sweep,
        ):
            await main._check_stale_workers()
        sweep.assert_awaited_once_with(stale_after_seconds=900)

    asyncio.run(run())


def test_worker_heartbeat_cas_acknowledges_only_current_earnapp_generation():
    async def run():
        body = main.WorkerHeartbeat(
            name="worker-a",
            client_id="worker-a",
            provider_states={
                "earnapp": {
                    "instances": [
                        {
                            "logical_node_id": "earnapp-node-a",
                            "generation": 4,
                            "device_id": "sdk-mac-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                            "proxy_id": 11,
                        },
                        {
                            "logical_node_id": "earnapp-node-stale",
                            "generation": 2,
                            "device_id": "sdk-mac-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                            "proxy_id": 12,
                        },
                    ]
                }
            },
        )

        def discard(coro):
            coro.close()

        with (
            patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
            patch.object(database, "upsert_worker", AsyncMock(return_value=11)),
            patch.object(
                earnapp_recovery,
                "heartbeat_node",
                AsyncMock(side_effect=[True, False]),
            ) as heartbeat,
            patch.object(database, "record_earnapp_proxy_health", AsyncMock(return_value=False)),
            patch.object(database, "confirm_worker_key", AsyncMock()),
            patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
            patch.object(main, "_spawn", side_effect=discard),
            patch.object(main.metrics, "record_heartbeat"),
        ):
            response = await main.api_worker_heartbeat(
                type("Request", (), {"headers": {"authorization": "Bearer key"}})(), body
            )

        assert response["earnapp_assignment_acks"] == [{"logical_node_id": "earnapp-node-a", "generation": 4}]
        assert response["earnapp_assignment_rejections"] == [{"logical_node_id": "earnapp-node-stale", "generation": 2}]
        assert heartbeat.await_args_list[0].args == ("earnapp-node-a", 11)
        assert heartbeat.await_args_list[0].kwargs == {
            "generation": 4,
            "device_id": "sdk-mac-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "proxy_id": 11,
        }

    asyncio.run(run())
