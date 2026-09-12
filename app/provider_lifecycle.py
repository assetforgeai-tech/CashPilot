"""Small provider-wide lifecycle decision helper.

The helper is deliberately read-only. Callers own persistence and provider
specific execution (for example EarnApp's cycle guard).
"""

from __future__ import annotations

from app import provider_runtime


def decide(provider: str, *, online: bool | None, banned: bool, proxy_healthy: bool | None) -> str:
    """Return ``restart``, ``recreate``, ``rotate`` or ``observe``."""
    runtime = provider_runtime.get(str(provider or "").strip().lower())
    if runtime is None:
        return "observe"
    if banned and str(provider or "").strip().lower() == "earnapp":
        return "restart"
    if banned:
        return "recreate"
    if online is False:
        return "restart"
    if proxy_healthy is False and "proxy" in runtime.modes:
        return "rotate"
    return "observe"


def decide_lane(
    provider: str,
    *,
    mode: str,
    online: bool | None,
    banned: bool,
    proxy_healthy: bool | None,
) -> str:
    """Apply lifecycle signals to one explicit direct/proxy lane."""
    runtime = provider_runtime.get(str(provider or "").strip().lower())
    selected = str(mode or "").strip().lower()
    if runtime is None or selected not in runtime.modes:
        return "observe"
    if banned:
        return "recreate"
    if online is False:
        return "restart"
    if selected == "proxy" and proxy_healthy is False:
        return "rotate"
    return "observe"
