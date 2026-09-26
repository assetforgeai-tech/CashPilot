"""Explicit, redacted CP-013 fatal-safety signals."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

FATAL_CODES = (
    "identity_mismatch",
    "wrong_wallet",
    "wrong_lease",
    "direct_fallback",
    "egress_mismatch",
    "route_failure",
    "dns_failure",
)


class RolloutSafetyViolation(Exception):
    def __init__(self, code: str):
        if code not in FATAL_CODES:
            raise ValueError("unknown rollout safety violation")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RolloutSafetyAssessment:
    stop_round: bool
    code: str


def enrich_rollout_result(
    result: Mapping[str, Any] | None,
    *,
    instances: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    probes: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
) -> dict[str, Any]:
    """Attach redacted probe/lease safety signals to one provider result."""
    enriched = dict(result or {})
    safety: dict[str, bool] = {}
    rows = {
        str(row.get("instance_id") or "").strip(): row
        for row in instances
        if isinstance(row, Mapping) and str(row.get("instance_id") or "").strip()
    }
    probe_rows = {
        str(row.get("instance_id") or "").strip(): row
        for row in probes
        if isinstance(row, Mapping) and str(row.get("instance_id") or "").strip()
    }
    deployed = enriched.get("instances")
    running_ids = (
        {
            str(row.get("instance_id") or "").strip()
            for row in deployed
            if isinstance(row, Mapping)
            and str(row.get("instance_id") or "").strip()
            and str(row.get("status") or "").strip().lower() in {"running", "deployed", "started"}
        }
        if isinstance(deployed, list)
        else set()
    )
    successful = 0
    missing_probes = 0
    missing_instances = 0
    missing_expected_egress = 0
    for instance_id in sorted(running_ids):
        instance = rows.get(instance_id)
        if instance is None:
            missing_instances += 1
            continue
        probe = probe_rows.get(instance_id)
        if probe is None:
            missing_probes += 1
            continue
        if probe.get("probe_ok") is not True:
            safety["route_failure"] = True
            continue
        successful += 1
        mode = str(instance.get("mode") or instance.get("egress_mode") or "").strip().lower()
        expected = str(instance.get("expected_egress_ip") or "").strip()
        observed = str(probe.get("observed_egress_ip") or "").strip()
        if mode == "proxy" and not str(instance.get("proxy_lease_id") or "").strip():
            safety["wrong_lease"] = True
        proxy_id = str(instance.get("proxy_id") or "").strip()
        lease_proxy_id = str(instance.get("proxy_lease_proxy_id") or "").strip()
        if mode == "proxy" and proxy_id and lease_proxy_id and proxy_id != lease_proxy_id:
            safety["wrong_lease"] = True
        if not expected:
            missing_expected_egress += 1
            continue
        if expected and observed != expected:
            safety["egress_mismatch"] = True
        if not observed:
            safety["egress_mismatch"] = True
    enriched["safety"] = safety
    enriched["safety_evidence"] = {
        "probes": len(probe_rows),
        "successful_probes": successful,
        "missing_probes": missing_probes,
        "missing_instances": missing_instances,
        "missing_expected_egress": missing_expected_egress,
    }
    if (
        (missing_probes or missing_instances or missing_expected_egress)
        and not safety
        and str(enriched.get("status") or "").strip().lower() not in {"failed", "error", "slot_conflict"}
        and not enriched.get("failed")
    ):
        enriched["status"] = "verification_pending"
    return enriched


def classify_rollout_result(result: Mapping[str, Any] | None) -> RolloutSafetyAssessment:
    safety = result.get("safety") if isinstance(result, Mapping) else None
    if not isinstance(safety, Mapping):
        return RolloutSafetyAssessment(False, "ordinary_failure")
    for code in FATAL_CODES:
        if safety.get(code) is True:
            return RolloutSafetyAssessment(True, code)
    # ponytail: unknown positive safety signals stop; add an adapter only when
    # its provider response contract is verified.
    if any(value is True for value in safety.values()):
        return RolloutSafetyAssessment(True, "unclassified_safety")
    return RolloutSafetyAssessment(False, "ordinary_failure")


def classify_rollout_exception(error: BaseException) -> RolloutSafetyAssessment:
    if isinstance(error, RolloutSafetyViolation):
        return RolloutSafetyAssessment(True, error.code)
    return RolloutSafetyAssessment(False, "ordinary_failure")
