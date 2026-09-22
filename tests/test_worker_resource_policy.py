from datetime import UTC, datetime, timedelta

from app.worker_resource_policy import (
    OFFLINE_AFTER_SECONDS,
    PRESERVED_OWNERSHIP,
    RECLAIM_AFTER_SECONDS,
    WorkerResourceFamily,
    WorkerStatus,
    decide_worker_resource_state,
)


def test_heartbeat_policy_boundaries_are_explicit():
    now = datetime(2026, 9, 22, tzinfo=UTC)
    assert decide_worker_resource_state(now, now=now).status is WorkerStatus.ONLINE
    assert (
        decide_worker_resource_state(now - timedelta(seconds=OFFLINE_AFTER_SECONDS), now=now).status
        is WorkerStatus.OFFLINE
    )
    decision = decide_worker_resource_state(now - timedelta(seconds=RECLAIM_AFTER_SECONDS), now=now)
    assert decision.status is WorkerStatus.RECLAIM_ALL_WORKER_RESOURCES
    assert decision.should_reclaim
    assert decision.reclaim_families == tuple(WorkerResourceFamily)


def test_missing_heartbeat_never_triggers_destructive_reclaim():
    decision = decide_worker_resource_state(None, now=datetime.now(UTC))
    assert decision.status is WorkerStatus.OFFLINE
    assert not decision.should_reclaim
    assert decision.reclaim_families == ()


def test_naive_timestamps_are_interpreted_as_utc_and_ownership_is_preserved():
    now = datetime(2026, 9, 22, 12, 0, 0)
    decision = decide_worker_resource_state(now - timedelta(seconds=RECLAIM_AFTER_SECONDS + 1), now=now)
    assert decision.should_reclaim
    assert decision.preserve_ownership == PRESERVED_OWNERSHIP
