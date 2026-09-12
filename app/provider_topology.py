"""Pure slot-aware provider deployment planning."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app import provider_modes

_SLOT_RE = re.compile(r"^ipv4-(\d{3,6})$")


@dataclass(frozen=True)
class ProviderNodePlan:
    worker_id: int
    provider_slug: str
    mode: str
    slot_id: str
    public_ip: str = ""
    network: str = ""

    @property
    def instance_id(self) -> str:
        return f"{self.provider_slug}-{self.mode}-w{self.worker_id}-{self.slot_id}"


def _normalise_slots(slots: int | list[Any] | tuple[Any, ...]) -> list[tuple[str, str, str]]:
    if isinstance(slots, int):
        if slots < 0:
            raise ValueError("public IPv4 slot count cannot be negative")
        raw: list[Any] = [f"ipv4-{index:03d}" for index in range(1, slots + 1)]
    else:
        raw = list(slots or [])
    result: dict[str, tuple[str, str]] = {}
    for item in raw:
        if isinstance(item, Mapping):
            if item.get("route_ready") is False:
                continue
            slot = str(item.get("slot_id") or "").strip().lower()
            public_ip = str(item.get("public_ip") or "").strip()
            network = str(item.get("docker_network") or "").strip()
        else:
            slot, public_ip, network = str(item or "").strip().lower(), "", ""
        if not _SLOT_RE.fullmatch(slot):
            raise ValueError("invalid public IPv4 slot")
        result.setdefault(slot, (public_ip, network))
    return [
        (slot, values[0], values[1])
        for slot, values in sorted(result.items(), key=lambda pair: int(pair[0].split("-", 1)[1]))
    ]


def plan_provider_nodes(
    worker_id: int,
    provider_slug: str,
    public_ipv4_slots: int | list[Any] | tuple[Any, ...],
    *,
    mode: str | None = None,
) -> list[ProviderNodePlan]:
    """Plan one deterministic node per ready slot and supported mode."""
    if int(worker_id) <= 0:
        raise ValueError("invalid worker id")
    slug = str(provider_slug or "").strip().lower()
    if slug not in provider_modes.BOTH | provider_modes.PROXY_ONLY | provider_modes.DIRECT_ONLY:
        raise ValueError("unknown provider")
    from app import provider_runtime

    runtime = provider_runtime.get(slug)
    if runtime and runtime.topology == "dedicated":
        raise ValueError("provider requires dedicated planner")
    if runtime and runtime.topology == "manual":
        raise ValueError("provider is manual-only")
    modes = provider_modes.expand_requested(slug, mode)
    slots = _normalise_slots(public_ipv4_slots)
    plans: list[ProviderNodePlan] = []
    for slot_id, public_ip, network in slots:
        for selected_mode in modes:
            plans.append(ProviderNodePlan(int(worker_id), slug, selected_mode, slot_id, public_ip, network))
    return plans


def summarize_provider_plan(plans: list[ProviderNodePlan], instances: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Return a read-only convergence summary for a planned provider lane."""
    desired_ids = {plan.instance_id for plan in plans}
    rows = {
        str(row.get("instance_id") or "").strip(): row for row in instances if str(row.get("instance_id") or "").strip()
    }
    running = sorted(
        instance_id
        for instance_id in desired_ids
        if str(rows.get(instance_id, {}).get("status") or "").lower() in {"running", "deployed"}
    )
    retry = sorted(
        instance_id
        for instance_id in desired_ids
        if str(rows.get(instance_id, {}).get("status") or "").lower() in {"failed", "missing", "verification_pending"}
    )
    return {
        "desired": len(desired_ids),
        "running": len(running),
        "retry": retry,
        "missing": sorted(desired_ids - set(rows)),
        "stale": sorted(set(rows) - desired_ids),
    }
