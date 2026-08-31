from __future__ import annotations

import asyncio
import base64
import stat
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app import database, main, runtime_assets, worker_api


def test_worker_rejects_legacy_direct_runtime_asset_downloads(tmp_path):
    async def run():
        spec = worker_api.DeploySpec(
            image="img",
            runtime_assets=[
                worker_api.RuntimeAssetSpec(
                    provider="demo",
                    asset_kind="chrome_profile_zip",
                    target="/config",
                    encoding="zip",
                    url="https://assets.example/profile.zip",
                )
            ],
        )
        with (
            patch.object(worker_api, "_RUNTIME_ASSET_DIR", tmp_path),
            pytest.raises(HTTPException, match="Direct runtime asset downloads are disabled"),
        ):
            await worker_api._materialize_runtime_assets("demo", spec)

    asyncio.run(run())


def test_worker_rejects_zip_runtime_asset_materialization(tmp_path):
    async def run():
        spec = worker_api.DeploySpec(
            image="img",
            runtime_assets=[
                worker_api.RuntimeAssetSpec(
                    provider="demo", asset_kind="chrome_profile_zip", target="/config", encoding="zip"
                )
            ],
        )
        with (
            patch.object(worker_api, "_RUNTIME_ASSET_DIR", tmp_path),
            pytest.raises(HTTPException, match="ZIP runtime assets are disabled"),
        ):
            await worker_api._materialize_runtime_assets("demo", spec)

    asyncio.run(run())


def test_runtime_asset_path_uses_worker_data_mountpoint(monkeypatch):
    class Container:
        attrs = {"Mounts": [{"Destination": "/data", "Source": "/var/lib/docker/volumes/cashpilot_worker_data/_data"}]}

    class Containers:
        def get(self, container_id):
            assert container_id == "worker-container"
            return Container()

    class Client:
        containers = Containers()

    monkeypatch.setenv("HOSTNAME", "worker-container")
    monkeypatch.setenv("CASHPILOT_DATA_DIR", "/data")
    monkeypatch.setattr(worker_api.orchestrator, "_get_client", lambda: Client())

    out = worker_api._docker_host_path(Path("/data/runtime-assets/uprock/credentials_json/credentials.json"))

    assert out == Path(
        "/var/lib/docker/volumes/cashpilot_worker_data/_data/runtime-assets/uprock/credentials_json/credentials.json"
    )


