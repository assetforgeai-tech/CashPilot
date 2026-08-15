from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app import database, main


def test_changed_deploy_credentials_mark_only_matching_deployed_provider(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "settings.db"):
            await database.init_db()
            await database.save_deployment("grass", "container-1", status="running", spec={"image": "grass"})
            await database.save_deployment("proxies-sx", "container-2", status="running", spec={"image": "proxies-sx"})

            changed = main._changed_credential_sections(
                {
                    "grass_store_access_token": "new-token",
                    "proxies-sx_api_key": "collector-only",
                }
            )
            await main._mark_redeploy_needed_for_config_change(changed)

            grass = await database.get_deployment("grass")
            proxies_sx = await database.get_deployment("proxies-sx")
            assert grass["status"] == "needs_redeploy"
            assert proxies_sx["status"] == "needs_redeploy"

    asyncio.run(run())


def test_dashboard_and_collector_credentials_do_not_mark_redeploy():
    changed = main._changed_credential_sections(
        {
            "proxybase_dashboard_access_token": "dashboard-token",
            "proxies-sx_api_key": "collector-token",
        }
    )

    assert changed["deploy"] == {"proxies-sx"}
    assert changed["dashboard"] == {"proxybase"}
    assert changed["collector"] == {"proxies-sx"}


def test_config_save_normalizes_legacy_importer_keys():
    normalized = main._normalize_config_update(
        {
            "iproyalpawns_email": "user@example.com",
            "proxies_sx_api_key": "psx-token",
            "repocket_rp_api_key": "rp-key",
            "myst_mmn_api_key": "mmn-key",
        }
    )

    assert normalized == {
        "iproyal_email": "user@example.com",
        "proxies-sx_api_key": "psx-token",
        "repocket_api_key": "rp-key",
        "mysterium_mmn_api_key": "mmn-key",
    }

def test_credential_health_reports_age_without_values(tmp_path):
    async def run():
        with (
            patch.object(database, "DB_DIR", tmp_path),
            patch.object(database, "DB_PATH", tmp_path / "settings.db"),
            patch.object(main, "_require_auth_api", lambda request: {"uid": 1}),
        ):
            await database.init_db()
            await database.set_config_bulk(
                {
                    "earnapp_oauth_token": "secret-token",
                    "grass_access_token": "grass-token",
                }
            )
            old = (datetime.now(UTC) - timedelta(hours=25)).replace(tzinfo=None).isoformat(sep=" ")
            db = await database._get_db()
            try:
                await db.execute("UPDATE config SET updated_at = ? WHERE key = ?", (old, "earnapp_oauth_token"))
                await db.commit()
            finally:
                await db.close()

            rows = await main.api_credential_health(object())
            by_key = {(row["service"], row["field"]): row for row in rows}
            assert by_key[("earnapp", "oauth_token")]["status"] == "no_known_expiry"
            assert by_key[("grass", "access_token")]["status"] == "no_known_expiry"
            assert "secret-token" not in str(rows)
            assert "grass-token" not in str(rows)

    asyncio.run(run())


def test_credential_health_marks_expiring_credentials(tmp_path):
    fake_service = {
        "slug": "demo",
        "name": "Demo",
        "collector": {
            "credentials": [
                {
                    "key": "session_cookie",
                    "label": "Session cookie",
                    "kind": "cookie",
                    "expires_hours": 10,
                }
            ]
        },
    }

    async def run():
        with (
            patch.object(database, "DB_DIR", tmp_path),
            patch.object(database, "DB_PATH", tmp_path / "settings.db"),
            patch.object(main, "_require_auth_api", lambda request: {"uid": 1}),
            patch.object(main.catalog, "get_services", return_value=[fake_service]),
            patch.object(main.catalog, "get_service", return_value=fake_service),
        ):
            await database.init_db()
            await database.set_config_bulk({"demo_session_cookie": "secret-cookie"})
            old = (datetime.now(UTC) - timedelta(hours=11)).replace(tzinfo=None).isoformat(sep=" ")
            db = await database._get_db()
            try:
                await db.execute("UPDATE config SET updated_at = ? WHERE key = ?", (old, "demo_session_cookie"))
                await db.commit()
            finally:
                await db.close()

            rows = await main.api_credential_health(object())
            assert rows[0]["status"] == "likely_expired"
            assert rows[0]["expected_lifetime_hours"] == 10
            assert "secret-cookie" not in str(rows)

    asyncio.run(run())

