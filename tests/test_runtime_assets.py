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

    def test_proxylite_user_id_is_masked_as_a_secret(self, tmp_path):
        async def run():
            with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "assets.db"):
                await database.init_db()
                await database.set_config_bulk({"proxylite_user_id": "521465"})
                masked = await database.get_config_masked()
                assert masked["_secrets"]["proxylite_user_id"] is True
                assert "proxylite_user_id" not in masked

        asyncio.run(run())
