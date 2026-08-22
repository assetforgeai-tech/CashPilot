from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app import catalog, database, main, metrics, provider_runtime
from app.retired_providers import RETIRED_PROVIDER_SLUGS

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PROVIDERS = {
    "earnfm",
    "iproyal",
    "mysterium",
    "nkn",
    "packetstream",
    "proxies-sx",
    "proxybase",
    "proxybase-xyz",
    "proxyrack",
    "repocket",
    "spide",
    "traffmonetizer",
    "uprock",
    "urnetwork",
    "wipter",
}


def _day(offset: int) -> str:
    return (datetime.now(UTC) - timedelta(days=offset)).strftime("%Y-%m-%d")


def test_current_product_provider_set_is_baseline_minus_grass():
    catalog_slugs = {service["slug"] for service in catalog.get_services()}

    assert catalog_slugs == EXPECTED_PROVIDERS
    assert set(provider_runtime.ACTIVE_SLUGS) == EXPECTED_PROVIDERS
    assert not (ROOT / "services" / "depin" / "grass.yml").exists()
    assert not (ROOT / "app" / "collectors" / "grass.py").exists()
    assert not (ROOT / "docs" / "guides" / "grass.md").exists()


def test_retired_provider_constant_has_one_authoritative_definition():
    assert main._is_retired_provider is metrics._is_retired_provider
    assert frozenset({"grass"}) == RETIRED_PROVIDER_SLUGS


def test_retired_provider_boundary_normalizes_case_and_outer_whitespace():
    for slug in ("grass", "Grass", " GRASS "):
        assert main._is_retired_provider(slug)
        assert metrics._is_retired_provider(slug)


def test_legacy_grass_config_keys_remain_masked(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "legacy.db"):
            await database.init_db()
            await database.set_config_bulk(
                {
                    "grass_store_wynd_status": "CONNECTED",
                    "grass_store_wynd_user_id": "legacy-user",
                }
            )

            masked = await database.get_config_masked()

            assert masked["_secrets"]["grass_store_wynd_status"] is True
            assert masked["_secrets"]["grass_store_wynd_user_id"] is True
            assert "grass_store_wynd_status" not in masked
            assert "grass_store_wynd_user_id" not in masked

    asyncio.run(run())


def test_removed_provider_legacy_rows_stay_stored_but_are_hidden_from_current_product(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "legacy.db"):
            await database.init_db()
            for slug in ("earnfm", "grass"):
                await database.upsert_earnings(slug, 1.0, date=_day(1))
                await database.upsert_earnings(slug, 3.0, date=_day(0))

            raw = await database.get_earnings_summary()
            assert {row["platform"] for row in raw} == {"earnfm", "grass"}

            rows = await main.api_earnings(object())
            breakdown = await main.api_earnings_breakdown(object())
            earned = main._without_retired_provider_values(await database.get_earned_by_platform(days=2))

            assert {row["platform"] for row in rows} == {"earnfm"}
            assert {row["platform"] for row in breakdown} == {"earnfm"}
            assert set(earned) == {"earnfm"}

    with (
        patch.object(main, "_require_auth_api", lambda request: {"uid": 1}),
        patch.object(main, "_require_reader", lambda request: {"uid": 1}),
    ):
        asyncio.run(run())


def test_worker_and_alert_views_hide_removed_provider_without_mutating_worker_state():
    worker = {
        "id": 7,
        "client_id": "worker-a",
        "name": "worker-a",
        "status": "online",
        "containers": json.dumps(
            [
                {"slug": "grass", "status": "running"},
                {"slug": "earnfm", "status": "running"},
            ]
        ),
        "apps": "[]",
        "system_info": json.dumps({"docker_available": True}),
        "key_issued_at": None,
        "key_confirmed": False,
    }

    async def run():
        main._collector_alerts = [
            {"kind": "collector", "platform": "grass", "error": "legacy"},
            {"kind": "collector", "platform": "earnfm", "error": "current"},
        ]
        listed = await main.api_list_workers(object())
        alerts = await main.api_collector_alerts(object())

        assert [row["slug"] for row in listed[0]["containers"]] == ["earnfm"]
        assert listed[0]["container_count"] == 1
        assert [row["platform"] for row in alerts["alerts"]] == ["earnfm"]

    with (
        patch.object(main, "_require_auth_api", lambda request: {"uid": 1}),
        patch.object(main.database, "list_workers", new_callable=AsyncMock, return_value=[worker]),
        patch.object(main.database, "get_config", new_callable=AsyncMock, return_value={}),
        patch.object(main, "_worker_provider_states", new_callable=AsyncMock, return_value={}),
    ):
        asyncio.run(run())


