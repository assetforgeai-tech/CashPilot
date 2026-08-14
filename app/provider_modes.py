from __future__ import annotations

BOTH = {
    "bitping",
    "grass",
    "proxylite",
    "proxybase",
    "proxybase-xyz",
    "proxyrack",
    "repocket",
    "spide",
    "traffmonetizer",
    "uprock",
    "urnetwork",
}
PROXY_ONLY = {"earnapp", "earnfm", "iproyal", "packetstream", "proxies-sx", "wipter"}
DIRECT_ONLY = {"mysterium"}


def supported_modes(slug: str) -> set[str]:
    if slug in BOTH:
        return {"direct", "proxy"}
    if slug in PROXY_ONLY:
        return {"proxy"}
    if slug in DIRECT_ONLY:
        return {"direct"}
    return {"direct"}


def expand_requested(slug: str, mode: str | None) -> list[str]:
    if not mode:
        return ["legacy"]
    wanted = ["direct", "proxy"] if mode == "both" else [mode]
    supported = supported_modes(slug)
    blocked = [item for item in wanted if item not in supported]
    if blocked:
        raise ValueError(f"{slug} does not support {', '.join(blocked)} mode")
    return wanted
