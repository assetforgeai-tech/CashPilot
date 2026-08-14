from __future__ import annotations

from app import provider_runtime

BOTH = {slug for slug, runtime in provider_runtime.PROVIDERS.items() if set(runtime.modes) == {"direct", "proxy"}}
PROXY_ONLY = {slug for slug, runtime in provider_runtime.PROVIDERS.items() if runtime.modes == ("proxy",)}
DIRECT_ONLY = {slug for slug, runtime in provider_runtime.PROVIDERS.items() if runtime.modes == ("direct",)}


def supported_modes(slug: str) -> set[str]:
    return provider_runtime.supported_modes(slug)


def default_deploy_mode(slug: str) -> str:
    return provider_runtime.default_mode(slug)

def expand_requested(slug: str, mode: str | None) -> list[str]:
    if not mode:
        mode = default_deploy_mode(slug)
    if mode == "legacy":
        return ["legacy"]
    wanted = ["direct", "proxy"] if mode == "both" else [mode]
    supported = supported_modes(slug)
    blocked = [item for item in wanted if item not in supported]
    if blocked:
        raise ValueError(f"{slug} does not support {', '.join(blocked)} mode")
    return wanted
