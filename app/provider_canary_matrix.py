"""Pure provider canary acceptance matrix.

Evaluates supplied evidence only; live execution belongs to CP-011.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app import provider_runtime


@dataclass(frozen=True)
class CanaryResult:
    provider: str
    group: str
    status: str
    required: tuple[str, ...]
    missing: tuple[str, ...]
    findings: tuple[str, ...]
    rollback: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "group": self.group,
            "status": self.status,
            "required": list(self.required),
            "missing": list(self.missing),
            "findings": list(self.findings),
            "rollback": self.rollback,
        }


@dataclass(frozen=True)
class GroupResult:
    group: str
    status: str
    members: tuple[CanaryResult, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"group": self.group, "status": self.status, "members": [item.as_dict() for item in self.members]}


def _required_signals(spec: provider_runtime.ProviderRuntime) -> tuple[str, ...]:
    required = ["egress_ok", "dns_ok", "ipv6_ok", "direct_fallback_blocked"]
    if "proxy" in spec.modes:
        required.append("udp_ok")
        if spec.proxy_transport != "direct_only":
            required.append("watchdog_ok")
    required.append("reboot_persistence_ok")
    return tuple(required)


def evaluate_provider_canary(
    provider: str,
    *,
    evidence: Mapping[str, Any],
    rollback_plan: str = "",
) -> CanaryResult:
    slug = str(provider or "").strip().lower()
    spec = provider_runtime.get(slug)
    group = spec.policy_group if spec else "unknown"
    if spec is None:
        return CanaryResult(slug, group, "INCONCLUSIVE", (), (), ("unknown_provider",), str(rollback_plan).strip())
    required = _required_signals(spec)
    missing = tuple(signal for signal in required if signal not in evidence or evidence[signal] is None)
    findings = tuple(signal for signal in required if signal in evidence and evidence[signal] is False)
    rollback = str(rollback_plan or evidence.get("rollback_plan") or "").strip()
    if not rollback:
        missing = (*missing, "rollback_plan")
    status = "FAIL" if findings else "INCONCLUSIVE" if missing else "PASS"
    return CanaryResult(slug, group, status, required, missing, findings, rollback)


def evaluate_provider_groups(evidence_by_provider: Mapping[str, Mapping[str, Any]]) -> dict[str, GroupResult]:
    grouped: dict[str, list[CanaryResult]] = defaultdict(list)
    for provider, evidence in evidence_by_provider.items():
        result = evaluate_provider_canary(provider, evidence=evidence)
        grouped[result.group].append(result)
    output: dict[str, GroupResult] = {}
    for group, members in grouped.items():
        ordered = tuple(sorted(members, key=lambda item: item.provider))
        status = (
            "FAIL"
            if any(item.status == "FAIL" for item in ordered)
            else "INCONCLUSIVE"
            if any(item.status == "INCONCLUSIVE" for item in ordered)
            else "PASS"
        )
        output[group] = GroupResult(group, status, ordered)
    return output
