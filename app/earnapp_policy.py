"""Shared safety policy for live EarnApp logical nodes."""

from __future__ import annotations

PROTECTED_LOGICAL_NODE_IDS = frozenset(
    {
        "earnapp-canary-test-sing-1",
        "earnapp-recovery-test-sing-2",
        "earnapp-ios-canary-test-sing-3",
        "earnapp-ubuntu-canary-test-sing-4",
        "earnapp-ubuntu-canary-test-sing-5",
    }
)


def protected_runtime_references() -> frozenset[str]:
    """Return exact logical, Docker, sidecar, and LXD names for protected nodes."""
    references: set[str] = set()
    for node_id in PROTECTED_LOGICAL_NODE_IDS:
        references.update(
            {
                node_id,
                f"cashpilot-{node_id}",
                f"cashpilot-{node_id}-egress",
                f"cashpilot-earnapp-{node_id}",
            }
        )
    return frozenset(references)


def is_protected_logical_node(logical_node_id: object) -> bool:
    """Return whether a live EarnApp node is inspection-only."""
    return str(logical_node_id or "").strip() in PROTECTED_LOGICAL_NODE_IDS


def is_protected_runtime_reference(value: object) -> bool:
    """Recognize only the deterministic runtime aliases of protected nodes."""
    return str(value or "").strip() in protected_runtime_references()
