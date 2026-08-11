from __future__ import annotations

import asyncio
from unittest.mock import patch

from app import database, main, runtime_assets


class TestRuntimeAssets:
    def test_config_key_forces_secret_encryption(self):
        key = runtime_assets.config_key("grass", "seed_bundle")
        assert key == "runtime_asset::grass::seed_bundle::secret"
        assert database._is_secret_key(key)

    def test_asset_status_never_returns_raw_value(self, tmp_path):
        async def run():
            with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "assets.db"):
                await database.init_db()
                await database.save_runtime_asset("grass", "seed_bundle", "raw-seed")
                assert await database.get_runtime_asset("grass", "seed_bundle") == "raw-seed"
                rows = await database.list_runtime_assets()
                assert rows == [{"provider": "grass", "asset_kind": "seed_bundle", "is_set": True}]

        asyncio.run(run())

    def test_config_sync_mirrors_runtime_assets(self):
        async def run():
            with patch.object(main.catalog, "get_services", return_value=[{"slug": "uprock", "deploy": {"runtime_assets": [{"provider": "uprock", "asset_kind": "credentials_json"}]}}]), patch.object(database, "save_runtime_asset") as save:
                await main._sync_runtime_assets_from_config({"uprock_credentials_json": "seed"})
                save.assert_awaited_once_with("uprock", "credentials_json", "seed")

        asyncio.run(run())