def test_legacy_grass_is_excluded_from_dashboard_total_and_daily_chart(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "legacy.db"):
            await database.init_db()
            for slug, before, after in (("earnfm", 1.0, 3.0), ("grass", 10.0, 20.0)):
                await database.upsert_earnings(slug, before, date=_day(1))
                await database.upsert_earnings(slug, after, date=_day(0))

            summary = await main.api_earnings_summary(object())
            daily = await main.api_earnings_daily(object(), days=2)

            assert summary["total"] == 3.0
            assert daily[-1]["amount"] == 2.0

    with (
        patch.object(main, "_require_reader", lambda request: {"uid": 1}),
        patch.object(main, "_require_auth_api", lambda request: {"uid": 1}),
        patch.object(main, "api_services_deployed", new_callable=AsyncMock, return_value=[]),
        patch.object(database, "get_config", new_callable=AsyncMock, return_value={}),
    ):
        asyncio.run(run())


def test_earnings_filters_keep_allowlist_compatibility_and_support_retired_exclusions(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "legacy.db"):
            await database.init_db()
            for slug, before, after in (
                ("earnfm", 1.0, 3.0),
                ("grass", 10.0, 20.0),
                ("integration-fixture", 4.0, 7.0),
            ):
                await database.upsert_earnings(slug, before, date=_day(1))
                await database.upsert_earnings(slug, after, date=_day(0))

            allowlisted = await database.get_earnings_dashboard_summary(platforms={"earnfm"})
            excluded = await database.get_earnings_dashboard_summary(excluded_platforms={"grass"})

            assert allowlisted["total"] == 3.0
            assert excluded["total"] == 10.0

    asyncio.run(run())


def test_dashboard_exclusion_is_case_insensitive_for_legacy_provider_rows(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "legacy.db"):
            await database.init_db()
            await database.upsert_earnings("Grass", 10.0, date=_day(1))
            await database.upsert_earnings("Grass", 20.0, date=_day(0))
            await database.upsert_earnings("earnfm", 1.0, date=_day(1))
            await database.upsert_earnings("earnfm", 3.0, date=_day(0))

            summary = await database.get_earnings_dashboard_summary(excluded_platforms={"grass"})
            daily = await database.get_daily_earnings(days=2, excluded_platforms={"grass"})

            assert summary["total"] == 3.0
            assert daily[-1]["amount"] == 2.0

    asyncio.run(run())


def test_health_check_ignores_legacy_grass_deployments():
    async def run():
        events = []
        with (
            patch.object(main, "_get_all_worker_containers", new_callable=AsyncMock, return_value=[]),
            patch.object(
                main.database,
                "list_workers",
                new_callable=AsyncMock,
                return_value=[
                    {"status": "online", "system_info": json.dumps({"docker_available": True}), "name": "worker"}
                ],
            ),
            patch.object(
                main.database,
                "get_deployments",
                new_callable=AsyncMock,
                return_value=[{"slug": "grass", "status": "running"}, {"slug": "earnfm", "status": "running"}],
            ),
            patch.object(
                main.database,
                "record_health_events",
                new_callable=AsyncMock,
                side_effect=lambda value: events.extend(value),
            ),
        ):
            await main._run_health_check()

        assert all(event[0] != "grass" for event in events)
        assert any(event[0] == "earnfm" for event in events)

    asyncio.run(run())


def test_retired_filter_does_not_turn_the_catalog_into_a_generic_data_allowlist():
    rows = [
        {"platform": "grass", "balance": 1.0},
        {"platform": "integration-fixture", "balance": 2.0},
    ]

    assert main._without_retired_provider_rows(rows) == [{"platform": "integration-fixture", "balance": 2.0}]


