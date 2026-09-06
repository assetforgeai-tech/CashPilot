"""Small, provider-wide EarnApp recovery policy.

The decision function is pure; callers persist the returned counters and action.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

# A short flatline window lets the worker recover promptly; the account API
# can lag, so this is still long enough to avoid reacting to one poll.
# EarnApp may take tens of minutes to assign country and admit workload.  Do
# not mutate a node during that admission window.
FLATLINE_MINUTES = 60
EARNINGS_ZERO_GRACE_MINUTES = 5
_UPTIME_BILLING = frozenset({"uptime", "fixed", "qualified_uptime"})


@dataclass(frozen=True)
class LifecycleDecision:
    action: str
    same_proxy_recreates: int
    rotate_count: int
    reason: str = ""
    earnings_zero_observed_at: str | None = None
    clear_earnings_zero_observed: bool = False


def effective_usage(snapshot: Mapping[str, Any]) -> float:
    """Return the workload counter appropriate for the account billing mode."""
    billing = str(snapshot.get("billing") or "").strip().lower()
    keys = (
        ("uptime", "total_uptime", "earned_total", "usage_total", "usage_current")
        if billing in _UPTIME_BILLING
        else (
            "usage_total",
            "usage_current",
            "bandwidth",
            "total_bandwidth",
            "earned_total",
        )
    )
    values = []
    for key in keys:
        try:
            value = float(snapshot.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            values.append(value)
    return max(values, default=0.0)


def _when(value: Any, default: datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return default


def evaluate_node(
    snapshot: Mapping[str, Any], runtime: Mapping[str, Any], now: datetime | None = None
) -> LifecycleDecision:
    """Return one simple action for a node snapshot without mutating state."""
    current = now or datetime.now(UTC)
    same = max(0, int(runtime.get("same_proxy_recreates") or 0))
    rotates = max(0, int(runtime.get("rotate_count") or 0))
    if bool(snapshot.get("auth_failed")):
        return LifecycleDecision("defer_auth", same, rotates, "account authentication requires retry")
    billing = str(snapshot.get("billing") or "").strip().lower()
    awaiting_country = (
        billing in _UPTIME_BILLING
        and snapshot.get("online") is True
        and not str(snapshot.get("country_code") or snapshot.get("country") or "").strip()
        and not str(snapshot.get("ip") or snapshot.get("public_ip") or "").strip()
        and not snapshot.get("banned")
    )
    if str(runtime.get("proxy_health") or "").lower() == "unhealthy" or snapshot.get("egress_ok") is False:
        return LifecycleDecision("rotate_recreate", same, rotates + 1, "proxy health or egress mismatch")
    baseline = float(runtime.get("usage_baseline") or 0)
    usage = float(snapshot.get("usage") or 0)
    if usage > baseline:
        return LifecycleDecision("healthy", 0, 0, "positive usage delta", clear_earnings_zero_observed=True)
    counter_ms = snapshot.get("earnings_update_in_ms")
    counter_available = counter_ms is not None
    if counter_ms is not None:
        try:
            counter_value = float(counter_ms)
            flatline = counter_value <= 0
        except (TypeError, ValueError):
            counter_value = None
            flatline = False
    else:
        counter_value = None
        started = _when(runtime.get("window_started_at"), current)
        flatline = current - started >= timedelta(minutes=FLATLINE_MINUTES)
    if counter_available and counter_value is not None and counter_value > 0:
        zero_seen = runtime.get("earnings_zero_observed_at")
        if zero_seen:
            return LifecycleDecision(
                "healthy" if usage > baseline else "observe",
                0 if usage > baseline else same,
                0 if usage > baseline else rotates,
                "positive usage delta" if usage > baseline else "earnings update cycle active",
                clear_earnings_zero_observed=True,
            )
    elif counter_available and flatline and not snapshot.get("banned"):
        zero_seen = runtime.get("earnings_zero_observed_at")
        if not zero_seen:
            return LifecycleDecision(
                "observe",
                same,
                rotates,
                "earnings update boundary observed; waiting for post-cycle usage",
                earnings_zero_observed_at=current.isoformat(),
            )
        zero_at = _when(zero_seen, current)
        if current - zero_at < timedelta(minutes=EARNINGS_ZERO_GRACE_MINUTES):
            return LifecycleDecision("observe", same, rotates, "waiting for post-cycle earnings refresh")
    if awaiting_country and not flatline:
        return LifecycleDecision("observe", same, rotates, "awaiting account-side country assignment")
    if not flatline and not snapshot.get("banned"):
        return LifecycleDecision("observe", same, rotates)
    # A healthy route with a flatline is a workload/admission problem, not
    # proof that the identity or proxy should be replaced. Restart in place so
    # the device, volume and lease remain stable.
    return LifecycleDecision("restart", 0, rotates, "usage flatline or banned")
