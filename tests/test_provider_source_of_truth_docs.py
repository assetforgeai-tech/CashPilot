from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_current_operator_docs_use_current_catalog_counts():
    docs = [
        ROOT / "docs" / "getting-started.md",
        ROOT / "docs" / "index.md",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in docs)
    assert "49 services" not in text
    assert "13 collectors" not in text
    assert "20 providers" in text
    assert "12 collectors" in text


def test_readme_has_only_live_catalog_categories():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "### GPU Compute" not in text
    assert "storage/      # Storage sharing services" not in text
    assert "compute/      # GPU compute services" not in text
