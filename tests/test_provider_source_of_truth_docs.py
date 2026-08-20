from __future__ import annotations

from pathlib import Path

from app import catalog
from app.collectors import COLLECTOR_MAP

ROOT = Path(__file__).resolve().parents[1]


def test_current_operator_docs_use_current_catalog_counts():
    docs = [
        ROOT / "docs" / "getting-started.md",
        ROOT / "docs" / "index.md",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in docs)
    services = catalog.get_services()
    provider_count = len(services)
    bandwidth_count = sum(1 for svc in services if svc["category"] == "bandwidth")
    depin_count = sum(1 for svc in services if svc["category"] == "depin")
    collector_count = len(COLLECTOR_MAP)

    assert "49 services" not in text
    assert "20 providers" not in text
    assert "15 collectors" not in text
    assert f"{provider_count} providers" in text
    assert f"Bandwidth Sharing** ({bandwidth_count} providers)" in text
    assert f"DePIN** ({depin_count} providers)" in text
    assert f"{collector_count} collectors" in text


def test_readme_has_only_live_catalog_categories():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "### GPU Compute" not in text
    assert "storage/      # Storage sharing services" not in text
    assert "compute/      # GPU compute services" not in text
