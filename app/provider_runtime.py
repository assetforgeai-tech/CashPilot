"""Provider-runtime truth matrix for the active CashPilot providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Mode = Literal["direct", "proxy"]
CollectorKind = Literal["earnings", "dashboard_only", "count_only"]


@dataclass(frozen=True)
class ProviderRuntime:
    slug: str
    setup_file: str
    collector_file: str
    modes: tuple[Mode, ...]
    collector_kind: CollectorKind

    @property
    def default_mode(self) -> str:
        return "both" if set(self.modes) == {"direct", "proxy"} else self.modes[0]

    @property
    def count_only(self) -> bool:
        return self.collector_kind == "count_only"

    @property
    def manual_only(self) -> bool:
        return self.collector_kind != "earnings"


PROVIDERS: dict[str, ProviderRuntime] = {
    "bitping": ProviderRuntime("bitping", "bitping.py", "bitping.py", ("direct", "proxy"), "earnings"),
    "earnapp": ProviderRuntime("earnapp", "earnapp.py", "", ("proxy",), "earnings"),
    "earnfm": ProviderRuntime("earnfm", "earn.fm.py", "earn.fm.py", ("direct", "proxy"), "earnings"),
    "grass": ProviderRuntime("grass", "Grass.py", "Grass.py", ("proxy",), "earnings"),
    "iproyal": ProviderRuntime("iproyal", "pawns.py", "pawns.py", ("proxy",), "earnings"),
    "mysterium": ProviderRuntime("mysterium", "MYST.py", "MYST.py", ("direct", "proxy"), "earnings"),
    "packetstream": ProviderRuntime("packetstream", "packetstream.py", "packetstream.py", ("proxy",), "earnings"),
    "proxies-sx": ProviderRuntime("proxies-sx", "proxies.sx.py", "proxies.sx.py", ("proxy",), "earnings"),
    "proxybase": ProviderRuntime("proxybase", "proxybase.org.py", "proxybase.org.py", ("direct", "proxy"), "dashboard_only"),
    "proxybase-xyz": ProviderRuntime("proxybase-xyz", "proxybase.xyz.py", "proxybase.xyz.py", ("direct", "proxy"), "count_only"),
    "proxylite": ProviderRuntime("proxylite", "lk.proxylite.ru.py", "lk.proxylite.ru.py", ("direct",), "count_only"),
    "proxyrack": ProviderRuntime("proxyrack", "proxyrack.org.py", "proxyrack.org.py", ("direct", "proxy"), "earnings"),
    "repocket": ProviderRuntime("repocket", "repocket.py", "repocket.py", ("direct", "proxy"), "earnings"),
    "spide": ProviderRuntime("spide", "spide.py", "spide.py", ("direct", "proxy"), "dashboard_only"),
    "traffmonetizer": ProviderRuntime("traffmonetizer", "traffmonetizer.py", "traffmonetizer.py", ("direct", "proxy"), "earnings"),
    "uprock": ProviderRuntime("uprock", "Uprock.py", "Uprock.py", ("proxy",), "count_only"),
    "urnetwork": ProviderRuntime("urnetwork", "URNetwork.py", "URNetwork.py", ("direct", "proxy"), "dashboard_only"),
    "wipter": ProviderRuntime("wipter", "Wipter.py", "Wipter.py", ("proxy",), "count_only"),
}

ACTIVE_SLUGS = frozenset(PROVIDERS)


def get(slug: str) -> ProviderRuntime | None:
    return PROVIDERS.get(slug)


def supported_modes(slug: str) -> set[str]:
    provider = get(slug)
    return set(provider.modes) if provider else {"direct"}


def default_mode(slug: str) -> str:
    provider = get(slug)
    return provider.default_mode if provider else "direct"


def catalog_runtime(slug: str) -> dict[str, object]:
    provider = get(slug)
    if not provider:
        return {}
    return {
        "modes": list(provider.modes),
        "default_mode": provider.default_mode,
        "collector_kind": provider.collector_kind,
        "manual_only": provider.manual_only,
        "count_only": provider.count_only,
        "setup_source": provider.setup_file,
        "collector_source": provider.collector_file,
    }
