"""Declarative inventory of resources owned by a worker generation.

This module is intentionally database-free.  Reclamation code consumes the
contract later, while this registry makes omissions fail during review/tests.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class ResourceDisposition(StrEnum):
    RELEASE = "release"
    RETIRE = "retire"


@dataclass(frozen=True)
class ResourceAuthority:
    table: str
    disposition: ResourceDisposition
    release_action: str
    release_reason: str
    post_release_state: str
    preserve: tuple[str, ...] = ()


REQUIRED_RESOURCE_FAMILIES = (
    "proxy_leases",
    "nkn_wallets",
    "myst_wallets",
    "provider_runtime_assignments",
    "capacity_reservations",
    "direct_only",
)


_REGISTRY: dict[str, ResourceAuthority] = {
    "proxy_leases": ResourceAuthority(
        table="provider_proxy_leases",
        disposition=ResourceDisposition.RELEASE,
        release_action="release_proxy_lease",
        release_reason="worker_lost",
        post_release_state="released; available for a new worker generation",
        preserve=("proxy_identity", "sticky_egress_ownership", "proxy_health"),
    ),
    "nkn_wallets": ResourceAuthority(
        table="nkn_wallets",
        disposition=ResourceDisposition.RELEASE,
        release_action="release_nkn_wallet_lease",
        release_reason="worker_lost",
        post_release_state="available; wallet identity remains intact",
        preserve=("wallet_identity", "credential", "history"),
    ),
    "myst_wallets": ResourceAuthority(
        table="myst_wallets",
        disposition=ResourceDisposition.RELEASE,
        release_action="release_myst_wallet_lease",
        release_reason="worker_lost",
        post_release_state="available; wallet identity remains intact",
        preserve=("wallet_identity", "credential", "history"),
    ),
    "provider_runtime_assignments": ResourceAuthority(
        table="provider_instances",
        disposition=ResourceDisposition.RETIRE,
        release_action="retire_runtime_assignment",
        release_reason="worker_lost",
        post_release_state="retired; reacquisition required for a new generation",
        preserve=("provider_identity", "earnings", "audit_history"),
    ),
    "capacity_reservations": ResourceAuthority(
        table="provider_proxy_leases.capacity_slot",
        disposition=ResourceDisposition.RELEASE,
        release_action="release_capacity_reservation",
        release_reason="worker_lost",
        post_release_state="capacity returned to provider pool",
        preserve=("provider_identity", "capacity_history"),
    ),
    "direct_only": ResourceAuthority(
        table="provider_instances",
        disposition=ResourceDisposition.RETIRE,
        release_action="retire_runtime_assignment",
        release_reason="worker_lost",
        post_release_state="retired; no proxy lease exists",
        preserve=("provider_identity", "earnings", "audit_history"),
    ),
}


def get_worker_resource_registry() -> dict[str, ResourceAuthority]:
    """Return a copy so callers cannot mutate the contract globally."""
    return dict(_REGISTRY)


def validate_registry(registry: Mapping[str, ResourceAuthority]) -> None:
    """Raise when a worker-bound authority is missing or underspecified."""
    missing = set(REQUIRED_RESOURCE_FAMILIES) - set(registry)
    if missing:
        raise ValueError(f"missing worker resource families: {', '.join(sorted(missing))}")
    for family in REQUIRED_RESOURCE_FAMILIES:
        authority = registry[family]
        if not authority.table or not authority.release_action:
            raise ValueError(f"incomplete worker resource authority: {family}")
        if authority.release_reason != "worker_lost":
            raise ValueError(f"invalid release reason for {family}")
        if not authority.post_release_state:
            raise ValueError(f"missing post-release state for {family}")


validate_registry(_REGISTRY)
