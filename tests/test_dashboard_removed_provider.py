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

def test_deployed_services_hides_removed_catalog_container_statuses():
    containers = [
        {
            "slug": "adnade",
            "name": "cashpilot-adnade",
            "status": "running",
            "image": "cashpilot/adnade:old",
            "cpu_percent": 1.0,
            "memory_mb": 10.0,
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
    slugs = [row["slug"] for row in resp.json()]
    assert "adnade" not in slugs

def test_provider_instances_group_under_canonical_provider_slug():
    containers = [
        {
            "slug": "earnfm-direct",
            "provider": "earnfm",
            "instance_mode": "direct",
            "name": "cashpilot-earnfm-direct",
            "status": "running",
            "image": "fazalfarhan01/earnfm-client:latest",
            "cpu_percent": 1.0,
            "memory_mb": 10.0,
            "deployed_by": "worker",
            "category": "bandwidth",
        },
        {
            "slug": "earnfm-proxy",
            "provider": "earnfm",
            "instance_mode": "proxy",
            "name": "cashpilot-earnfm-proxy",
            "status": "running",
            "image": "fazalfarhan01/earnfm-client:latest",
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
    by_slug = {row["slug"]: row for row in rows}
    assert len(rows) == 15
    assert by_slug["earnfm"]["instances"] == 2
    assert {item["mode"] for item in by_slug["earnfm"]["instance_details"]} == {"direct", "proxy"}

def test_dashboard_lists_active_catalog_providers_even_before_deploy():
    with (
        TestClient(app, raise_server_exceptions=False) as client,
        patch("app.main.auth.get_current_user", return_value=_reader()),
        patch("app.main._get_all_worker_containers", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.get_health_scores", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.get_config", new_callable=AsyncMock, return_value={}),
        patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.list_provider_instances", new_callable=AsyncMock, return_value=[]),
    ):
        resp = client.get("/api/services/deployed")

    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 15
    by_slug = {row["slug"]: row for row in rows}
    assert by_slug["proxybase-xyz"]["container_status"] == "not_deployed"
    assert by_slug["proxybase-xyz"]["collector_needs_setup"] is False

@pytest.mark.asyncio
async def test_auto_deploy_uses_provider_default_mode():
    seen = {}

    async def fake_deploy(_request, slug, body, worker_id=None, _auth=None):
        seen["slug"] = slug
        seen["mode"] = body.mode
        seen["worker_id"] = worker_id
        return {"status": "deployed"}

    with patch("app.main.api_deploy", new=fake_deploy):
        await main._auto_deploy_one(42, "earnfm")

    assert seen == {"slug": "earnfm", "mode": "both", "worker_id": 42}
