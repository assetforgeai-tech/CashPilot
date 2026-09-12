from datetime import UTC, datetime

import pytest

from app.earnapp_lifecycle import evaluate_node


def _runtime(**overrides):
    value = {
        "proxy_health": "healthy",
        "usage_baseline": 10.0,
        "same_proxy_recreates": 0,
        "rotate_count": 0,
        "window_started_at": "2026-09-08T00:00:00+00:00",
    }
    value.update(overrides)
    return value


@pytest.mark.parametrize(
    ("snapshot", "runtime", "action"),
    [
        ({"usage": 10, "online": False, "banned": False}, _runtime(), "restart"),
        ({"usage": 10, "online": True, "banned": True}, _runtime(), "restart"),
        ({"usage": 10, "online": True, "banned": False}, _runtime(proxy_health="unhealthy"), "rotate_recreate"),
        ({"usage": 10, "online": False, "banned": False, "auth_failed": True}, _runtime(), "defer_auth"),
        ({"usage": 11, "online": True, "banned": False}, _runtime(), "healthy"),
    ],
)
def test_unified_recovery_policy(snapshot, runtime, action):
    assert evaluate_node(snapshot, runtime, datetime(2026, 9, 8, 1, tzinfo=UTC)).action == action


def test_banned_never_falls_through_to_offline_restart():
    decision = evaluate_node(
        {"usage": 10, "online": False, "banned": True, "earnings_update_in_ms": 0},
        _runtime(),
        datetime(2026, 9, 8, 1, tzinfo=UTC),
    )
    assert decision.action == "restart"


def test_offline_takes_priority_over_positive_usage_and_restarts_in_place():
    decision = evaluate_node(
        {"usage": 11, "online": False, "banned": False},
        _runtime(),
    )
    assert decision.action == "restart"
