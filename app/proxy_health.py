"""Shared proxy-health grouping; node health remains per lease."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable, Mapping
from typing import Any


def probe_key(lease: Mapping[str, Any]) -> tuple[str, ...]:
    egress = str(lease.get("exit_ip") or "").strip()
    if egress:
        return ("egress", egress)
    return (
        "endpoint",
        str(lease.get("host") or "").strip().lower(),
        str(lease.get("port") or "").strip(),
        str(lease.get("protocol") or "").strip().lower(),
    )


def build_probe_groups(leases: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: OrderedDict[tuple[str, ...], dict[str, Any]] = OrderedDict()
    for lease in leases:
        if str(lease.get("lane") or "proxy").strip().lower() == "direct":
            continue
        instance_id = str(lease.get("instance_id") or "").strip()
        if not instance_id:
            continue
        group = groups.setdefault(probe_key(lease), {"key": probe_key(lease), "instance_ids": []})
        group["instance_ids"].append(instance_id)
    return list(groups.values())


def fanout_probe_result(group: Mapping[str, Any], result: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "instance_id": instance_id,
            "status": str(result.get("status") or "unknown"),
            "reason": str(result.get("reason") or ""),
        }
        for instance_id in group.get("instance_ids", [])
    ]
