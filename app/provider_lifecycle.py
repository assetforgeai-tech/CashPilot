"""Small provider-wide lifecycle decision helper.

The helper is deliberately read-only. Callers own persistence and provider
specific execution (for example EarnApp's cycle guard).
"""

from __future__ import annotations

from collections.abc import Mapping

from app import provider_runtime


def decide(
    provider: str,
    *,
    online: bool | None,
    banned: bool,
    proxy_healthy: bool | None,
    usage_stalled: bool = False,
    direct_route_healthy: bool | None = None,
    provider_auth_healthy: bool | None = None,
    account_suspended: bool = False,
) -> str:
    """Return ``restart``, ``recreate``, ``rotate`` or ``observe``."""
    runtime = provider_runtime.get(str(provider or "").strip().lower())
    if runtime is None:
        return "observe"
    selected = "direct" if "direct" in runtime.modes and "proxy" not in runtime.modes else "proxy"
    if provider_auth_healthy is False or account_suspended:
        return runtime.lifecycle_action(selected, "provider_auth_unhealthy")
    if direct_route_healthy is False and "direct" in runtime.modes:
        return runtime.lifecycle_action("direct", "direct_route_unhealthy")
    if banned:
        return runtime.lifecycle_action(selected, "banned")
    if online is False:
        return runtime.lifecycle_action(selected, "offline")
    if proxy_healthy is False and "proxy" in runtime.modes:
        return runtime.lifecycle_action("proxy", "proxy_unhealthy")
    if usage_stalled:
        return runtime.lifecycle_action(selected, "usage_stalled")
    return "observe"


def decide_lane(
    provider: str,
    *,
    mode: str,
    online: bool | None,
    banned: bool,
    proxy_healthy: bool | None,
    usage_stalled: bool = False,
    direct_route_healthy: bool | None = None,
    provider_auth_healthy: bool | None = None,
    account_suspended: bool = False,
) -> str:
    """Apply lifecycle signals to one explicit direct/proxy lane."""
    runtime = provider_runtime.get(str(provider or "").strip().lower())
    selected = str(mode or "").strip().lower()
    if runtime is None or selected not in runtime.modes:
        return "observe"
    if provider_auth_healthy is False or account_suspended:
        return runtime.lifecycle_action(selected, "provider_auth_unhealthy")
    if selected == "direct" and direct_route_healthy is False:
        return runtime.lifecycle_action(selected, "direct_route_unhealthy")
    if banned:
        return runtime.lifecycle_action(selected, "banned")
    if online is False:
        return runtime.lifecycle_action(selected, "offline")
    if selected == "proxy" and proxy_healthy is False:
        return runtime.lifecycle_action(selected, "proxy_unhealthy")
    if usage_stalled:
        return runtime.lifecycle_action(selected, "usage_stalled")
    return "observe"


def decide_instance(instance: Mapping[str, object]) -> str:
    """Dispatch one persisted provider instance using its explicit lane."""
    provider = str(instance.get("provider_slug") or instance.get("slug") or "").strip().lower()
    mode = str(instance.get("mode") or "").strip().lower()
    if not provider or not mode:
        return "observe"
    return decide_lane(
        provider,
        mode=mode,
        online=instance.get("online") if "online" in instance else None,
        banned=bool(instance.get("banned")),
        proxy_healthy=instance.get("proxy_healthy") if "proxy_healthy" in instance else None,
        usage_stalled=bool(instance.get("usage_stalled")),
        direct_route_healthy=instance.get("direct_route_healthy") if "direct_route_healthy" in instance else None,
        provider_auth_healthy=instance.get("provider_auth_healthy") if "provider_auth_healthy" in instance else None,
        account_suspended=bool(instance.get("account_suspended")),
    )
