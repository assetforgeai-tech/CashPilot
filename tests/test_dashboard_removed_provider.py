from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

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