def test_collection_history_does_not_count_legacy_grass_as_a_run():
    async def run():
        main._collection_has_run = False
        with (
            patch.object(main.database, "list_alerts", new_callable=AsyncMock, return_value=[]),
            patch.object(
                main.database,
                "get_earnings_summary",
                new_callable=AsyncMock,
                return_value=[{"platform": "grass", "balance": 1.0}],
            ),
        ):
            await main._warm_collector_alerts()
        assert main._collection_has_run is False

    asyncio.run(run())


def test_worker_earnings_hide_case_variants_of_retired_grass():
    async def run():
        body = main.WorkerHeartbeat(
            name="worker",
            containers=[{"slug": "Grass"}, {"slug": "earnfm"}],
        )
        with (
            patch.object(
                database,
                "get_earned_by_platform",
                new_callable=AsyncMock,
                return_value={"grass": 99.0, "earnfm": 2.5},
            ),
            patch.object(database, "list_workers", new_callable=AsyncMock, return_value=[]),
        ):
            result = await main._earnings_for_worker(body)

        assert [row["slug"] for row in result["platforms"]] == ["earnfm"]
        assert result["total_usd"] == 2.5

    asyncio.run(run())


def test_official_deploy_endpoint_rejects_removed_provider():
    async def run():
        return await main.api_deploy(
            object(),
            "grass",
            main.DeployRequest(env={}),
            worker_id=7,
            _auth={"uid": 1},
        )

    with patch.object(main, "_resolve_worker_id", AsyncMock(return_value=7)):
        try:
            asyncio.run(run())
        except main.HTTPException as exc:
            assert exc.status_code == 404
            assert "not found" in exc.detail
        else:
            raise AssertionError("removed provider deploy was accepted")


def test_runtime_asset_operational_surfaces_hide_and_reject_retired_grass():
    async def run():
        request = object()
        with (
            patch.object(main, "_require_owner", lambda _request: {"uid": 1}),
            patch.object(
                database,
                "list_runtime_assets",
                new_callable=AsyncMock,
                return_value=[
                    {"provider": "grass", "asset_kind": "chrome_profile_zip", "is_set": True},
                    {"provider": "uprock", "asset_kind": "credentials_json", "is_set": True},
                ],
            ),
        ):
            listed = await main.api_runtime_assets_list(request)
        assert listed == [{"provider": "uprock", "asset_kind": "credentials_json", "is_set": True}]

        with patch.object(main, "_require_owner", lambda _request: {"uid": 1}):
            try:
                await main.api_runtime_asset_save(
                    request,
                    main.RuntimeAssetSaveRequest(provider="grass", asset_kind="seed_bundle", value="legacy"),
                )
            except main.HTTPException as exc:
                assert exc.status_code == 404
            else:
                raise AssertionError("retired Grass runtime asset was accepted")

        with (
            patch.object(main, "_require_confirmed_worker", new_callable=AsyncMock),
            patch.object(database, "get_runtime_asset", new_callable=AsyncMock) as get_asset,
        ):
            try:
                await main.api_worker_runtime_asset(
                    request,
                    main.RuntimeAssetRequest(client_id="worker", provider="grass", asset_kind="seed_bundle"),
                )
            except main.HTTPException as exc:
                assert exc.status_code == 404
            else:
                raise AssertionError("retired Grass runtime asset was fetched")
            get_asset.assert_not_awaited()

    asyncio.run(run())


def test_payout_mutations_cannot_change_retired_grass_history():
    async def run():
        request = object()
        with (
            patch.object(main, "_require_writer", lambda _request: {"uid": 1}),
            patch.object(
                database,
                "get_payouts",
                new_callable=AsyncMock,
                return_value=[{"id": 41, "platform": "grass", "confirmed": 0}],
            ),
            patch.object(database, "confirm_payout", new_callable=AsyncMock) as confirm,
            patch.object(database, "reject_payout", new_callable=AsyncMock) as reject,
        ):
            for handler, kwargs in (
                (main.api_confirm_payout, {"method": ""}),
                (main.api_reject_payout, {}),
            ):
                try:
                    await handler(request, payout_id=41, **kwargs)
                except main.HTTPException as exc:
                    assert exc.status_code == 404
                else:
                    raise AssertionError("retired Grass payout mutation was accepted")

            confirm.assert_not_awaited()
            reject.assert_not_awaited()

    asyncio.run(run())
