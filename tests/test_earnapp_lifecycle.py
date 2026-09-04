from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app import main
from app.earnapp_lifecycle import evaluate_node


def _runtime(**overrides):
    value = {
        "state": "ACTIVE",
        "proxy_health": "healthy",
        "usage_baseline": 10.0,
        "same_proxy_recreates": 0,
        "rotate_count": 0,
        "window_started_at": (datetime.now(UTC) - timedelta(minutes=121)).isoformat(),
    }
    value.update(overrides)
    return value


def test_positive_usage_resets_recovery_counters():
    decision = evaluate_node({"usage": 11.0, "banned": False}, _runtime(), datetime.now(UTC))
    assert decision.action == "healthy"
    assert decision.same_proxy_recreates == 0


def test_flat_usage_recreates_same_proxy_twice_then_rotates():
    now = datetime.now(UTC)
    first = evaluate_node({"usage": 10.0, "banned": False}, _runtime(same_proxy_recreates=0), now)
    second = evaluate_node({"usage": 10.0, "banned": False}, _runtime(same_proxy_recreates=1), now)
    third = evaluate_node({"usage": 10.0, "banned": False}, _runtime(same_proxy_recreates=2), now)
    assert first.action == second.action == "recreate"
    assert third.action == "rotate_recreate"


def test_proxy_failure_rotates_immediately_and_auth_failure_is_deferred():
    now = datetime.now(UTC)
    assert (
        evaluate_node({"usage": 10, "banned": False}, _runtime(proxy_health="unhealthy"), now).action
        == "rotate_recreate"
    )
    assert evaluate_node({"usage": 10, "banned": False, "auth_failed": True}, _runtime(), now).action == "defer_auth"


@pytest.mark.asyncio
async def test_scheduler_persists_initial_flatline_window(monkeypatch):
    node = {
        "logical_node_id": "earnapp-mac-1",
        "state": "ACTIVE",
        "proxy_health": "healthy",
        "usage_baseline": 0.0,
        "window_started_at": None,
        "same_proxy_recreates": 0,
        "rotate_count": 0,
    }
    monkeypatch.setattr(main.database, "list_earnapp_logical_nodes", AsyncMock(return_value=[node]))
    monkeypatch.setattr(main.database, "get_latest_earnapp_snapshot", AsyncMock(return_value=None))
    monkeypatch.setattr(
        main.database,
        "get_provider_instance_spec",
        AsyncMock(return_value={"earnapp_device_verification": {"usage_current": 0.0, "banned": False}}),
    )
    update = AsyncMock(return_value=True)
    monkeypatch.setattr(main.database, "update_earnapp_lifecycle", update)

    before = datetime.now(UTC)
    await main._run_earnapp_lifecycle_scheduler()
    after = datetime.now(UTC)

    persisted = update.await_args.kwargs["window_started_at"]
    assert before <= datetime.fromisoformat(persisted) <= after


@pytest.mark.asyncio
async def test_scheduler_uses_latest_account_snapshot_when_spec_has_no_evidence(monkeypatch):
    node = {
        "logical_node_id": "earnapp-mac-1",
        "account_id": 2,
        "device_id": "sdk-mac-1",
        "state": "ACTIVE",
        "proxy_health": "healthy",
        "usage_baseline": 0.0,
        "window_started_at": None,
        "same_proxy_recreates": 0,
        "rotate_count": 0,
    }
    monkeypatch.setattr(main.database, "list_earnapp_logical_nodes", AsyncMock(return_value=[node]))
    monkeypatch.setattr(main.database, "get_provider_instance_spec", AsyncMock(return_value={}))
    monkeypatch.setattr(
        main.database,
        "get_latest_earnapp_snapshot",
        AsyncMock(return_value={"devices_json": '[{"device_id":"sdk-mac-1","online":true,"usage_current":0}]'}),
    )
    update = AsyncMock(return_value=True)
    monkeypatch.setattr(main.database, "update_earnapp_lifecycle", update)
    await main._run_earnapp_lifecycle_scheduler()
    assert update.await_count == 1


@pytest.mark.asyncio
async def test_scheduler_prefers_latest_account_snapshot_over_stale_spec_evidence(monkeypatch):
    node = {
        "logical_node_id": "earnapp-mac-2",
        "account_id": 470,
        "device_id": "sdk-mac-2",
        "state": "ACTIVE",
        "proxy_health": "healthy",
        "usage_baseline": 0.0,
        "window_started_at": None,
        "same_proxy_recreates": 0,
        "rotate_count": 0,
    }
    monkeypatch.setattr(main.database, "list_earnapp_logical_nodes", AsyncMock(return_value=[node]))
    monkeypatch.setattr(
        main.database,
        "get_provider_instance_spec",
        AsyncMock(
            return_value={
                "earnapp_device_verification": {"device_id": "sdk-mac-2", "error_kind": "remote"},
            }
        ),
    )
    monkeypatch.setattr(
        main.database,
        "get_latest_earnapp_snapshot",
        AsyncMock(
            return_value={
                "devices_json": '[{"device_id":"sdk-mac-2","online":true,"country_code":"VN","usage_current":1}]',
            }
        ),
    )
    update = AsyncMock(return_value=True)
    monkeypatch.setattr(main.database, "update_earnapp_lifecycle", update)
    await main._run_earnapp_lifecycle_scheduler()
    assert update.await_args.args[1].action == "healthy"
