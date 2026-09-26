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
