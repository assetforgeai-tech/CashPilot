from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PUBLISHER_ASSETS = (
    "scripts/install-nkn-chaindb-publisher.sh",
    "scripts/nkn_chaindb_publisher.py",
    "scripts/cashpilot-nkn-chaindb-publisher.service",
    "scripts/cashpilot-nkn-chaindb-publisher-failure.service",
    "scripts/cashpilot-nkn-chaindb-publisher.timer",
)


def test_ui_publisher_assets_are_not_excluded_from_docker_context():
    """Every file copied by Dockerfile must survive .dockerignore filtering."""
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "scripts/" not in ignore or all(f"!{asset}" in ignore for asset in PUBLISHER_ASSETS), (
        "publisher assets are excluded from the UI build context"
    )


def test_release_runs_when_build_context_or_publisher_assets_change():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "      - '.dockerignore'" in workflow
    assert "      - 'scripts/**'" in workflow


def test_all_publisher_assets_exist_and_are_copied_by_ui_image():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    for asset in PUBLISHER_ASSETS:
        assert (ROOT / asset).is_file(), asset
        assert f"COPY --chown=cashpilot:root {asset}" in dockerfile
