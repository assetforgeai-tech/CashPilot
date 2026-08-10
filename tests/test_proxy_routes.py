from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@asynccontextmanager
async def _noop_lifespan(_app):
    yield


app.router.lifespan_context = _noop_lifespan


def _owner_user():
    return {"uid": 1, "u": "admin", "r": "owner"}


def _viewer_user():
    return {"uid": 2, "u": "viewer", "r": "viewer"}


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_proxy_provider_pages_require_owner(client):
    with patch("app.main.auth.get_current_user", return_value=_viewer_user()):
        assert client.get("/proxy-providers").status_code == 403
        assert client.get("/proxy-pool").status_code == 403


def test_proxy_provider_list_does_not_expose_secret(client):
    rows = [
        {
            "id": 1,
            "name": "vtproxy",
            "type": "vtproxy",
            "base_url": "https://vtproxy.net",
            "api_key_set": True,
            "enabled": 1,
        }
    ]
    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch("app.main.database.list_proxy_providers", new_callable=AsyncMock, return_value=rows),
    ):
        resp = client.get("/api/proxy-providers")
    assert resp.status_code == 200
    assert "secret-key" not in resp.text
    assert '"api_key":' not in resp.text


def test_proxy_provider_sync_is_owner_only(client):
    with patch("app.main.auth.get_current_user", return_value=_viewer_user()):
        resp = client.post("/api/proxy-providers/1/sync")
    assert resp.status_code == 403


def test_worker_proxy_assignment_sticks(client):
    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch("app.main.database.set_worker_proxy_assignment", new_callable=AsyncMock, return_value=True) as setter,
        patch("app.main.database.get_worker", new_callable=AsyncMock, return_value={"id": 7, "name": "w7"}),
        patch(
            "app.main.database.get_proxy_endpoint",
            new_callable=AsyncMock,
            return_value={"host": "proxy.example.com", "port": 8080, "protocol": "http"},
        ),
        patch("app.main._proxy_to_worker", new_callable=AsyncMock, return_value={"status": "ok"}) as apply,
    ):
        resp = client.post(
            "/api/workers/7/proxy-assignment",
            json={"proxy_id": 3, "mode": "proxy", "fallback": "hold"},
        )
    assert resp.status_code == 200
    assert setter.await_count == 1
    apply.assert_awaited_once()
