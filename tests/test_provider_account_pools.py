from __future__ import annotations

import asyncio
from unittest.mock import patch

from app import database, provider_accounts


def test_account_pool_summary_uses_provider_adapters_without_exposing_secrets(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "accounts.db"):
            await database.init_db()
            await database.upsert_earnapp_account(
                profile_key="profile-a",
                account_name="a@example.com",
                email="a@example.com",
                auth_method="google",
                credentials={"cookies": {"oauth-refresh-token": "secret"}},
                credential_keys=["oauth-refresh-token"],
                token_expires_at=None,
                cookie_expires_at=None,
            )
            pools = await provider_accounts.list_provider_account_pools()
            earnapp = next(row for row in pools if row["provider"] == "earnapp")
            assert earnapp["total"] == 1
            assert earnapp["active"] == 1
            assert "credentials" not in earnapp
            assert any(row["provider"] == "nkn" and row["adapter"] == "none" for row in pools)

    asyncio.run(run())
