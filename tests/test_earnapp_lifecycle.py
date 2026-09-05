from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app import main
from app.earnapp_lifecycle import evaluate_node
from app.version import at_least


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


@pytest.mark.parametrize(
    "actual, minimum, expected",
    [
        ("1.18.21", "1.18.21", True),
        ("v1.18.22", "1.18.21", True),
        ("1.18.20", "1.18.21", False),
        ("dev", "1.18.21", False),
    ],
)
def test_worker_capability_version_comparison_fails_closed(actual, minimum, expected):
    assert at_least(actual, minimum) is expected


def test_positive_usage_resets_recovery_counters():
    decision = evaluate_node({"usage": 11.0, "banned": False}, _runtime(), datetime.now(UTC))
    assert decision.action == "healthy"
    assert decision.same_proxy_recreates == 0


def test_flat_usage_restarts_without_recreate_or_proxy_rotation():
    now = datetime.now(UTC)
    decision = evaluate_node(
        {"usage": 10.0, "online": False, "banned": True},
        _runtime(same_proxy_recreates=2, rotate_count=3),
        now,
    )
    assert decision.action == "restart"
    assert decision.same_proxy_recreates == 0
    assert decision.rotate_count == 3


def test_new_or_restarted_node_gets_a_sixty_minute_admission_window():
    now = datetime.now(UTC)
    observe = evaluate_node(
        {"usage": 10.0, "banned": False},
        _runtime(window_started_at=(now - timedelta(minutes=59)).isoformat()),
        now,
    )
    recover = evaluate_node(
        {"usage": 10.0, "banned": False},
        _runtime(window_started_at=(now - timedelta(minutes=60)).isoformat()),
        now,
    )
    assert observe.action == "observe"
    assert recover.action == "restart"


def test_qualified_uptime_without_country_or_ip_waits_for_backend_assignment():
    now = datetime.now(UTC)
    decision = evaluate_node(
        {
            "usage": 0.0,
            "billing": "qualified_uptime",
            "online": True,
            "country_code": "",
            "ip": "",
            "banned": False,
        },
        _runtime(window_started_at=(now - timedelta(minutes=30)).isoformat()),
        now,
    )
    assert decision.action == "observe"


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
        AsyncMock(return_value={"earnapp_device_verification": {"device_id": "sdk-mac-2", "error_kind": "remote"}}),
    )
    monkeypatch.setattr(
        main.database,
        "get_latest_earnapp_snapshot",
        AsyncMock(
            return_value={
                "devices_json": '[{"device_id":"sdk-mac-2","online":true,"country_code":"VN","usage_current":1}]'
            }
        ),
    )
    update = AsyncMock(return_value=True)
    monkeypatch.setattr(main.database, "update_earnapp_lifecycle", update)

    await main._run_earnapp_lifecycle_scheduler()

    assert update.await_count == 1
    assert update.await_args.args[1].action == "healthy"


@pytest.mark.asyncio
async def test_scheduler_uses_uptime_for_qualified_uptime_billing(monkeypatch):
    node = {
        "logical_node_id": "earnapp-mac-qualified-uptime",
        "account_id": 470,
        "assigned_worker_id": 3098,
        "device_id": "sdk-mac-qualified-uptime",
        "state": "ACTIVE",
        "proxy_health": "healthy",
        "usage_baseline": 100.0,
        "window_started_at": (datetime.now(UTC) - timedelta(minutes=10)).isoformat(),
        "same_proxy_recreates": 2,
        "rotate_count": 1,
    }
    monkeypatch.setattr(main.database, "list_earnapp_logical_nodes", AsyncMock(return_value=[node]))
    monkeypatch.setattr(main.database, "get_provider_instance_spec", AsyncMock(return_value={}))
    monkeypatch.setattr(
        main.database,
        "get_latest_earnapp_snapshot",
        AsyncMock(
            return_value={
                "collected_at": datetime.now(UTC).isoformat(),
                "devices_json": (
                    '[{"device_id":"sdk-mac-qualified-uptime",'
                    '"billing":"qualified_uptime","usage_current":0,'
                    '"usage_total":0,"uptime":160,"total_uptime":160}]'
                ),
            }
        ),
    )
    update = AsyncMock(return_value=True)
    execute = AsyncMock(return_value=True)
    monkeypatch.setattr(main.database, "update_earnapp_lifecycle", update)
    monkeypatch.setattr(main, "_execute_earnapp_lifecycle_action", execute)

    await main._run_earnapp_lifecycle_scheduler()

    execute.assert_not_awaited()
    assert update.await_args.args[1].action == "healthy"
    assert update.await_args.kwargs["usage"] == 160.0


