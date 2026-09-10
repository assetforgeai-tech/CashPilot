from __future__ import annotations

import asyncio
from unittest.mock import patch

from app import database, earnapp_accounts
from app import earnapp_collection
from tests.test_earnapp_account_pool import _payload


def test_paypal_assignment_is_fixed_and_quarantined_after_account_delete(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "paypal.db"):
            await database.init_db()
            first_account = await earnapp_accounts.import_account(_payload("paypal-a", "a@example.com"))
            second_account = await earnapp_accounts.import_account(_payload("paypal-b", "b@example.com"))
            first_paypal = await database.add_earnapp_paypal("PayoutA@example.com")
            second_paypal = await database.add_earnapp_paypal("payout-b@example.com")

            assigned = await database.assign_earnapp_paypal(first_account)
            assert assigned == {"id": first_paypal, "destination": "PayoutA@example.com"}
            assert await database.assign_earnapp_paypal(first_account) == assigned
            assert (await database.assign_earnapp_paypal(second_account))["id"] == second_paypal

            await database.set_earnapp_account_state(first_account, "ACCOUNT_LOCKED")
            assert await database.delete_locked_earnapp_account(first_account) == "DELETED"
            rows = await database.list_earnapp_paypal_pool()
            quarantined = next(row for row in rows if row["id"] == first_paypal)
            assert quarantined["state"] == "QUARANTINED"
            assert quarantined["assigned_account_id"] == first_account
            assert all("destination" not in row for row in rows)

    asyncio.run(run())


def test_collection_auto_configures_paypal_only_when_payment_is_unconfigured(monkeypatch):
    calls = []

    async def configure(account_id, **_kwargs):
        calls.append(account_id)
        return {"configured": True, "method": "paypal.com"}

    monkeypatch.setattr(earnapp_collection, "configure_payment_from_paypal_pool", configure)

    async def run():
        assert await earnapp_collection.ensure_paypal_pool_payment(7, {"payment": {}}) == {
            "configured": True,
            "method": "paypal.com",
        }
        assert await earnapp_collection.ensure_paypal_pool_payment(8, {"payment": {"configured": True}}) == {
            "configured": True
        }

    asyncio.run(run())
    assert calls == [7]
