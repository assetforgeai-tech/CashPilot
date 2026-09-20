"""Guarded fault injection for disposable EarnApp rotation canaries.

This deliberately does not mutate a production node.  It produces the same
proxy-health failure evidence consumed by the staged replacement transaction,
so orchestration can be proven without waiting for a real outage.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

ALLOWED_WORKERS = frozenset({118903, 118904})
CANARY_PREFIX = "earnapp-disposable-"


class FaultInjectionRejected(ValueError):
    """The request is not sufficiently isolated to be used as a canary."""


@dataclass(frozen=True)
class FaultInjectionRequest:
    logical_node_id: str
    worker_id: int
    nonce: str
    proxy_id: int
    proxy_host: str = ""
    proxy_port: int = 0


def validate_request(request: FaultInjectionRequest) -> None:
    """Reject anything that could target a real managed node."""
    node_id = request.logical_node_id.strip().lower()
    if not node_id.startswith(CANARY_PREFIX):
        raise FaultInjectionRejected("fault injection requires a disposable canary slug")
    if request.worker_id not in ALLOWED_WORKERS:
        raise FaultInjectionRejected("worker is outside the live canary scope")
    if len(request.nonce.strip()) < 16:
        raise FaultInjectionRejected("explicit canary nonce is required")
    if request.proxy_id <= 0:
        raise FaultInjectionRejected("a candidate proxy is required")


def failed_proxy_evidence(request: FaultInjectionRequest) -> dict[str, Any]:
    """Return deterministic failure evidence in the normal health schema."""
    validate_request(request)
    return {
        "fault_injected": True,
        "proxy_health": "unhealthy",
        "reason": "fault_injected_proxy_failure",
        "proxy_id": request.proxy_id,
        "worker_id": request.worker_id,
        "logical_node_id": request.logical_node_id,
        "nonce": request.nonce,
        "egress_ip": None,
        "direct_fallback_blocked": True,
    }


def is_disposable_candidate(candidate: Mapping[str, Any]) -> bool:
    """Keep injected candidates out of normal production allocator results."""
    return str(candidate.get("logical_node_id") or "").lower().startswith(CANARY_PREFIX)


async def run_repeated_failure_gate(
    request: FaultInjectionRequest,
    *,
    record_health: Any,
    rotate: Any,
    threshold: int = 3,
) -> dict[str, Any]:
    """Drive the normal repeated-health gate without a production outage.

    ``record_health`` and ``rotate`` are the existing database/lifecycle
    adapters.  No test-only rotation shortcut is used; the caller supplies
    the same functions used by heartbeat reconciliation.
    """
    validate_request(request)
    if threshold < 1:
        raise FaultInjectionRejected("health threshold must be positive")
    evidence = failed_proxy_evidence(request)
    for _ in range(threshold):
        accepted = await record_health(evidence)
        if not accepted:
            raise FaultInjectionRejected("canary health evidence was not accepted")
    rotated = await rotate(evidence)
    return {**evidence, "failure_samples": threshold, "rotation_requested": bool(rotated)}