@pytest.mark.asyncio
async def test_scheduler_refreshes_stale_account_snapshot_before_flatline_recreate(monkeypatch):
    node = {
        "logical_node_id": "earnapp-mac-refresh",
        "account_id": 470,
        "assigned_worker_id": 3098,
        "device_id": "sdk-mac-refresh",
        "state": "ACTIVE",
        "proxy_health": "healthy",
        "usage_baseline": 100.0,
        "window_started_at": (datetime.now(UTC) - timedelta(minutes=10)).isoformat(),
        "same_proxy_recreates": 0,
        "rotate_count": 0,
    }
    monkeypatch.setattr(main.database, "list_earnapp_logical_nodes", AsyncMock(return_value=[node]))
    monkeypatch.setattr(main.database, "get_provider_instance_spec", AsyncMock(return_value={}))
    old = (datetime.now(UTC) - timedelta(minutes=70)).isoformat()
    stale = {"collected_at": old, "devices_json": '[{"device_id":"sdk-mac-refresh","online":true,"usage_current":100}]'}
    fresh = {
        "collected_at": datetime.now(UTC).isoformat(),
        "devices_json": '[{"device_id":"sdk-mac-refresh","online":true,"usage_current":160}]',
    }
    monkeypatch.setattr(main.database, "get_latest_earnapp_snapshot", AsyncMock(side_effect=[stale, fresh]))
    collect = AsyncMock(return_value={"status": "ok", "usage_current": 60})
    monkeypatch.setattr(main.earnapp_collection, "collect_account", collect)
    update = AsyncMock(return_value=True)
    execute = AsyncMock()
    monkeypatch.setattr(main.database, "update_earnapp_lifecycle", update)
    monkeypatch.setattr(main, "_execute_earnapp_lifecycle_action", execute)

    await main._run_earnapp_lifecycle_scheduler()

    collect.assert_awaited_once_with(470)
    execute.assert_not_awaited()
    assert update.await_args.args[1].action == "healthy"


@pytest.mark.asyncio
async def test_scheduler_executes_restart_decision_for_mutable_node(monkeypatch):
    node = {
        "logical_node_id": "earnapp-mac-recover",
        "account_id": 2,
        "assigned_worker_id": 3098,
        "device_id": "sdk-mac-recover",
        "state": "ACTIVE",
        "proxy_health": "healthy",
        "usage_baseline": 0.0,
        "window_started_at": (datetime.now(UTC) - timedelta(minutes=121)).isoformat(),
        "same_proxy_recreates": 0,
        "rotate_count": 0,
    }
    monkeypatch.setattr(main.database, "list_earnapp_logical_nodes", AsyncMock(return_value=[node]))
    monkeypatch.setattr(
        main.database,
        "get_worker",
        AsyncMock(return_value={"status": "online", "system_info": '{"version":"1.18.21"}'}),
    )
    monkeypatch.setattr(main.database, "get_provider_instance_spec", AsyncMock(return_value={"image": "img"}))
    monkeypatch.setattr(
        main.database,
        "get_latest_earnapp_snapshot",
        AsyncMock(return_value={"devices_json": '[{"device_id":"sdk-mac-recover","online":true,"usage_current":0}]'}),
    )
    update = AsyncMock(return_value=True)
    deploy = AsyncMock(return_value={"status": "restarted"})
    monkeypatch.setattr(main.database, "update_earnapp_lifecycle", update)
    monkeypatch.setattr(main, "_execute_earnapp_lifecycle_action", deploy)

    await main._run_earnapp_lifecycle_scheduler()

    deploy.assert_awaited_once_with(node, "restart")
    persisted = update.await_args.kwargs["window_started_at"]
    assert datetime.now(UTC) - datetime.fromisoformat(persisted) < timedelta(seconds=5)


