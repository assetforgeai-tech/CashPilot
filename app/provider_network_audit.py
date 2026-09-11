"""Read-only checks for provider runtime network drift."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app import provider_runtime


def audit_provider_network_inventory(
    provider: str,
    *,
    instances: Iterable[Mapping[str, Any]],
    containers: Iterable[Mapping[str, Any]],
    inventory_confirmed: bool,
) -> dict[str, Any]:
    """Report proxy-only runtimes that bypass the managed egress sidecar.

    This is intentionally inspection-only. Missing or unconfirmed Docker
    inventory is ``unverified`` rather than evidence of a safe deployment.
    """
    slug = str(provider or "").strip().lower()
    instances = list(instances)
    containers = list(containers)
    runtime = provider_runtime.get(slug)
    if runtime is None or not inventory_confirmed:
        return {"provider": slug, "status": "unverified", "missing_sidecar": [], "untracked": [], "findings": []}
    if runtime.modes != ("proxy",):
        return {"provider": slug, "status": "not_applicable", "missing_sidecar": [], "untracked": [], "findings": []}

    by_id = {
        str(item.get("instance_id") or item.get("instance_slug") or item.get("name") or "").strip(): item
        for item in containers
        if isinstance(item, Mapping)
    }
    if slug == "wipter" and "wipter" in by_id and "wipter-proxy" not in by_id:
        by_id["wipter-proxy"] = by_id["wipter"]
    missing: list[str] = []
    tracked = {str(item.get("instance_id") or "").strip() for item in instances}
    if slug == "wipter" and "wipter-proxy" in tracked:
        tracked.add("wipter")
    untracked = sorted(
        str(item.get("instance_slug") or item.get("name") or "").strip()
        for item in containers
        if str(item.get("instance_slug") or item.get("name") or "").strip() not in tracked
    )
    findings: list[str] = []
    for instance in instances:
        instance_id = str(instance.get("instance_id") or instance.get("logical_node_id") or "").strip()
        if not instance_id or str(instance.get("status") or "").lower() in {"retired", "stopped"}:
            continue
        container = by_id.get(instance_id)
        if not container:
            missing.append(instance_id)
            findings.append(f"{instance_id}: runtime inventory missing; direct egress risk")
            continue
        mode = str(container.get("network_mode") or container.get("NetworkMode") or "").lower()
        sidecar = bool(container.get("sidecar_id") or container.get("sidecar_container_id"))
        if not sidecar and not mode.startswith("container:"):
            missing.append(instance_id)
            findings.append(f"{instance_id}: managed sidecar missing; direct egress risk")
            continue
        if slug == "wipter":
            required = {"NET_ADMIN", "NET_RAW", "DAC_OVERRIDE"}
            actual = {str(cap).upper() for cap in (container.get("cap_add") or [])}
            absent = sorted(required - actual)
            if absent:
                missing.append(instance_id)
                findings.append(f"{instance_id}: required capabilities missing: {', '.join(absent)}")
    for instance_id in untracked:
        live = by_id.get(instance_id)
        if live is None and len(containers) == 1:
            live = containers[0]
        mode = str((live or {}).get("network_mode") or (live or {}).get("NetworkMode") or "").lower()
        suffix = "; direct egress risk" if mode and not mode.startswith("container:") else ""
        findings.append(f"{instance_id}: live runtime is not tracked in CashPilot{suffix}")
    return {
        "provider": slug,
        "status": "attention" if missing or untracked else "pass",
        "missing_sidecar": missing,
        "untracked": untracked,
        "findings": findings,
    }
