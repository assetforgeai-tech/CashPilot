"""Small, provider-wide EarnApp recovery policy.

The decision function is pure; callers persist the returned counters and action.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

FLATLINE_MINUTES = 120


@dataclass(frozen=True)
class LifecycleDecision:
    action: str
    same_proxy_recreates: int
    rotate_count: int
    reason: str = ""


def _when(value: Any, default: datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return default


def evaluate_node(snapshot: Mapping[str, Any], runtime: Mapping[str, Any], now: datetime | None = None) -> LifecycleDecision:
    """Return one simple action for a node snapshot without mutating state."""
    current = now or datetime.now(UTC)
    same = max(0, int(runtime.get("same_proxy_recreates") or 0))
    rotates = max(0, int(runtime.get("rotate_count") or 0))
    if bool(snapshot.get("auth_failed")):
        return LifecycleDecision("defer_auth", same, rotates, "account authentication requires retry")
    if str(runtime.get("proxy_health") or "").lower() == "unhealthy" or snapshot.get("egress_ok") is False:
        return LifecycleDecision("rotate_recreate", same, rotates + 1, "proxy health or egress mismatch")
    baseline = float(runtime.get("usage_baseline") or 0)
    usage = float(snapshot.get("usage") or 0)
    if usage > baseline:
        return LifecycleDecision("healthy", 0, 0, "positive usage delta")
    started = _when(runtime.get("window_started_at"), current)
    flatline = current - started >= timedelta(minutes=FLATLINE_MINUTES)
    if not flatline and not snapshot.get("banned"):
        return LifecycleDecision("observe", same, rotates)
    if same < 2:
        return LifecycleDecision("recreate", same + 1, rotates, "usage flatline or banned")
    return LifecycleDecision("rotate_recreate", 0, rotates + 1, "same-proxy recovery exhausted")
