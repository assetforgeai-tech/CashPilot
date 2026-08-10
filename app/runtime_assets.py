"""Runtime asset key helpers."""

from __future__ import annotations

import re

ALLOWED_KINDS = {"seed_bundle", "cookie_bundle", "dashboard_token", "wallet_lease_ref"}
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

def validate(provider: str, asset_kind: str) -> tuple[str, str]:
    provider = provider.strip().lower()
    asset_kind = asset_kind.strip().lower()
    if not _SLUG_RE.match(provider):
        raise ValueError("invalid provider")
    if asset_kind not in ALLOWED_KINDS:
        raise ValueError("invalid asset kind")
    return provider, asset_kind

def config_key(provider: str, asset_kind: str) -> str:
    provider, asset_kind = validate(provider, asset_kind)
    return f"runtime_asset::{provider}::{asset_kind}::secret"

def parse_config_key(key: str) -> tuple[str, str] | None:
    parts = key.split("::")
    if len(parts) != 4 or parts[0] != "runtime_asset" or parts[3] != "secret":
        return None
    try:
        return validate(parts[1], parts[2])
    except ValueError:
        return None
