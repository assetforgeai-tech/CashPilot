from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app import database, earnapp_collection, earnapp_recovery
from app.main import app


@asynccontextmanager
async def _noop_lifespan(app_):
    yield


app.router.lifespan_context = _noop_lifespan


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as value:
        yield value


def _owner():
    return {"uid": 1, "u": "admin", "r": "owner"}


def _import_body() -> dict[str, object]:
    return {
        "profile_key": "profile-40",
        "account_name": "owner@example.com",
        "email": "owner@example.com",
        "auth_method": "google",
        "cookies": {
            "auth": {"value": "1"},
            "auth-method": {"value": "google"},
            "oauth-refresh-token": {"value": "refresh-secret"},
            "xsrf-token": {"value": "xsrf-secret"},
        },
    }


def test_account_routes_are_registered_and_owner_only(client):
    routes = {route.path for route in app.routes}
    assert "/api/admin/earnapp/accounts" in routes
    assert "/api/admin/earnapp/accounts/import" in routes
    assert "/api/admin/earnapp/accounts/{account_id}/collect" in routes
    assert "/api/admin/earnapp/nodes/{logical_node_id}/replacement-ticket" in routes

    with patch("app.deps.auth.get_current_user", return_value=None):
        response = client.get("/api/admin/earnapp/accounts")
    assert response.status_code == 401


def test_import_and_list_mask_every_credential_and_report_capacity(tmp_path, client):
    with (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", tmp_path / "earnapp.db"),
        patch("app.deps.auth.get_current_user", return_value=_owner()),
    ):
        asyncio.run(database.init_db())
        imported = client.post("/api/admin/earnapp/accounts/import", json=_import_body())
        listed = client.get("/api/admin/earnapp/accounts")

    assert imported.status_code == 200
    payload = listed.json()
    assert listed.status_code == 200
    assert payload["counts"] == {"accounts": 1, "active": 1, "locked": 0, "nodes": 0}
    assert payload["proxy_capacity"]["recovery_hold_seconds"] == 3600
    row = payload["accounts"][0]
    assert row["profile_key"] == "profile-40"
    assert row["credentials_present"]["oauth-refresh-token"] is True
    assert row["token_warning"] == "expiry_unknown"
    serialized = listed.text
    assert "refresh-secret" not in serialized
    assert "xsrf-secret" not in serialized
    assert "credentials_enc" not in serialized


def test_import_updates_the_same_profile_without_duplicating_the_account(tmp_path, client):
    body = _import_body()
    with (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", tmp_path / "earnapp.db"),
        patch("app.deps.auth.get_current_user", return_value=_owner()),
    ):
        asyncio.run(database.init_db())
        first = client.post("/api/admin/earnapp/accounts/import", json=body)
        body["cookies"]["xsrf-token"] = {"value": "new-xsrf-secret"}
        second = client.post("/api/admin/earnapp/accounts/import", json=body)
        listed = client.get("/api/admin/earnapp/accounts")

    assert first.json()["account_id"] == second.json()["account_id"]
    assert listed.json()["counts"]["accounts"] == 1
    assert "new-xsrf-secret" not in listed.text


