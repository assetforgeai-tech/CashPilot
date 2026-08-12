from __future__ import annotations

import os
import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import database, main, myst_wallets


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

    def test_wallet_page_accepts_file_import(self, client):
        with _auth_owner():
            resp = client.get("/myst-wallet")
        assert 'id="myst-wallet-file"' in resp.text
        assert 'data-action="importMystWalletFile"' in resp.text


class TestMystWalletApi:
    def test_wallet_list_endpoint_exists(self, client):
        with _auth_owner():
            resp = client.get("/api/admin/myst-wallets")
        assert resp.status_code == 200

    def test_wallet_import_requires_owner(self, client):
        resp = client.post("/api/admin/myst-wallets/import", json={"raw": "wallet-a"})
        assert resp.status_code == 401

    def test_wallet_update_marks_funded(self, client):
        with (
            _auth_owner(),
            patch("app.routers.myst_wallets.database.update_myst_wallet", new_callable=AsyncMock, return_value=True),
        ):
            resp = client.patch("/api/admin/myst-wallets/3", json={"funding": "FUNDED"})
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_wallet_export_returns_text_only_when_owner(self, client):
        with (
            _auth_owner(),
            patch("app.routers.myst_wallets.database.export_myst_wallets", new_callable=AsyncMock, return_value=["wallet-a", "wallet-b"]),
        ):
            resp = client.get("/api/admin/myst-wallets/export")
        assert resp.status_code == 200
        assert resp.text == "wallet-a\nwallet-b"


class TestMystWalletHelpers:
    def test_normalize_wallet_lines_skips_blanks(self):
        assert myst_wallets.normalize_wallet_lines(" a \n\n b \r\n") == ["a", "b"]

    def test_wallet_address_hint_handles_json_keystore_address(self):
        raw = '{"address":"57143ba62ee95ac60abdb0aab1b3fdfe9f4bf5b1","crypto":{}}'
        assert myst_wallets.wallet_address_hint(raw) == "0x57143ba62ee95ac60abdb0aab1b3fdfe9f4bf5b1"[-12:]

