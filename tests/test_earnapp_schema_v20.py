"""Schema contracts that keep EarnApp logical-node identity immutable."""

from __future__ import annotations

import asyncio
import sqlite3
from unittest.mock import patch

import pytest

from app import database, earnapp_accounts


def _payload(profile_key: str, email: str) -> dict:
    return {
        "profile_key": profile_key,
        "account_name": email,
        "email": email,
        "auth_method": "google",
        "cookies": {"oauth-refresh-token": "refresh", "xsrf-token": "xsrf"},
    }


def test_schema_persists_platform_and_rejects_platform_change(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account = await earnapp_accounts.import_account(_payload("profile-platform", "platform@example.com"))

            first = await database.assign_earnapp_account("earnapp-platform-node", platform="macos")
            assert first["id"] == account
            node = await database.get_earnapp_logical_node("earnapp-platform-node")
            assert node is not None
            assert node["platform"] == "macos"

            with pytest.raises(ValueError, match="platform"):
                await database.assign_earnapp_account("earnapp-platform-node", platform="ios")

    asyncio.run(run())


def test_non_empty_device_ids_are_unique_but_legacy_empty_ids_are_allowed(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            first = await earnapp_accounts.import_account(_payload("profile-device-a", "a@example.com"))
            second = await earnapp_accounts.import_account(_payload("profile-device-b", "b@example.com"))
            db = await database._get_db()
            try:
                await db.execute(
                    "INSERT INTO earnapp_logical_nodes (logical_node_id, account_id, platform, device_id) VALUES (?, ?, ?, ?)",
                    ("device-node-a", first, "macos", "sdk-mac-unique-device"),
                )
                await db.execute(
                    "INSERT INTO earnapp_logical_nodes (logical_node_id, account_id, platform, device_id) VALUES (?, ?, ?, ?)",
                    ("device-node-empty", second, "ubuntu", ""),
                )
                await db.commit()
                with pytest.raises(sqlite3.IntegrityError):
                    await db.execute(
                        "INSERT INTO earnapp_logical_nodes (logical_node_id, account_id, platform, device_id) VALUES (?, ?, ?, ?)",
                        ("device-node-b", second, "ios", "sdk-mac-unique-device"),
                    )
            finally:
                await db.close()

    asyncio.run(run())


def test_schema_upgrade_preserves_existing_node_identity_and_lease_columns(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account = await earnapp_accounts.import_account(_payload("profile-migrate", "migrate@example.com"))
            db = await database._get_db()
            try:
                await db.execute(
                    "INSERT INTO earnapp_logical_nodes (logical_node_id, account_id, state, generation, device_id, current_proxy_id, preferred_proxy_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("migration-node", account, "ACTIVE", 7, "sdk-mac-preserved", None, None),
                )
                await db.execute("PRAGMA user_version = 19")
                await db.commit()
            finally:
                await db.close()

            await database.init_db()
            node = await database.get_earnapp_logical_node("migration-node")
            assert node is not None
            assert node["generation"] == 7
            assert node["device_id"] == "sdk-mac-preserved"
            assert node["platform"] == "unknown"

    asyncio.run(run())
