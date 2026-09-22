"""Pure heartbeat freshness policy for worker-scoped resources.

This module deliberately has no database, network, or provider dependencies.  It
only translates a heartbeat timestamp into a lifecycle decision; callers own the
atomic reclamation transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

OFFLINE_AFTER_SECONDS: Final = 3 * 60
RECLAIM_AFTER_SECONDS: Final = 15 * 60


class WorkerStatus(StrEnum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    RECLAIM_ALL_WORKER_RESOURCES = "RECLAIM_ALL_WORKER_RESOURCES"


class WorkerResourceFamily(StrEnum):
    PROXY_LEASES = "proxy_leases"
    NKN_WALLET_LEASES = "nkn_wallet_leases"
    MYST_WALLET_LEASES = "myst_wallet_leases"
    RUNTIME_ASSIGNMENTS = "runtime_assignments"
    CAPACITY_RESERVATIONS = "capacity_reservations"


RECLAIMABLE_RESOURCE_FAMILIES: Final[tuple[WorkerResourceFamily, ...]] = tuple(WorkerResourceFamily)
PRESERVED_OWNERSHIP: Final[tuple[str, ...]] = (
    "provider_credentials",
    "account_pool_membership",
    "earnapp_account_egress_sticky_ownership",
    "paypal_ownership",
    "historical_evidence",
)


@dataclass(frozen=True, slots=True)
class WorkerResourceDecision:
    """Decision returned by :func:`decide_worker_resource_state`."""

    status: WorkerStatus
    age_seconds: float | None
    reclaim_families: tuple[WorkerResourceFamily, ...] = ()
    preserve_ownership: tuple[str, ...] = PRESERVED_OWNERSHIP

    @property
    def should_reclaim(self) -> bool:
        return self.status is WorkerStatus.RECLAIM_ALL_WORKER_RESOURCES


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def decide_worker_resource_state(
    last_heartbeat: datetime | None,
    *,
    now: datetime | None = None,
) -> WorkerResourceDecision:
    """Return the worker state from heartbeat freshness alone.

    A missing heartbeat timestamp is treated as ``OFFLINE`` but is never enough
    to trigger destructive reclamation.  The scheduler must observe elapsed
    time from a real heartbeat before reclaiming resources.
    """

    if last_heartbeat is None:
        return WorkerResourceDecision(WorkerStatus.OFFLINE, None)

    observed_at = _as_utc(now or datetime.now(UTC))
    heartbeat_at = _as_utc(last_heartbeat)
    age_seconds = max(0.0, (observed_at - heartbeat_at).total_seconds())
    if age_seconds >= RECLAIM_AFTER_SECONDS:
        return WorkerResourceDecision(
            WorkerStatus.RECLAIM_ALL_WORKER_RESOURCES,
            age_seconds,
            RECLAIMABLE_RESOURCE_FAMILIES,
        )
    if age_seconds >= OFFLINE_AFTER_SECONDS:
        return WorkerResourceDecision(WorkerStatus.OFFLINE, age_seconds)
    return WorkerResourceDecision(WorkerStatus.ONLINE, age_seconds)


# Short alias for callers that prefer a policy-shaped verb.
evaluate_worker_heartbeat = decide_worker_resource_state
