from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import database, earnapp_collection, earnapp_recovery
from app.main import app
from app.routers import earnapp_accounts as earnapp_accounts_router


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
    assert "/api/admin/earnapp/accounts/{account_id}/payment" in routes
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
                    "devices": [
                        {
                            "device_id": "secretly-not-returned",
                            "billing": "qualified_uptime",
                            "usage_current": 18142,
                            "usage_total": 18142,
                            "usage_available": True,
                        }
                    ],
                },
            )

        asyncio.run(seed())
        with patch.object(
            earnapp_collection,
            "account_route_status",
            AsyncMock(
                return_value={
                    "status": "healthy",
                    "source": "node",
                    "proxy_id": 17,
                    "egress_ip": "198.51.100.17",
                    "country_code": "VN",
                    "checked_at": "2026-08-27 10:00:00",
                }
            ),
        ):
            response = client.get("/api/admin/earnapp/accounts")

    payload = response.json()
    snapshot = payload["accounts"][0]["collector"]
    assert snapshot["money_balance"] == 12.5
    assert snapshot["money_total"] == 90.0
    assert snapshot["online_nodes"] == 2
    assert snapshot["offline_nodes"] == 1
    assert snapshot["usage_current"] == 18142
    assert snapshot["usage_total"] == 18142
    assert snapshot["usage_available_nodes"] == 1
    assert snapshot["usage_missing_nodes"] == 0
    assert payload["accounts"][0]["route"] == {
        "status": "healthy",
        "source": "node",
        "proxy_id": 17,
        "egress_ip": "198.51.100.17",
        "country_code": "VN",
        "checked_at": "2026-08-27 10:00:00",
    }
    assert "devices_json" not in snapshot
    node = payload["nodes"][0]
    assert node["logical_node_id"] == "earnapp-node-a"
    assert node["generation"] == 3
    assert 3590 <= node["recovery_hold_remaining_seconds"] <= 3600
    assert "secretly-not-returned" not in response.text


def test_collect_endpoint_returns_sanitized_result_and_replacement_delegates_platform_policy(client):
    issue_ticket = AsyncMock(return_value="one-time-ticket")
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
        patch.object(earnapp_recovery, "issue_replacement_ticket", issue_ticket),
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
    assert ticket.status_code == 200
    assert ticket.json()["replacement_ticket"] == "one-time-ticket"
    issue_ticket.assert_awaited_once_with("earnapp-node-a", 9)


def test_payment_routes_are_owner_only_and_return_only_sanitized_state(client):
    configured = {
        "configured": True,
        "method": "paypal.com",
        "destination_masked": "o***@example.com",
        "methods": [],
        "transactions": [],
    }
    disabled = {**configured, "configured": False, "method": "", "destination_masked": ""}
    with (
        patch("app.deps.auth.get_current_user", return_value=_owner()),
        patch.object(earnapp_collection, "configure_payment", AsyncMock(return_value=configured)) as configure,
        patch.object(earnapp_collection, "disable_payment", AsyncMock(return_value=disabled)) as disable,
    ):
        response = client.post(
            "/api/admin/earnapp/accounts/7/payment",
            json={"payment_method": "paypal.com", "destination": "owner@example.com"},
        )
        removed = client.delete("/api/admin/earnapp/accounts/7/payment")

    assert response.status_code == 200
    assert response.json() == configured
    assert "owner@example.com" not in response.text
    configure.assert_awaited_once_with(7, payment_method="paypal.com", destination="owner@example.com")
    assert removed.status_code == 200
    assert removed.json() == disabled
    disable.assert_awaited_once_with(7)


@pytest.mark.asyncio
async def test_local_runtime_cleanup_accepts_authoritative_docker_absence(monkeypatch):
    remove = AsyncMock(
        return_value={
            "status": "removed",
            "main_present": False,
            "sidecar_present": False,
        }
    )
    monkeypatch.setattr("app.main._proxy_to_worker", remove)

    assert await earnapp_accounts_router._remove_local_runtime(
        {
            "logical_node_id": "earnapp-node-1",
            "instance_id": "earnapp-node-1",
            "worker_id": 7,
            "runtime_backend": "docker",
            "generation": 4,
            "device_id": "sdk-ios-" + "1" * 32,
        }
    )
    remove.assert_awaited_once_with(
        7,
        "DELETE",
        "/api/earnapp/docker-nodes/earnapp-node-1",
        json={"generation": 4, "device_id": "sdk-ios-" + "1" * 32},
        timeout=180,
    )


@pytest.mark.asyncio
async def test_local_runtime_cleanup_does_not_use_a_stale_container_list_as_absence_evidence(monkeypatch):
    remove = AsyncMock(
        return_value={
            "status": "removed",
            "main_present": False,
            "sidecar_present": True,
        }
    )
    monkeypatch.setattr("app.main._proxy_to_worker", remove)

    assert not await earnapp_accounts_router._remove_local_runtime(
        {
            "logical_node_id": "earnapp-node-1",
            "instance_id": "earnapp-node-1",
            "worker_id": 7,
            "runtime_backend": "docker",
            "generation": 4,
            "device_id": "sdk-ios-" + "1" * 32,
        }
    )
    remove.assert_awaited_once_with(
        7,
        "DELETE",
        "/api/earnapp/docker-nodes/earnapp-node-1",
        json={"generation": 4, "device_id": "sdk-ios-" + "1" * 32},
        timeout=180,
    )


