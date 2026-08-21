"""Explicitly retired provider slugs kept for legacy-data boundaries."""

from __future__ import annotations

from typing import Any

RETIRED_PROVIDER_SLUGS = frozenset({"grass"})


def is_retired_provider(slug: Any) -> bool:
    return str(slug or "").strip().lower() in RETIRED_PROVIDER_SLUGS