def test_locked_account_delete_requires_two_exact_confirmations(tmp_path, client):
    with (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", tmp_path / "earnapp.db"),
        patch("app.deps.auth.get_current_user", return_value=_owner()),
    ):
        asyncio.run(database.init_db())
        account_id = client.post("/api/admin/earnapp/accounts/import", json=_import_body()).json()["account_id"]

        not_locked = client.request(
            "DELETE",
            f"/api/admin/earnapp/accounts/{account_id}",
            json={"confirm_account_name": "owner@example.com", "confirm_phrase": "DELETE ACCOUNT"},
        )
        asyncio.run(database.set_earnapp_account_state(account_id, "ACCOUNT_LOCKED"))
        wrong_name = client.request(
            "DELETE",
            f"/api/admin/earnapp/accounts/{account_id}",
            json={"confirm_account_name": "wrong@example.com", "confirm_phrase": "DELETE ACCOUNT"},
        )
        wrong_phrase = client.request(
            "DELETE",
            f"/api/admin/earnapp/accounts/{account_id}",
            json={"confirm_account_name": "owner@example.com", "confirm_phrase": "delete"},
        )
        deleted = client.request(
            "DELETE",
            f"/api/admin/earnapp/accounts/{account_id}",
            json={"confirm_account_name": "owner@example.com", "confirm_phrase": "DELETE ACCOUNT"},
        )

    assert not_locked.status_code == 409
    assert wrong_name.status_code == 400
    assert wrong_phrase.status_code == 400
    assert deleted.status_code == 200


def test_list_includes_latest_collector_summary_and_recovery_countdown(tmp_path, client):
    with (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", tmp_path / "earnapp.db"),
        patch("app.deps.auth.get_current_user", return_value=_owner()),
    ):
        asyncio.run(database.init_db())
        account_id = client.post("/api/admin/earnapp/accounts/import", json=_import_body()).json()["account_id"]

        async def seed():
            await database.assign_earnapp_account("earnapp-node-a")
            db = await database._get_db()
            await db.execute(
                """
                UPDATE earnapp_logical_nodes
                SET state='RECOVERY_HOLD', generation=3, device_id='device-a',
                    recovery_started_at=datetime('now'), recovery_hold_until=datetime('now', '+1 hour')
                WHERE logical_node_id='earnapp-node-a'
                """
            )
            await db.commit()
            await database.save_earnapp_snapshot(
                account_id,
                {
                    "money_balance": 12.5,
                    "money_total": 90.0,
                    "online_nodes": 2,
                    "offline_nodes": 1,
                    "devices": [{"device_id": "secretly-not-returned"}],
                },
            )

        asyncio.run(seed())
        response = client.get("/api/admin/earnapp/accounts")

    payload = response.json()
    snapshot = payload["accounts"][0]["collector"]
    assert snapshot["money_balance"] == 12.5
    assert snapshot["money_total"] == 90.0
    assert snapshot["online_nodes"] == 2
    assert snapshot["offline_nodes"] == 1
    assert "devices_json" not in snapshot
    node = payload["nodes"][0]
    assert node["logical_node_id"] == "earnapp-node-a"
    assert node["generation"] == 3
    assert 3590 <= node["recovery_hold_remaining_seconds"] <= 3600
    assert "secretly-not-returned" not in response.text


def test_collect_and_replacement_ticket_endpoints_return_sanitized_results(client):
    with (
        patch("app.deps.auth.get_current_user", return_value=_owner()),
        patch.object(
            earnapp_collection,
            "collect_account",
            AsyncMock(
                return_value={
                    "status": "ok",
                    "money_balance": 1.25,
                    "money_total": 5.0,
                    "online_nodes": 1,
                    "offline_nodes": 0,
                    "devices": [{"device_id": "device-a"}],
                }
            ),
        ),
        patch.object(earnapp_recovery, "issue_replacement_ticket", AsyncMock(return_value="one-time-ticket")),
    ):
        collected = client.post("/api/admin/earnapp/accounts/7/collect")
        ticket = client.post(
            "/api/admin/earnapp/nodes/earnapp-node-a/replacement-ticket",
            json={"target_worker_id": 9},
        )

    assert collected.status_code == 200
    assert collected.json() == {
        "status": "ok",
        "money_balance": 1.25,
        "money_total": 5.0,
        "online_nodes": 1,
        "offline_nodes": 0,
    }
    assert "device-a" not in collected.text
    assert ticket.json() == {
        "logical_node_id": "earnapp-node-a",
        "target_worker_id": 9,
        "replacement_ticket": "one-time-ticket",
        "expires_in_seconds": 900,
    }
