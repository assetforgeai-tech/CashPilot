from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import app


@asynccontextmanager
async def _noop_lifespan(_app):
    yield


app.router.lifespan_context = _noop_lifespan


def _reader():
    return {"uid": 1, "u": "reader", "r": "reader"}


def test_deployed_services_hides_removed_catalog_slugs():
    with (
        TestClient(app, raise_server_exceptions=False) as client,
        patch("app.main.auth.get_current_user", return_value=_reader()),
        patch("app.main._get_all_worker_containers", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.get_health_scores", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.get_config", new_callable=AsyncMock, return_value={}),
        patch(
            "app.main.database.get_deployments",
            new_callable=AsyncMock,
            return_value=[
                {"slug": "bytelixir", "status": "external"},
                {"slug": "grass", "status": "external"},
            ],
        ),
    ):
        resp = client.get("/api/services/deployed")

    assert resp.status_code == 200
    slugs = [row["slug"] for row in resp.json()]
    assert "grass" in slugs
    assert "bytelixir" not in slugs

def test_provider_instances_group_under_canonical_provider_slug():
    containers = [
        {
            "slug": "bitping-direct",
            "provider": "bitping",
            "instance_mode": "direct",
            "name": "cashpilot-bitping-direct",
            "status": "running",
            "image": "bitping/bitpingd:latest",
            "cpu_percent": 1.0,
            "memory_mb": 10.0,
            "deployed_by": "worker",
            "category": "bandwidth",
        },
        {
            "slug": "bitping-proxy",
            "provider": "bitping",
            "instance_mode": "proxy",
            "name": "cashpilot-bitping-proxy",
            "status": "running",
            "image": "bitping/bitpingd:latest",
            "cpu_percent": 2.0,
            "memory_mb": 20.0,
            "deployed_by": "worker",
            "category": "bandwidth",
        },
    ]
    with (
        TestClient(app, raise_server_exceptions=False) as client,
        patch("app.main.auth.get_current_user", return_value=_reader()),
        patch("app.main._get_all_worker_containers", new_callable=AsyncMock, return_value=containers),
        patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.get_health_scores", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.get_config", new_callable=AsyncMock, return_value={}),
        patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.list_provider_instances", new_callable=AsyncMock, return_value=[]),
    ):
        resp = client.get("/api/services/deployed")

    assert resp.status_code == 200
    rows = resp.json()
    assert [row["slug"] for row in rows] == ["bitping"]
    assert rows[0]["instances"] == 2
    assert {item["mode"] for item in rows[0]["instance_details"]} == {"direct", "proxy"}

@pytest.mark.asyncio
async def test_auto_deploy_uses_provider_default_mode():
    seen = {}

    async def fake_deploy(_request, slug, body, worker_id=None, _auth=None):
        seen["slug"] = slug
        seen["mode"] = body.mode
        seen["worker_id"] = worker_id
        return {"status": "deployed"}

    with patch("app.main.api_deploy", new=fake_deploy):
        await main._auto_deploy_one(42, "bitping")

    assert seen == {"slug": "bitping", "mode": "both", "worker_id": 42}
