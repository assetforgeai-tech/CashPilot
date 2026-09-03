"""Provider-runtime truth matrix for the active CashPilot providers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

Mode = Literal["direct", "proxy"]
CollectorKind = Literal["earnings", "dashboard_only", "count_only"]
DeploymentPolicy = Literal["enabled", "platform_restricted", "vps_runtime_prohibited"]

# Keep the compliance decision in the provider truth matrix so the catalog,
# API and UI all expose the same policy without inferring it from a Docker
# image or from historical deployments.
VPS_RUNTIME_BLOCK_REASON = "vps_runtime_prohibited"
VPS_RUNTIME_BLOCK_MESSAGE = (
    "EarnApp generic hosted deployment is disabled. Use the dedicated official Ubuntu x64 LXD runtime."
)
EARNAPP_PLATFORM_BLOCK_REASON = "platform_runtime_disabled"
EARNAPP_PLATFORM_BLOCK_MESSAGE = "EarnApp requires a qualified residential proxy and its dedicated Docker runtime: VN uses MacOS/iOS and non-VN uses Ubuntu."


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
    allowed_platforms: tuple[str, ...] = ()
    blocked_platforms: tuple[str, ...] = ()

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
        slug="earnapp",
        setup_file="earnapp.py",
        collector_file="earnapp.py",
        modes=("proxy",),
        collector_kind="earnings",
        deployment_allowed=True,
        deployment_policy="platform_restricted",
        policy_message=EARNAPP_PLATFORM_BLOCK_MESSAGE,
        allowed_platforms=("macos", "ios", "ubuntu"),
        blocked_platforms=(),
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


def _runtime_platform(spec: object) -> tuple[str, str]:
    if not isinstance(spec, Mapping):
        return "", ""
    platform = str(spec.get("platform") or "").strip().lower()
    backend = str(spec.get("runtime_backend") or "").strip().lower()
    if not platform:
        contract = spec.get("runtime_contract")
        if isinstance(contract, Mapping):
            platform = str(contract.get("platform") or "").strip().lower()
    if platform == "darwin":
        platform = "macos"
    if (
        isinstance(spec, Mapping)
        and str(spec.get("provider_slug") or "").strip().lower() == "earnapp"
        and platform == "linux"
    ):
        platform = "ubuntu"
    return platform, backend


def platform_deployment_allowed(slug: str, platform: str, runtime_backend: str = "") -> bool:
    """Return whether one explicit provider platform/backend is deployable."""
    provider = get(str(slug or "").strip().lower())
    if not provider or not provider.deployment_allowed:
        return False
    if provider.deployment_policy == "enabled":
        return True
    selected = str(platform or "").strip().lower()
    backend = str(runtime_backend or "").strip().lower()
    if selected == "darwin":
        selected = "macos"
    # EarnApp's Ubuntu wire contract identifies the OS as ``linux`` while
    # CashPilot's orchestration policy names that lane ``ubuntu``.
    if provider.slug == "earnapp" and selected == "linux":
        selected = "ubuntu"
    if provider.allowed_platforms and selected not in provider.allowed_platforms:
        return False
    if provider.slug == "earnapp" and selected == "ubuntu":
        return backend == "docker"
    if provider.slug == "earnapp" and selected in {"macos", "ios"}:
        return backend == "docker"
    return bool(selected)


def earnapp_platforms_for_proxy(country_code: str, ip_type: str) -> set[str]:
    """Return platform lanes compatible with one qualified EarnApp proxy."""
    country = str(country_code or "").strip().upper()
    kind = str(ip_type or "").strip().lower().replace("-", "_")
    if kind not in {"residential", "residential_proxy"}:
        return set()
    if country == "VN":
        return {"macos", "ios"}
    if len(country) == 2:
        return {"ubuntu"}
    return set()


def deployment_block(slug: str, spec: object = None) -> ProviderRuntime | None:
    """Block generic deploy routes for restricted provider runtimes.

    Platform-restricted runtimes must use their dedicated endpoint. Otherwise
    caller-controlled metadata could turn the generic Docker route into an
    Ubuntu/LXD bypass without executing the LXD runtime contract.
    """
    route_slug = str(slug or "").strip().lower()
    spec_slug = ""
    if isinstance(spec, Mapping):
        spec_slug = str(spec.get("provider_slug") or "").strip().lower()
    if is_runtime_instance(route_slug, spec_slug):
        policy = get("earnapp")
        if not policy:
            return None
        if policy.deployment_policy == "platform_restricted":
            return policy
        return None if policy.deployment_allowed else policy
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
    if policy and is_runtime_instance(route_slug, spec_slug):
        platform, backend = _runtime_platform(spec)
        if not platform_deployment_allowed("earnapp", platform, backend):
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
        "allowed_platforms": list(provider.allowed_platforms),
        "blocked_platforms": list(provider.blocked_platforms),
        "setup_source": provider.setup_file,
        "collector_source": provider.collector_file,
    }
