"""Durable Proxy Pool state authority.

The SQLite transaction helpers stay in :mod:`app.database` so schema and CAS
changes remain in one owner. This module is the narrow import boundary for the
probe scheduler and rotation worker; it does not perform provider or worker
side effects.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app import database


async def record_proxy_probe_transition(
    proxy_id: int,
    result: Mapping[str, Any],
    *,
    generation: int,
) -> dict[str, Any]:
    return await database.record_proxy_probe_transition(proxy_id, result, generation=generation)


async def enqueue_proxy_rotation_requests(proxy_id: int, probe_generation: int) -> int:
    return await database.enqueue_proxy_rotation_requests(proxy_id, probe_generation)


async def claim_proxy_rotation_request(now: Any = None) -> dict[str, Any] | None:
    return await database.claim_proxy_rotation_request(now)


async def complete_proxy_rotation_request(
    request_id: int,
    state: str,
    *,
    error: str = "",
    lease_token: str = "",
    replacement_committed: bool = False,
) -> bool:
    return await database.complete_proxy_rotation_request(
        request_id,
        state,
        error=error,
        lease_token=lease_token,
        replacement_committed=replacement_committed,
    )


__all__ = [
    "claim_proxy_rotation_request",
    "complete_proxy_rotation_request",
    "enqueue_proxy_rotation_requests",
    "record_proxy_probe_transition",
]