@pytest.mark.asyncio
async def test_local_runtime_cleanup_does_not_treat_worker_failure_as_absence(monkeypatch):
    remove = AsyncMock(side_effect=HTTPException(status_code=503, detail="worker offline"))
    monkeypatch.setattr("app.main._proxy_to_worker", remove)

    assert not await earnapp_accounts_router._remove_local_runtime(
        {
            "logical_node_id": "earnapp-node-3",
            "instance_id": "earnapp-node-3",
            "worker_id": 9,
            "runtime_backend": "docker",
            "generation": 2,
            "device_id": "sdk-mac-" + "3" * 32,
        }
    )
    remove.assert_awaited_once()


@pytest.mark.asyncio
async def test_local_runtime_cleanup_rejects_orphaned_docker_sidecar(monkeypatch):
    remove = AsyncMock(
        return_value={
            "status": "removed",
            "main_present": False,
            "sidecar_present": True,
        }
    )
    monkeypatch.setattr("app.main._proxy_to_worker", remove)

    assert not await earnapp_accounts_router._remove_local_runtime(
        {
            "logical_node_id": "earnapp-node-1",
            "instance_id": "earnapp-node-1",
            "worker_id": 7,
            "runtime_backend": "docker",
            "generation": 4,
            "device_id": "sdk-ios-" + "1" * 32,
        }
    )
    remove.assert_awaited_once_with(
        7,
        "DELETE",
        "/api/earnapp/docker-nodes/earnapp-node-1",
        json={"generation": 4, "device_id": "sdk-ios-" + "1" * 32},
        timeout=180,
    )


def test_worker_container_presence_uses_exact_live_lookup():
    class Container:
        short_id = "abcdef123456"
        labels = {
            "cashpilot.managed": "true",
            "cashpilot.service": "earnapp-node-1",
            "cashpilot.provider": "earnapp",
        }

    with (
        patch("app.worker_api._verify_api_key"),
        patch("app.worker_api.orchestrator._find_container", return_value=Container()) as find,
    ):
        from app import worker_api

        result = asyncio.run(worker_api.api_container_presence(object(), "earnapp-node-1"))

    assert result == {
        "present": True,
        "slug": "earnapp-node-1",
        "provider_slug": "earnapp",
        "container_id": "abcdef123456",
    }
    find.assert_called_once_with("earnapp-node-1")


@pytest.mark.asyncio
async def test_local_runtime_cleanup_uses_authoritative_lxd_presence_when_state_file_is_missing(monkeypatch):
    calls = []

    async def proxy(worker_id, method, path, **kwargs):
        calls.append((worker_id, method, path, kwargs))
        if method == "DELETE":
            raise HTTPException(status_code=404, detail="worker state missing")
        return {
            "present": True,
            "runtime_backend": "lxd",
            "instance_id": "cashpilot-earnapp-earnapp-node-lxd",
        }

    monkeypatch.setattr("app.main._proxy_to_worker", proxy)

    assert not await earnapp_accounts_router._remove_local_runtime(
        {
            "logical_node_id": "earnapp-node-lxd",
            "instance_id": "earnapp-node-lxd",
            "worker_id": 7,
            "runtime_backend": "lxd",
            "generation": 3,
            "device_id": "sdk-node-" + "a" * 32,
        }
    )
    assert calls[-1] == (
        7,
        "POST",
        "/api/earnapp/nodes/earnapp-node-lxd/presence",
        {
            "json": {"generation": 3, "device_id": "sdk-node-" + "a" * 32},
            "timeout": 30,
        },
    )


@pytest.mark.asyncio
async def test_local_runtime_cleanup_accepts_lxd_absence_only_from_authoritative_presence_404(monkeypatch):
    calls = []

    async def proxy(worker_id, method, path, **kwargs):
        calls.append((worker_id, method, path, kwargs))
        raise HTTPException(status_code=404, detail="Worker request failed")

    monkeypatch.setattr("app.main._proxy_to_worker", proxy)

    assert await earnapp_accounts_router._remove_local_runtime(
        {
            "logical_node_id": "earnapp-node-lxd",
            "instance_id": "earnapp-node-lxd",
            "worker_id": 7,
            "runtime_backend": "lxd",
            "generation": 3,
            "device_id": "sdk-node-" + "a" * 32,
        }
    )
    assert calls[-1] == (
        7,
        "POST",
        "/api/earnapp/nodes/earnapp-node-lxd/presence",
        {
            "json": {"generation": 3, "device_id": "sdk-node-" + "a" * 32},
            "timeout": 30,
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["docker", "lxd"])
async def test_local_runtime_cleanup_never_treats_a_missing_worker_as_runtime_absence(monkeypatch, backend):
    async def proxy(*_args, **_kwargs):
        raise HTTPException(status_code=404, detail="Worker not found")

    monkeypatch.setattr("app.main._proxy_to_worker", proxy)
    binding = {
        "logical_node_id": "earnapp-node-missing-worker",
        "instance_id": "earnapp-node-missing-worker",
        "worker_id": 404,
        "runtime_backend": backend,
    }
    if backend == "lxd":
        binding.update(generation=3, device_id="sdk-node-" + "a" * 32)

    assert not await earnapp_accounts_router._remove_local_runtime(binding)
