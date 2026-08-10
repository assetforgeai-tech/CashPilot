from __future__ import annotations

import os
from contextlib import asynccontextmanager
from unittest.mock import patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import myst_wallets


@asynccontextmanager
async def _noop_lifespan(app_):
    yield


app.router.lifespan_context = _noop_lifespan


def _owner():
    return {"uid": 1, "u": "admin", "r": "owner"}


def _auth_owner():
    return patch("app.main.auth.get_current_user", return_value=_owner())


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestMystWalletMenu:
    def test_settings_exposes_wallet_menu(self, client):
        with _auth_owner():
            resp = client.get("/settings")
        assert resp.status_code == 200
        assert "MYST Wallet" in resp.text

    def test_wallet_page_exists(self, client):
        with _auth_owner():
            resp = client.get("/myst-wallet")
        assert resp.status_code == 200


class TestMystWalletApi:
    def test_wallet_list_endpoint_exists(self, client):
        with _auth_owner():
            resp = client.get("/api/admin/myst-wallets")
        assert resp.status_code == 200

    def test_wallet_import_requires_owner(self, client):
        resp = client.post("/api/admin/myst-wallets/import", json={"raw": "wallet-a"})
        assert resp.status_code == 401


class TestMystWalletHelpers:
    def test_normalize_wallet_lines_skips_blanks(self):
        assert myst_wallets.normalize_wallet_lines(" a \n\n b \r\n") == ["a", "b"]