def test_credential_health_dedupes_shared_keys_across_sections(tmp_path):
    fake_service = {
        "slug": "traffmonetizer",
        "name": "Traffmonetizer",
        "collector": {
            "credentials": [
                {
                    "key": "token",
                    "label": "Token",
                    "kind": "token",
                    "required": True,
                    "description": "collector token",
                }
            ]
        },
            "deploy": {
                "credentials": [
                    {
                        "key": "token",
                        "label": "Token",
                        "kind": "token",
                        "required": True,
                        "description": "deploy token",
                    },
                ]
            },
        }

    async def run():
        with (
            patch.object(database, "DB_DIR", tmp_path),
            patch.object(database, "DB_PATH", tmp_path / "settings.db"),
            patch.object(main, "_require_auth_api", lambda request: {"uid": 1}),
            patch.object(main.catalog, "get_services", return_value=[fake_service]),
            patch.object(main.catalog, "get_service", return_value=fake_service),
        ):
            await database.init_db()
            await database.set_config_bulk({"traffmonetizer_token": "token"})
            rows = await main.api_credential_health(object())
            assert [(row["service"], row["field"]) for row in rows] == [("traffmonetizer", "token")]

    asyncio.run(run())

def test_startup_backfills_deploy_only_and_dashboard_only_tracking_rows(tmp_path):
    deploy_only = {
        "slug": "proxylite",
        "deploy": {"credentials": [{"key": "user_id", "required": True}]},
    }
    dashboard_only = {
        "slug": "dashboard-only",
        "dashboard": {"credentials": [{"key": "dashboard_session", "required": False}]},
    }

    async def run():
        with (
            patch.object(database, "DB_DIR", tmp_path),
            patch.object(database, "DB_PATH", tmp_path / "settings.db"),
            patch.object(main.catalog, "get_services", return_value=[deploy_only, dashboard_only]),
            patch.object(main.catalog, "get_service", side_effect=lambda slug: {"proxylite": deploy_only, "dashboard-only": dashboard_only}.get(slug)),
        ):
            await database.init_db()
            await database.set_config_bulk(
                {
                    "proxylite_user_id": "user-1",
                    "dashboard-only_dashboard_session": "session",
                }
            )

            tracked = await main._track_fully_configured_services()

            assert tracked == 2
            assert (await database.get_deployment("proxylite"))["status"] == "external"
            assert (await database.get_deployment("dashboard-only"))["status"] == "external"

    asyncio.run(run())

def test_saving_deploy_only_credentials_tracks_that_service(tmp_path):
    svc = {
        "slug": "proxybase-xyz",
        "deploy": {"credentials": [{"key": "phrase", "required": True}]},
    }

    async def run():
        with (
            patch.object(database, "DB_DIR", tmp_path),
            patch.object(database, "DB_PATH", tmp_path / "settings.db"),
            patch.object(main.catalog, "get_service", return_value=svc),
        ):
            await database.init_db()
            await database.set_config_bulk({"proxybase-xyz_phrase": "phrase"})

            assert main._service_tracking_ready("proxybase-xyz", await database.get_config())

    asyncio.run(run())

def test_collectors_meta_carries_runtime_contract_for_all_providers():
    async def run():
        with patch.object(main, "_require_owner", lambda request: {"uid": 1}):
            rows = await main.api_collectors_meta(object())
            by_slug = {row["slug"]: row for row in rows}
            assert len(by_slug) == 18
            assert by_slug["proxylite"]["count_only"] is True
            assert by_slug["proxybase"]["manual_only"] is True
            assert by_slug["bitping"]["manual_only"] is False
            assert by_slug["earnfm"]["supported_modes"] == ["direct", "proxy"]

    asyncio.run(run())