class TestMystWalletInventory:
    def test_admin_list_never_returns_raw_wallet(self, tmp_path):
        async def run():
            with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "myst.db"):
                await database.init_db()
                await database.import_myst_wallets("raw-wallet-one")
                rows = await database.list_myst_wallets()
                assert rows
                assert "raw_wallet" not in rows[0]
                assert "raw_wallet_enc" not in rows[0]
                assert rows[0]["release_reason"] == ""
                assert rows[0]["wallet_assignment_version"] == 0

        asyncio.run(run())

    def test_explicit_export_returns_raw_wallets(self, tmp_path):
        async def run():
            with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "myst.db"):
                await database.init_db()
                await database.import_myst_wallets("raw-wallet-one\nraw-wallet-two")
                rows = await database.export_myst_wallets()
                assert rows == ["raw-wallet-one", "raw-wallet-two"]

        asyncio.run(run())

    def test_funded_wallet_lease_marks_owner(self, tmp_path):
        async def run():
            with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "myst.db"):
                await database.init_db()
                await database.import_myst_wallets("raw-wallet-one")
                wallets = await database.list_myst_wallets()
                assert await database.update_myst_wallet(wallets[0]["id"], funding="FUNDED")
                leased = await database.lease_myst_wallet("worker-a", worker_id=7)
                assert leased["raw_wallet"] == "raw-wallet-one"
                assert leased["state"] == "LEASED"
                assert leased["leased_to_client_id"] == "worker-a"
                assert leased["wallet_assignment_version"] == 1
                listed = await database.list_myst_wallets()
                assert listed[0]["state"] == "LEASED"
                assert listed[0]["leased_to_worker_id"] == 7
                assert listed[0]["wallet_assignment_version"] == 1

        asyncio.run(run())

    def test_lease_reuses_current_worker_wallet(self, tmp_path):
        async def run():
            with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "myst.db"):
                await database.init_db()
                await database.import_myst_wallets("raw-wallet-one\nraw-wallet-two")
                first = await database.lease_myst_wallet("worker-a", worker_id=7, public_ip="8.8.8.8")
                second = await database.lease_myst_wallet("worker-a", worker_id=7, public_ip="8.8.8.8")
                assert second["id"] == first["id"]
                assert second["wallet_assignment_version"] == first["wallet_assignment_version"]

        asyncio.run(run())

    def test_lease_blocks_duplicate_public_ip(self, tmp_path):
        async def run():
            with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "myst.db"):
                await database.init_db()
                await database.import_myst_wallets("raw-wallet-one\nraw-wallet-two")
                assert await database.lease_myst_wallet("worker-a", worker_id=7, public_ip="8.8.8.8")
                with pytest.raises(database.MystWalletPublicIpInUse):
                    await database.lease_myst_wallet("worker-b", worker_id=8, public_ip="8.8.8.8")

        asyncio.run(run())

    def test_stale_worker_lease_reclaims_by_worker_heartbeat(self, tmp_path):
        async def run():
            with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "myst.db"):
                await database.init_db()
                worker_id = await database.upsert_worker("worker-a", "worker", "http://worker", system_info='{"egress_ip":"8.8.8.8"}')
                await database.import_myst_wallets("raw-wallet-one")
                leased = await database.lease_myst_wallet("worker-a", worker_id=worker_id, public_ip="8.8.8.8")
                db = await database._get_db()
                try:
                    await db.execute("UPDATE workers SET last_heartbeat = datetime('now', '-2 hours') WHERE id = ?", (worker_id,))
                    await db.commit()
                finally:
                    await db.close()

                count = await database.reclaim_stale_myst_wallet_leases(max_worker_age_seconds=3600)

                assert count == 1
                row = (await database.list_myst_wallets())[0]
                assert row["id"] == leased["id"]
                assert row["state"] == "AVAILABLE"
                assert row["release_reason"] == "CLIENT_STALE"

        asyncio.run(run())

    def test_only_lease_owner_can_release(self, tmp_path):
        async def run():
            with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "myst.db"):
                await database.init_db()
                await database.import_myst_wallets("raw-wallet-one")
                wallet_id = (await database.list_myst_wallets())[0]["id"]
                await database.update_myst_wallet(wallet_id, funding="FUNDED")
                leased = await database.lease_myst_wallet("worker-a")
                assert not await database.release_myst_wallet(
                    leased["id"],
                    "worker-b",
                    wallet_assignment_version=leased["wallet_assignment_version"],
                )
                assert await database.release_myst_wallet(
                    leased["id"],
                    "worker-a",
                    release_reason="SHUTDOWN",
                    wallet_assignment_version=leased["wallet_assignment_version"],
                )
                row = (await database.list_myst_wallets())[0]
                assert row["release_reason"] == "SHUTDOWN"

        asyncio.run(run())

    def test_heartbeat_keeps_lease_alive_with_redacted_runtime(self, tmp_path):
        async def run():
            with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "myst.db"):
                await database.init_db()
                await database.import_myst_wallets("raw-wallet-one")
                wallet_id = (await database.list_myst_wallets())[0]["id"]
                await database.update_myst_wallet(wallet_id, funding="FUNDED")
                leased = await database.lease_myst_wallet("worker-a")
                ok = await database.sync_myst_wallet_runtime(
                    leased["id"],
                    "worker-a",
                    wallet_assignment_version=leased["wallet_assignment_version"],
                    node_identity="0xnode",
                    runtime_status="healthy",
                    evidence={"dashboard_text": "secret-ish text"},
                )
                assert ok
                row = (await database.list_myst_wallets())[0]
                assert row["state"] == "LEASED"
                assert row["node_identity"] == "0xnode"
                assert row["runtime_status"] == "healthy"
                assert row["last_heartbeat_at"]
                assert "dashboard_text" not in row

        asyncio.run(run())

    def test_unregistered_heartbeat_marks_wallet_unfunded(self, tmp_path):
        async def run():
            with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "myst.db"):
                await database.init_db()
                await database.import_myst_wallets("raw-wallet-one")
                wallet_id = (await database.list_myst_wallets())[0]["id"]
                await database.update_myst_wallet(wallet_id, funding="FUNDED")
                leased = await database.lease_myst_wallet("worker-a")
                ok = await database.sync_myst_wallet_runtime(
                    leased["id"],
                    "worker-a",
                    wallet_assignment_version=leased["wallet_assignment_version"],
                    runtime_status="healthy",
                    evidence={"registration_status": "Unregistered"},
                )
                assert ok
                row = (await database.list_myst_wallets())[0]
                assert row["state"] == "AVAILABLE"
                assert row["funding"] == "UNFUNDED"
                assert row["release_reason"] == "MYST_WALLET_UNFUNDED"
                assert row["leased_to_worker_id"] is None

        asyncio.run(run())

    def test_payment_required_without_unregistered_does_not_mark_wallet_unfunded(self, tmp_path):
        async def run():
            with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "myst.db"):
                await database.init_db()
                await database.import_myst_wallets("raw-wallet-one")
                wallet_id = (await database.list_myst_wallets())[0]["id"]
                await database.update_myst_wallet(wallet_id, funding="FUNDED")
                leased = await database.lease_myst_wallet("worker-a")
                ok = await database.sync_myst_wallet_runtime(
                    leased["id"],
                    "worker-a",
                    wallet_assignment_version=leased["wallet_assignment_version"],
                    runtime_status="payment_required",
                    evidence={"payment_required": True, "registration_status": "Registered"},
                )
                assert ok
                row = (await database.list_myst_wallets())[0]
                assert row["state"] == "LEASED"
                assert row["funding"] == "FUNDED"

        asyncio.run(run())

    def test_stale_wallet_assignment_version_cannot_heartbeat(self, tmp_path):
        async def run():
            with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "myst.db"):
                await database.init_db()
                await database.import_myst_wallets("raw-wallet-one")
                wallet_id = (await database.list_myst_wallets())[0]["id"]
                await database.update_myst_wallet(wallet_id, funding="FUNDED")
                leased = await database.lease_myst_wallet("worker-a")

                ok = await database.sync_myst_wallet_runtime(
                    leased["id"],
                    "worker-a",
                    wallet_assignment_version=leased["wallet_assignment_version"] - 1,
                    node_identity="stale-node",
                    runtime_status="stale",
                )

                assert not ok
                row = (await database.list_myst_wallets())[0]
                assert row["node_identity"] == ""
                assert row["runtime_status"] == ""

        asyncio.run(run())

    def test_stale_wallet_assignment_version_cannot_release(self, tmp_path):
        async def run():
            with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "myst.db"):
                await database.init_db()
                await database.import_myst_wallets("raw-wallet-one")
                wallet_id = (await database.list_myst_wallets())[0]["id"]
                await database.update_myst_wallet(wallet_id, funding="FUNDED")
                leased = await database.lease_myst_wallet("worker-a")

                ok = await database.release_myst_wallet(
                    leased["id"],
                    "worker-a",
                    release_reason="stale",
                    wallet_assignment_version=leased["wallet_assignment_version"] - 1,
                )

                assert not ok
                row = (await database.list_myst_wallets())[0]
                assert row["state"] == "LEASED"
                assert row["release_reason"] == ""

        asyncio.run(run())

    def test_myst_wallet_ack_requires_current_assignment_version(self, tmp_path):
        async def run():
            with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "myst.db"):
                await database.init_db()
                await database.import_myst_wallets("raw-wallet-one")
                wallet_id = (await database.list_myst_wallets())[0]["id"]
                await database.update_myst_wallet(wallet_id, funding="FUNDED")
                leased = await database.lease_myst_wallet("worker-a")

                assert not await database.ack_myst_wallet(
                    leased["id"],
                    "worker-a",
                    wallet_assignment_version=leased["wallet_assignment_version"] - 1,
                    node_identity="0xnode",
                    evidence={"raw_wallet": "must-not-store"},
                )
                assert await database.ack_myst_wallet(
                    leased["id"],
                    "worker-a",
                    wallet_assignment_version=leased["wallet_assignment_version"],
                    node_identity="0xnode",
                    evidence={"raw_wallet": "must-not-store", "registration_status": "Registered"},
                )
                row = (await database.list_myst_wallets())[0]
                assert row["state"] == "LEASED"
                assert row["runtime_status"] == "wallet_imported"
                assert row["node_identity"] == "0xnode"

        asyncio.run(run())

    def test_worker_heartbeat_updates_myst_wallet_provider_state(self, tmp_path, client):
        async def setup():
            with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "myst.db"):
                await database.init_db()
                await database.import_myst_wallets("raw-wallet-one")
                wallet_id = (await database.list_myst_wallets())[0]["id"]
                await database.update_myst_wallet(wallet_id, funding="FUNDED")
                leased = await database.lease_myst_wallet("worker-a")
                return leased

        leased = asyncio.run(setup())
        body = {
            "name": "worker",
            "client_id": "worker-a",
            "url": "http://worker",
            "containers": [],
            "system_info": {"egress_ip": "8.8.8.8"},
            "provider_states": {
                "mysterium": {
                    "wallet_id": leased["id"],
                    "wallet_assignment_version": leased["wallet_assignment_version"],
                    "node_identity": "0xnode",
                    "runtime_status": "running",
                    "evidence": {"registration_status": "Registered"},
                }
            },
        }
        with (
            patch.object(database, "DB_DIR", tmp_path),
            patch.object(database, "DB_PATH", tmp_path / "myst.db"),
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
        ):
            resp = client.post("/api/workers/heartbeat", json=body, headers={"Authorization": "Bearer test"})
            row = asyncio.run(database.list_myst_wallets())[0]

        assert resp.status_code == 200
        assert row["node_identity"] == "0xnode"
        assert row["runtime_status"] == "running"

    def test_worker_heartbeat_reclaims_stale_myst_wallets(self, tmp_path, client):
        async def setup():
            with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "myst.db"):
                await database.init_db()
                worker_id = await database.upsert_worker("worker-a", "worker", "http://worker")
                await database.import_myst_wallets("raw-wallet-one")
                leased = await database.lease_myst_wallet("worker-a", worker_id=worker_id)
                db = await database._get_db()
                try:
                    await db.execute("UPDATE workers SET last_heartbeat = datetime('now', '-2 hours') WHERE id = ?", (worker_id,))
                    await db.commit()
                finally:
                    await db.close()
                return leased

        leased = asyncio.run(setup())
        body = {
            "name": "worker",
            "client_id": "worker-a",
            "url": "http://worker",
            "containers": [],
            "system_info": {"egress_ip": "8.8.8.8"},
            "provider_states": {},
        }
        with (
            patch.object(database, "DB_DIR", tmp_path),
            patch.object(database, "DB_PATH", tmp_path / "myst.db"),
            patch("app.main.database.reclaim_stale_myst_wallet_leases", new_callable=AsyncMock, return_value=1),
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
        ):
            resp = client.post("/api/workers/heartbeat", json=body, headers={"Authorization": "Bearer test"})

        assert resp.status_code == 200
        assert leased["id"] > 0

    def test_myst_wallet_heartbeat_endpoint_is_removed(self, client):
        resp = client.post(
            "/api/myst-wallets/" + "heartbeat",
            json={
                "client_id": "worker-a",
                "wallet_id": 1,
                "wallet_assignment_version": 1,
            },
        )
        assert resp.status_code == 404

    def test_mysterium_deploy_attaches_wallet_for_worker_client(self, tmp_path):
        async def run():
            with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "myst.db"):
                await database.init_db()
                worker_id = await database.upsert_worker("worker-client", "worker", "http://worker")
                await database.import_myst_wallets("raw-wallet-one")
                spec = {"deploy_credentials": {"myst_dashboard_password": "pw", "myst_mmn_api_key": "mmn"}}
                await main._attach_myst_wallet_for_deploy("mysterium", worker_id, spec)

                creds = spec["deploy_credentials"]
                assert creds["myst_wallet_raw"] == "raw-wallet-one"
                assert creds["myst_wallet_assignment_version"] == 1
                row = (await database.list_myst_wallets())[0]
                assert row["state"] == "LEASED"
                assert row["leased_to_worker_id"] == worker_id

        asyncio.run(run())
