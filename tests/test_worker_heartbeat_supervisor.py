from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


def test_heartbeat_freshness_uses_success_timestamp():
    from app import worker_api

    with (
        patch.object(worker_api, "UI_URL", "https://ui.example"),
        patch.object(worker_api, "_last_heartbeat_at", 100.0),
    ):
        assert worker_api._heartbeat_is_fresh(now=279.0)
        assert not worker_api._heartbeat_is_fresh(now=280.0)


@pytest.mark.asyncio
async def test_supervisor_recreates_finished_heartbeat_task_once():
    from app import worker_api

    finished = asyncio.create_task(asyncio.sleep(0))
    await finished
    replacement = AsyncMock()
    with (
        patch.object(worker_api, "UI_URL", "https://ui.example"),
        patch.object(worker_api, "_heartbeat_task", finished),
        patch.object(worker_api, "_start_heartbeat_task", return_value=replacement) as start,
    ):
        await worker_api._supervise_heartbeat_once()
        start.assert_called_once_with()
        assert worker_api._heartbeat_task is replacement


@pytest.mark.asyncio
async def test_supervisor_does_not_duplicate_live_heartbeat_task():
    from app import worker_api

    live = asyncio.create_task(asyncio.Event().wait())
    try:
        with (
            patch.object(worker_api, "UI_URL", "https://ui.example"),
            patch.object(worker_api, "_heartbeat_task", live),
            patch.object(worker_api, "_start_heartbeat_task") as start,
        ):
            await worker_api._supervise_heartbeat_once()
        start.assert_not_called()
    finally:
        live.cancel()
        with pytest.raises(asyncio.CancelledError):
            await live


def test_compose_worker_healthcheck_checks_heartbeat_endpoint():
    from pathlib import Path

    text = Path("docker-compose.fleet.yml").read_text(encoding="utf-8")
    assert "healthcheck:" in text
    assert "/healthz" in text


def test_worker_image_and_bootstrap_keep_restart_and_heartbeat_health_contract():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    assert "/healthz" in (root / "Dockerfile.worker").read_text(encoding="utf-8")
    startup = (root / "azure_create" / "worker-startup.sh").read_text(encoding="utf-8")
    assert "ExecStartPost=/usr/bin/docker update --restart unless-stopped cashpilot-worker" in startup
