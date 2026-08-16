from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import database
from app.main import app


@asynccontextmanager
async def _noop_lifespan(app_):
    yield


app.router.lifespan_context = _noop_lifespan


def _owner():
    return {"uid": 1, "u": "admin", "r": "owner"}


@pytest.fixture
def isolated_db(tmp_path):
    async def setup():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
            await database.init_db()
            yield

    gen = setup()
    asyncio.run(gen.__anext__())
    try:
        yield
    finally:
        try:
            asyncio.run(gen.__anext__())
        except StopAsyncIteration:
            pass


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_import_lists_masked_earnapp_account(isolated_db, client):
    raw = '{"oauth_refresh_token":"refresh","oauth_token":"token","xsrf_token":"xsrf","brd_sess_id":"sess","cg_uuid":"uuid"}'
    with patch("app.deps.auth.get_current_user", return_value=_owner()):
        resp = client.post("/api/admin/earnapp-accounts/import", json={"file_name": "assetforgeai.gmail.com.txt", "raw": raw})
        listed = client.get("/api/admin/earnapp-accounts")

    assert resp.status_code == 200
    assert listed.status_code == 200
    row = listed.json()["accounts"][0]
    assert row["account_name"] == "assetforgeai.gmail.com"
    assert row["state"] == "VALID"
    assert row["assigned_nodes"] == 0
    assert "oauth_token" not in row
    assert listed.json()["counts"]["total"] == 1


def test_earnapp_leases_are_balanced_and_skip_disabled(isolated_db):
    async def run():
        await database.upsert_earnapp_account("a@example.com", "oauth_token=a\nxsrf_token=x")
        await database.upsert_earnapp_account("b@example.com", "oauth_token=b\nxsrf_token=x")
        first = await database.lease_earnapp_account(1, "earnapp.proxy.1")
        second = await database.lease_earnapp_account(2, "earnapp.proxy.2")
        await database.update_earnapp_account_state(first["account_id"], "DISABLED")
        sticky = await database.lease_earnapp_account(1, "earnapp.proxy.1")
        third = await database.lease_earnapp_account(3, "earnapp.proxy.3")
        return first, second, sticky, third

    first, second, sticky, third = asyncio.run(run())

    assert first["account_name"] != second["account_name"]
    assert sticky["account_id"] == first["account_id"]
    assert third["account_id"] == second["account_id"]


def test_earnapp_pool_visible_in_settings(client):
    with patch("app.deps.auth.get_current_user", return_value=_owner()):
        resp = client.get("/settings")

    assert resp.status_code == 200
    assert "EarnApp Account Pool" in resp.text
    assert 'id="earnapp-account-file"' in resp.text