class TestRuntimeAssets:
    def test_config_key_forces_secret_encryption(self):
        key = runtime_assets.config_key("demo-provider", "seed_bundle")
        assert key == "runtime_asset::demo-provider::seed_bundle::secret"
        assert database._is_secret_key(key)

    def test_asset_status_never_returns_raw_value(self, tmp_path):
        async def run():
            with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "assets.db"):
                await database.init_db()
                await database.save_runtime_asset("demo-provider", "seed_bundle", "raw-seed")
                assert await database.get_runtime_asset("demo-provider", "seed_bundle") == "raw-seed"
                rows = await database.list_runtime_assets()
                assert rows == [{"provider": "demo-provider", "asset_kind": "seed_bundle", "is_set": True}]

        asyncio.run(run())

    def test_config_sync_mirrors_runtime_assets(self):
        async def run():
            with (
                patch.object(
                    main.catalog,
                    "get_services",
                    return_value=[
                        {
                            "slug": "uprock",
                            "deploy": {"runtime_assets": [{"provider": "uprock", "asset_kind": "credentials_json"}]},
                        }
                    ],
                ),
                patch.object(database, "save_runtime_asset") as save,
            ):
                await main._sync_runtime_assets_from_config({"uprock_credentials_json": "seed"})
                save.assert_awaited_once_with("uprock", "credentials_json", "seed")

        asyncio.run(run())

    def test_uprock_file_inputs_are_masked_as_configured_secrets(self, tmp_path):
        async def run():
            with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "assets.db"):
                await database.init_db()
                await database.set_config_bulk({"uprock_credentials_json": "seed", "uprock_main_db": "db"})
                masked = await database.get_config_masked()
                assert masked["_secrets"]["uprock_credentials_json"] is True
                assert masked["_secrets"]["uprock_main_db"] is True
                assert "uprock_credentials_json" not in masked
                assert "uprock_main_db" not in masked

        asyncio.run(run())

    def test_proxybase_xyz_phrase_is_masked_as_a_secret(self, tmp_path):
        async def run():
            with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "assets.db"):
                await database.init_db()
                await database.set_config_bulk({"proxybase-xyz_phrase": "seed phrase"})
                masked = await database.get_config_masked()
                assert masked["_secrets"]["proxybase-xyz_phrase"] is True
                assert "proxybase-xyz_phrase" not in masked

        asyncio.run(run())

    def test_chrome_profile_zip_is_allowed_as_runtime_asset_kind(self):
        assert runtime_assets.validate("demo", "chrome_profile_zip") == ("demo", "chrome_profile_zip")

    def test_worker_fetches_runtime_assets_with_active_worker_key(self):
        async def run():
            seen = {}

            class Response:
                status_code = 200

                def raise_for_status(self):
                    pass

                def json(self):
                    return {"value": "seed"}

            class Client:
                def __init__(self, *args, **kwargs):
                    pass

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    return None

                async def post(self, url, *, headers, json):
                    seen["headers"] = headers
                    seen["json"] = json
                    return Response()

            with (
                patch.object(worker_api, "UI_URL", "http://ui"),
                patch.object(worker_api, "API_KEY", "shared"),
                patch.object(worker_api, "_worker_key", "own-worker-key"),
                patch.object(worker_api.httpx, "AsyncClient", Client),
            ):
                value = await worker_api._fetch_runtime_asset("uprock", "credentials_json")

            assert value == "seed"
            assert seen["headers"] == {"Authorization": "Bearer own-worker-key"}

        asyncio.run(run())

    def test_worker_materialized_file_runtime_assets_are_container_readable(self, tmp_path):
        async def run():
            spec = worker_api.DeploySpec(
                image="img",
                runtime_assets=[
                    worker_api.RuntimeAssetSpec(
                        provider="uprock",
                        asset_kind="credentials_json",
                        target="/cashpilot/runtime-assets/uprock/credentials.json",
                        encoding="text",
                    )
                ],
            )
            with (
                patch.object(worker_api, "_RUNTIME_ASSET_DIR", tmp_path),
                patch.object(worker_api, "_fetch_runtime_asset", return_value="seed"),
            ):
                await worker_api._materialize_runtime_assets("uprock", spec)

            source = Path(next(iter(spec.volumes)))
            assert source.read_text() == "seed"
            assert source.stat().st_mode & stat.S_IROTH

        asyncio.run(run())

    def test_worker_scopes_same_asset_kind_by_asset_id(self, tmp_path):
        async def run():
            specs = [
                worker_api.DeploySpec(
                    image="img",
                    runtime_assets=[
                        worker_api.RuntimeAssetSpec(
                            provider="earnapp",
                            asset_kind="mac_identity_profile",
                            asset_id=node_id,
                            target="/profile.json.enc",
                            encoding="text",
                        )
                    ],
                )
                for node_id in ("earnapp-canary-a", "earnapp-canary-b")
            ]
            with (
                patch.object(worker_api, "_RUNTIME_ASSET_DIR", tmp_path),
                patch.object(
                    worker_api,
                    "_fetch_runtime_asset",
                    side_effect=["profile-a", "profile-b"],
                ),
            ):
                await worker_api._materialize_runtime_assets("earnapp-canary", specs[0])
                await worker_api._materialize_runtime_assets("earnapp-canary", specs[1])

            sources = [Path(next(iter(spec.volumes))) for spec in specs]
            assert sources[0] != sources[1]
            assert sources[0].read_text() == "profile-a"
            assert sources[1].read_text() == "profile-b"
            assert sources[0].name == "asset"
            assert sources[1].name == "asset"

        asyncio.run(run())
