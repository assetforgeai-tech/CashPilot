"""Provider-runtime truth matrix for the active CashPilot providers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

Mode = Literal["direct", "proxy"]
CollectorKind = Literal["earnings", "dashboard_only", "count_only"]
DeploymentPolicy = Literal["enabled", "vps_runtime_prohibited"]

# Keep the compliance decision in the provider truth matrix so the catalog,
# API and UI all expose the same policy without inferring it from a Docker
# image or from historical deployments.
VPS_RUNTIME_BLOCK_REASON = "vps_runtime_prohibited"
VPS_RUNTIME_BLOCK_MESSAGE = (
    "EarnApp prohibits virtual machines, containers, and hosting services; "
    "CashPilot keeps collection and historical state available but blocks new VPS runtime deployment."
)


@dataclass(frozen=True)
class ProviderRuntime:
    slug: str
    setup_file: str
    collector_file: str
    modes: tuple[Mode, ...]
    collector_kind: CollectorKind
    deployment_allowed: bool = True
    deployment_policy: DeploymentPolicy = "enabled"
    policy_message: str = ""

    @property
    def default_mode(self) -> str:
        return "both" if set(self.modes) == {"direct", "proxy"} else self.modes[0]

    @property
    def count_only(self) -> bool:
        return self.collector_kind == "count_only"

    @property
    def manual_only(self) -> bool:
        return self.collector_kind != "earnings"

    @property
    def deployment_policy_message(self) -> str:
        """Compatibility name used by dashboard clients for policy copy."""
        return self.policy_message


PROVIDERS: dict[str, ProviderRuntime] = {
    "earnfm": ProviderRuntime("earnfm", "earn.fm.py", "earn.fm.py", ("direct", "proxy"), "earnings"),
    "earnapp": ProviderRuntime(
        "earnapp",
        "earnapp.py",
        "earnapp.py",
        ("proxy",),
        "earnings",
        False,
        VPS_RUNTIME_BLOCK_REASON,
        VPS_RUNTIME_BLOCK_MESSAGE,
    ),
    "iproyal": ProviderRuntime("iproyal", "pawns.py", "pawns.py", ("proxy",), "earnings"),
    "mysterium": ProviderRuntime("mysterium", "MYST.py", "MYST.py", ("direct",), "earnings"),
    "nkn": ProviderRuntime("nkn", "nkn.py", "nkn.py", ("direct",), "dashboard_only"),
    "packetstream": ProviderRuntime("packetstream", "packetstream.py", "packetstream.py", ("proxy",), "earnings"),
    "proxies-sx": ProviderRuntime("proxies-sx", "proxies.sx.py", "proxies.sx.py", ("proxy",), "earnings"),
    "proxybase": ProviderRuntime(
        "proxybase", "proxybase.org.py", "proxybase.org.py", ("direct", "proxy"), "dashboard_only"
    ),
    "proxybase-xyz": ProviderRuntime(
        "proxybase-xyz", "proxybase.xyz.py", "proxybase.xyz.py", ("direct", "proxy"), "count_only"
    ),
    "proxyrack": ProviderRuntime("proxyrack", "proxyrack.org.py", "proxyrack.org.py", ("direct", "proxy"), "earnings"),
    "repocket": ProviderRuntime("repocket", "repocket.py", "repocket.py", ("direct", "proxy"), "earnings"),
    "spide": ProviderRuntime("spide", "spide.py", "spide.py", ("direct", "proxy"), "dashboard_only"),
    "traffmonetizer": ProviderRuntime(
        "traffmonetizer", "traffmonetizer.py", "traffmonetizer.py", ("direct", "proxy"), "earnings"
    ),
    "uprock": ProviderRuntime("uprock", "Uprock.py", "Uprock.py", ("proxy",), "count_only"),
    "urnetwork": ProviderRuntime("urnetwork", "URNetwork.py", "URNetwork.py", ("direct", "proxy"), "dashboard_only"),
    "wipter": ProviderRuntime("wipter", "Wipter.py", "Wipter.py", ("proxy",), "count_only"),
}

ACTIVE_SLUGS = frozenset(PROVIDERS)


def get(slug: str) -> ProviderRuntime | None:
    return PROVIDERS.get(slug)


def deployment_block(slug: str, spec: object = None) -> ProviderRuntime | None:
    """Return the disabled runtime named by a route slug or raw deploy spec."""
    route_slug = str(slug or "").strip().lower()
    spec_slug = ""
    if isinstance(spec, dict):
        spec_slug = str(spec.get("provider_slug") or "").strip().lower()
    if is_runtime_instance(route_slug, spec_slug):
        policy = get("earnapp")
        return policy if policy and not policy.deployment_allowed else None
    for candidate in (spec_slug, route_slug):
        provider = get(candidate)
        if provider and not provider.deployment_allowed:
            return provider
    return None


def mutation_block(slug: str = "", spec: object = None) -> ProviderRuntime | None:
    """Return the policy that blocks mutations for a disabled runtime.

    Deployment checks protect new instances, while this narrower helper is used
    by reconciliation and lifecycle paths that could mutate an existing
    provider runtime or its lease.  Keep the distinction explicit so enabling a
    provider later does not silently change the generic deployment semantics.
    """
    route_slug = str(slug or "").strip().lower()
    spec_slug = ""
    if isinstance(spec, Mapping):
        spec_slug = str(spec.get("provider_slug") or "").strip().lower()
    policy = get("earnapp")
    if policy and not policy.deployment_allowed and is_runtime_instance(route_slug, spec_slug):
        return policy
    return None


def is_runtime_instance(slug: str, provider_slug: str = "") -> bool:
    """Recognize a disabled provider's catalog slug and historical instances."""
    instance_slug = str(slug or "").strip().lower()
    canonical_slug = str(provider_slug or "").strip().lower()
    return canonical_slug == "earnapp" or instance_slug == "earnapp" or instance_slug.startswith("earnapp-")


def supported_modes(slug: str) -> set[str]:
    provider = get(slug)
    return set(provider.modes) if provider else {"direct"}


def default_mode(slug: str) -> str:
    provider = get(slug)
    return provider.default_mode if provider else "direct"


def catalog_runtime(slug: str) -> dict[str, object]:
    provider = get(slug)
    if not provider:
        return {}
    return {
        "modes": list(provider.modes),
        "default_mode": provider.default_mode,
        "collector_kind": provider.collector_kind,
        "manual_only": provider.manual_only,
        "count_only": provider.count_only,
        "deployment_allowed": provider.deployment_allowed,
        "deployment_policy": provider.deployment_policy,
        "policy_message": provider.policy_message,
        "deployment_policy_message": provider.deployment_policy_message,
        "setup_source": provider.setup_file,
        "collector_source": provider.collector_file,
    }
