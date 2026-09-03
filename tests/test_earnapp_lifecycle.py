from datetime import UTC, datetime, timedelta

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
    assert evaluate_node({"usage": 10, "banned": False}, _runtime(proxy_health="unhealthy"), now).action == "rotate_recreate"
    assert evaluate_node({"usage": 10, "banned": False, "auth_failed": True}, _runtime(), now).action == "defer_auth"