@pytest.mark.asyncio
async def test_scheduler_does_not_advance_recovery_after_failed_mutation(monkeypatch):
    node = {
        "logical_node_id": "earnapp-mac-recover",
        "account_id": 2,
        "assigned_worker_id": 3098,
        "device_id": "sdk-mac-recover",
        "state": "ACTIVE",
        "proxy_health": "healthy",
        "usage_baseline": 0.0,
        "window_started_at": (datetime.now(UTC) - timedelta(minutes=121)).isoformat(),
        "same_proxy_recreates": 0,
        "rotate_count": 0,
    }
    monkeypatch.setattr(main.database, "list_earnapp_logical_nodes", AsyncMock(return_value=[node]))
    monkeypatch.setattr(
        main.database,
        "get_worker",
        AsyncMock(return_value={"status": "online", "system_info": '{"version":"1.18.21"}'}),
    )
    monkeypatch.setattr(main.database, "get_provider_instance_spec", AsyncMock(return_value={"image": "img"}))
    monkeypatch.setattr(
        main.database,
        "get_latest_earnapp_snapshot",
        AsyncMock(return_value={"devices_json": '[{"device_id":"sdk-mac-recover","usage_current":0}]'}),
    )
    update = AsyncMock(return_value=True)
    monkeypatch.setattr(main.database, "update_earnapp_lifecycle", update)
    monkeypatch.setattr(main, "_execute_earnapp_lifecycle_action", AsyncMock(return_value=False))

    await main._run_earnapp_lifecycle_scheduler()

    update.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "worker, should_execute",
    [
        ({"status": "online", "system_info": '{"version":"1.18.21"}'}, True),
        ({"status": "online", "system_info": '{"version":"1.18.20"}'}, False),
        ({"status": "online", "system_info": "{}"}, False),
        ({"status": "offline", "system_info": '{"version":"1.18.21"}'}, False),
    ],
)
async def test_scheduler_mutates_only_workers_supporting_lifecycle_api(monkeypatch, worker, should_execute):
    node = {
        "logical_node_id": "earnapp-mac-capability-gate",
        "account_id": 2,
        "assigned_worker_id": 3098,
        "device_id": "sdk-mac-capability-gate",
        "state": "ACTIVE",
        "proxy_health": "healthy",
        "usage_baseline": 0.0,
        "window_started_at": (datetime.now(UTC) - timedelta(minutes=121)).isoformat(),
        "same_proxy_recreates": 0,
        "rotate_count": 0,
    }
    monkeypatch.setattr(main.database, "list_earnapp_logical_nodes", AsyncMock(return_value=[node]))
    monkeypatch.setattr(main.database, "get_worker", AsyncMock(return_value=worker))
    monkeypatch.setattr(main.database, "get_provider_instance_spec", AsyncMock(return_value={"image": "img"}))
    monkeypatch.setattr(
        main.database,
        "get_latest_earnapp_snapshot",
        AsyncMock(return_value={"devices_json": '[{"device_id":"sdk-mac-capability-gate","usage_current":0}]'}),
    )
    update = AsyncMock(return_value=True)
    execute = AsyncMock(return_value=True)
    monkeypatch.setattr(main.database, "update_earnapp_lifecycle", update)
    monkeypatch.setattr(main, "_execute_earnapp_lifecycle_action", execute)

    await main._run_earnapp_lifecycle_scheduler()

    assert execute.await_count == (1 if should_execute else 0)
    if not should_execute:
        update.assert_not_awaited()


@pytest.mark.asyncio
async def test_restart_action_calls_cas_scoped_worker_route(monkeypatch):
    node = {
        "logical_node_id": "earnapp-mac-recover",
        "assigned_worker_id": 3098,
        "generation": 3,
        "device_id": "sdk-mac-" + "a" * 32,
        "platform": "macos",
    }
    proxy = AsyncMock(return_value={"status": "restarted"})
    monkeypatch.setattr(main, "_proxy_to_worker", proxy)

    assert await main._execute_earnapp_lifecycle_action(node, "restart") is True
    proxy.assert_awaited_once_with(
        3098,
        "POST",
        "/api/earnapp/docker-nodes/earnapp-mac-recover/restart",
        json={"generation": 3, "device_id": "sdk-mac-" + "a" * 32},
        timeout=180,
    )
