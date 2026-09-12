"""Pure slot-aware provider deployment planning."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from app import provider_modes

_SLOT_RE = re.compile(r"^ipv4-(\d{3,6})$")


def topology_contract(provider_slug: str) -> dict[str, Any]:
    """Return the explicit egress contract used by planning and UI code."""
    from app import provider_runtime

    runtime = provider_runtime.get(str(provider_slug or "").strip().lower())
    if runtime is None:
        raise ValueError("unknown provider")
    topology = runtime.topology
    modes = set(runtime.modes)
    lanes = [mode for mode in ("direct", "proxy") if mode in modes]
    return {
        "topology": topology,
        "lanes": lanes,
        "capacity_basis": {
            lane: (
                "dedicated_runtime"
                if runtime.topology in {"dedicated", "manual"}
                else "public_ipv4_slot"
                if lane == "direct"
                else "eligible_proxy"
            )
            for lane in lanes
        },
        "lane_isolation": len(lanes) > 1,
        "direct_required": "direct" in lanes,
        "proxy_required": "proxy" in lanes,
        "direct_fallback": False,
        "proxy_fallback": False,
    }


def build_capacity_preflight(
    *,
    slots: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    system_info: Mapping[str, Any] | None = None,
    ports: list[str] | tuple[str, ...] = (),
    available_proxy_count: int | None = None,
) -> dict[str, Any]:
    """Normalize worker capacity facts for a read-only deployment preflight."""
    info = system_info if isinstance(system_info, Mapping) else {}
    resources = info.get("resources") if isinstance(info.get("resources"), Mapping) else {}
    memory = resources.get("memory") if isinstance(resources.get("memory"), Mapping) else {}
    disk = info.get("disk") if isinstance(info.get("disk"), Mapping) else {}
    return {
        "cpu_cores": resources.get("cpu_cores"),
        "memory_total_bytes": memory.get("total_bytes"),
        "disk_free_bytes": disk.get("free_bytes"),
        "ports": [str(port).split(":", 1)[-1] for port in ports],
        "public_ipv4_slots": len(slots),
        "ready_public_ipv4_slots": sum(1 for slot in slots if slot.get("route_ready") is True),
        "proxy_capacity": None if available_proxy_count is None else max(0, int(available_proxy_count)),
    }


@dataclass(frozen=True)
class ProviderNodePlan:
    worker_id: int
    provider_slug: str
    mode: str
    slot_id: str
    # ``lane`` is explicit in API payloads; keep it equal to mode for now so
    # callers can evolve lane-specific policy without inferring from IDs.
    lane: str = ""
    topology: str = ""
    public_ip: str = ""
    network: str = ""
    route_ready: bool = True
    capacity_slot: str = ""
    deployable: bool = True
    blocked_reason: str = ""

    @property
    def instance_id(self) -> str:
        return f"{self.provider_slug}-{self.mode}-w{self.worker_id}-{self.slot_id}"


def _normalise_slots(slots: int | list[Any] | tuple[Any, ...]) -> list[tuple[str, str, str, bool]]:
    if isinstance(slots, int):
        if slots < 0:
            raise ValueError("public IPv4 slot count cannot be negative")
        raw: list[Any] = [f"ipv4-{index:03d}" for index in range(1, slots + 1)]
    else:
        raw = list(slots or [])
    result: dict[str, tuple[str, str, bool]] = {}
    for item in raw:
        if isinstance(item, Mapping):
            slot = str(item.get("slot_id") or "").strip().lower()
            public_ip = str(item.get("public_ip") or "").strip()
            network = str(item.get("docker_network") or "").strip()
            route_ready = item.get("route_ready") is True
        else:
            slot, public_ip, network, route_ready = str(item or "").strip().lower(), "", "", True
        if not _SLOT_RE.fullmatch(slot):
            raise ValueError("invalid public IPv4 slot")
        result.setdefault(slot, (public_ip, network, route_ready))
    return [
        (slot, values[0], values[1], values[2])
        for slot, values in sorted(result.items(), key=lambda pair: int(pair[0].split("-", 1)[1]))
    ]


def plan_provider_nodes(
    worker_id: int,
    provider_slug: str,
    public_ipv4_slots: int | list[Any] | tuple[Any, ...],
    *,
    mode: str | None = None,
    proxy_capacity: int | None = None,
    direct_desired: int | None = None,
    proxy_desired: int | None = None,
) -> list[ProviderNodePlan]:
    """Plan independent lanes, optionally against explicit lane targets."""
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
    for target in (direct_desired, proxy_desired):
        if target is not None and int(target) < 0:
            raise ValueError("lane desired count cannot be negative")
    if direct_desired is not None and "direct" not in modes:
        raise ValueError("unsupported lane target: direct")
    if proxy_desired is not None and "proxy" not in modes:
        raise ValueError("unsupported lane target: proxy")
    slots = _normalise_slots(public_ipv4_slots)
    plans: list[ProviderNodePlan] = []
    # Proxy capacity is an independent discovery result. Unknown capacity must
    # stay pending; inferring it from public IPv4 slots creates unsafe proxy
    # nodes before the pool has been checked.
    direct_target = direct_desired if direct_desired is not None else len(slots)
    direct_slots = slots[:direct_target] if "direct" in modes else []
    if "direct" in modes and direct_target > len(slots):
        direct_slots.extend((f"ipv4-{index:03d}", "", "", False) for index in range(len(slots) + 1, direct_target + 1))
    # Bootstrap public-IP count is the default node cardinality for every
    # proxy lane. Capacity remains a gate; it must not silently expand the
    # requested topology. Workers without slot discovery retain the legacy
    # proxy-capacity fallback until bootstrap enrollment is available.
    proxy_target = (
        proxy_desired
        if proxy_desired is not None
        else len(slots)
        if slots
        else (max(0, int(proxy_capacity)) if proxy_capacity is not None else 0)
    )
    proxy_slots = (
        [
            (f"proxy-{index:03d}", "", "", index <= max(0, int(proxy_capacity or 0)))
            for index in range(1, proxy_target + 1)
        ]
        if "proxy" in modes
        else []
    )
    direct_plans: list[ProviderNodePlan] = []
    proxy_plans: list[ProviderNodePlan] = []
    for slot_id, public_ip, network, route_ready in direct_slots:
        deployable = route_ready
        direct_plans.append(
            ProviderNodePlan(
                int(worker_id),
                slug,
                "direct",
                slot_id,
                "direct",
                runtime.topology if runtime else "",
                public_ip,
                network,
                route_ready,
                slot_id,
                deployable,
                "direct_route_not_ready" if not deployable else "",
            )
        )
    for proxy_index, (slot_id, public_ip, network, route_ready) in enumerate(proxy_slots, 1):
        proxy_plans.append(
            ProviderNodePlan(
                int(worker_id),
                slug,
                "proxy",
                slot_id,
                "proxy",
                runtime.topology if runtime else "",
                public_ip,
                network,
                route_ready,
                f"proxy-{proxy_index:03d}",
                route_ready,
                "" if route_ready else "proxy_capacity_unavailable",
            )
        )
    plans.extend(direct_plans)
    plans.extend(proxy_plans)
    return plans


def summarize_provider_plan(
    plans: list[ProviderNodePlan],
    instances: list[Mapping[str, Any]],
    *,
    available_proxy_count: int | None = None,
    existing_proxy_count: int = 0,
) -> dict[str, Any]:
    """Return a read-only convergence summary for a planned provider lane."""
    desired_ids = {plan.instance_id for plan in plans}
    rows = {
        str(row.get("instance_id") or "").strip(): row for row in instances if str(row.get("instance_id") or "").strip()
    }
    effective_plans = list(plans)
    if available_proxy_count is not None:
        proxy_seen = 0
        effective_plans = []
        for plan in plans:
            deployable = plan.deployable
            if plan.mode == "proxy":
                deployable = deployable and proxy_seen < max(0, int(available_proxy_count))
                proxy_seen += 1
            effective_plans.append(plan if deployable == plan.deployable else replace(plan, deployable=deployable))
    deployable_ids = {plan.instance_id for plan in effective_plans if plan.deployable}
    lanes = {
        mode: {
            "desired": sum(1 for plan in effective_plans if plan.mode == mode),
            "deployable": sum(1 for plan in effective_plans if plan.mode == mode and plan.deployable),
            "running": sum(
                1
                for plan in effective_plans
                if plan.mode == mode
                and plan.deployable
                and str(rows.get(plan.instance_id, {}).get("status") or "").lower() in {"running", "deployed"}
            ),
        }
        for mode in ("direct", "proxy")
        if any(plan.mode == mode for plan in plans)
    }
    lane_capacity = {}
    for mode in ("direct", "proxy"):
        lane_plans = [plan for plan in effective_plans if plan.mode == mode]
        if not lane_plans:
            continue
        deployable_count = sum(1 for plan in lane_plans if plan.deployable)
        running_count = sum(
            1
            for plan in lane_plans
            if plan.deployable
            and str(rows.get(plan.instance_id, {}).get("status") or "").lower() in {"running", "deployed"}
        )
        lane_capacity[mode] = {
            "desired": len(lane_plans),
            "deployable": deployable_count,
            "running": running_count,
            "free": max(0, deployable_count - running_count),
            "blocked": len(lane_plans) - deployable_count,
        }
    direct_capacity = lane_capacity.get("direct", {}).get("deployable", 0)
    proxy_capacity = (
        max(0, int(available_proxy_count))
        if available_proxy_count is not None and any(plan.mode == "proxy" for plan in plans)
        else None
    )
    running = sorted(
        instance_id
        for instance_id in deployable_ids
        if str(rows.get(instance_id, {}).get("status") or "").lower() in {"running", "deployed"}
    )
    retry = sorted(
        instance_id
        for instance_id in deployable_ids
        if str(rows.get(instance_id, {}).get("status") or "").lower() in {"failed", "missing", "verification_pending"}
    )
    return {
        "desired": len(desired_ids),
        # ``desired`` is the topology target; ``capacity_target`` is the number
        # currently satisfiable without unsafe fallback. Keeping both prevents
        # proxy shortage from silently shrinking the operator's target.
        "capacity_target": (
            min(len(desired_ids), max(0, int(available_proxy_count)) + max(0, int(existing_proxy_count)))
            if available_proxy_count is not None and all(plan.mode == "proxy" for plan in plans)
            else len(desired_ids)
        ),
        "deployable": len(deployable_ids),
        "pending_capacity": sum(1 for plan in effective_plans if not plan.deployable),
        "lanes": lanes,
        "lane_capacity": lane_capacity,
        "direct_capacity": direct_capacity if any(plan.mode == "direct" for plan in plans) else None,
        "proxy_capacity": proxy_capacity,
        "running": len(running),
        "retry": retry,
        "missing": sorted(deployable_ids - set(rows)),
        "stale": sorted(set(rows) - desired_ids),
        "pending_proxy": sum(1 for plan in effective_plans if plan.mode == "proxy" and not plan.deployable),
        "blocked_slots": sorted({plan.slot_id for plan in plans if not plan.deployable}),
        "blocked": sum(1 for plan in plans if not plan.deployable),
        "proxy_capacity_shortfall": (
            max(
                0,
                sum(1 for plan in plans if plan.mode == "proxy") - max(0, int(available_proxy_count)),
            )
            if available_proxy_count is not None and any(plan.mode == "proxy" for plan in plans)
            else 0
        ),
    }
