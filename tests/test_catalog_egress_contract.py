from pathlib import Path

import yaml

from app import provider_runtime


def _service_file(slug: str) -> Path:
    matches = list(Path("services").rglob(f"{slug}.yml"))
    assert matches, slug
    return matches[0]


def test_every_runtime_provider_declares_explicit_egress_contract():
    missing = []
    for slug in provider_runtime.PROVIDERS:
        data = yaml.safe_load(_service_file(slug).read_text(encoding="utf-8")) or {}
        egress = data.get("egress") or {}
        if not all(egress.get(key) for key in ("mode", "udp", "fallback", "reason")) or egress["fallback"] != "none":
            missing.append(slug)
    assert not missing, f"providers missing explicit egress contract: {missing}"
