from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import zipfile
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

from fastapi.testclient import TestClient

import app.nkn_wallets as nkn_wallets
from app import database
from app.main import app


@asynccontextmanager
async def _noop_lifespan(app_):
    yield


app.router.lifespan_context = _noop_lifespan


def _owner():
    return {"uid": 1, "u": "admin", "r": "owner"}


def _auth_owner():
    return patch("app.main.auth.get_current_user", return_value=_owner())


def _wallet_json(address: str = "NKNa31NDoKZop91uJ8V6F863HaD1H3Jebikq") -> str:
    return json.dumps(
        {
            "Version": 2,
            "IV": "iv",
            "MasterKey": "mk",
            "SeedEncrypted": "seed",
            "Address": address,
            "Scrypt": {"Salt": "salt", "N": 32768, "R": 8, "P": 1},
        },
        separators=(",", ":"),
    )


def _zip_b64() -> str:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as zf:
        zf.writestr("1000001/wallet.json", _wallet_json())
        zf.writestr("1000001/wallet.pswd", "pw")
    return base64.b64encode(data.getvalue()).decode()


class TestNknWalletHelpers:
    def test_iter_wallet_records_reads_folder_address_and_password(self):
        records = list(nkn_wallets.iter_wallet_records_from_zip(base64.b64decode(_zip_b64())))
        assert records == [
            {
                "folder_name": "1000001",
                "wallet_json": _wallet_json(),
                "wallet_pswd": "pw",
                "wallet_fingerprint": "1000001",
                "address": "NKNa31NDoKZop91uJ8V6F863HaD1H3Jebikq",
            }
        ]


class TestNknWalletApi:
    def test_page_exists(self):
        with TestClient(app, raise_server_exceptions=False) as client, _auth_owner():
            resp = client.get("/nkn-wallet")
        assert resp.status_code == 200
        assert "NKN Wallet" in resp.text

    def test_import_requires_owner(self):
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/api/admin/nkn-wallets/import", json={"archive_b64": _zip_b64()})
        assert resp.status_code == 401

    def test_import_endpoint_calls_database(self):
        with (
            TestClient(app, raise_server_exceptions=False) as client,
            _auth_owner(),
            patch("app.routers.nkn_wallets.database.import_nkn_wallets_from_zip", new_callable=AsyncMock, return_value=1),
        ):
            resp = client.post("/api/admin/nkn-wallets/import", json={"archive_b64": _zip_b64()})
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "imported": 1}


class TestNknWalletInventory:
    def test_import_and_list_redacts_wallet_files(self, tmp_path):
        async def run():
            with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "nkn.db"):
                await database.init_db()
                assert await database.import_nkn_wallets_from_zip(base64.b64decode(_zip_b64())) == 1
                rows = await database.list_nkn_wallets()
                assert rows[0]["folder_name"] == "1000001"
                assert rows[0]["address"] == "NKNa31NDoKZop91uJ8V6F863HaD1H3Jebikq"
                assert rows[0]["public_ip"] == ""
                assert "wallet_json" not in rows[0]
                assert "wallet_pswd" not in rows[0]

        asyncio.run(run())
