from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app import catalog, provider_runtime
from app.collectors import COLLECTOR_MAP
from scripts import sync_docs_nav

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


def test_active_context_marks_earnapp_provider_block_as_historical():
    text = (ROOT / "docs" / "ACTIVE_CONTEXT.md").read_text(encoding="utf-8")

    assert "## Current source policy (unreleased, 2026-08-29)" in text
    assert "**Historical v1.14.1 status:** `COMPLIANCE_BLOCKED` / `RUNTIME_DISABLED`" in text
    assert "- **Status:** `COMPLIANCE_BLOCKED` / `RUNTIME_DISABLED`" not in text


def test_generated_service_index_derives_runtime_disabled_from_provider_truth_matrix(monkeypatch):
    providers = dict(provider_runtime.PROVIDERS)
    providers["earnfm"] = replace(
        providers["earnfm"],
        deployment_allowed=False,
        deployment_policy="vps_runtime_prohibited",
    )
    monkeypatch.setattr(provider_runtime, "PROVIDERS", providers)

    disabled_slugs = sync_docs_nav.runtime_disabled_slugs()

    assert disabled_slugs == frozenset({"earnfm"})


def test_generated_service_index_removes_earnapp_policy_notice_when_runtime_is_reenabled(monkeypatch):
    providers = dict(provider_runtime.PROVIDERS)
    providers["earnapp"] = replace(
        providers["earnapp"],
        deployment_allowed=True,
        deployment_policy="enabled",
        policy_message="",
    )
    monkeypatch.setattr(provider_runtime, "PROVIDERS", providers)

    rendered = sync_docs_nav.render_index(
        [
            {
                "slug": "earnapp",
                "name": "EarnApp",
                "category": "bandwidth",
                "status": "active",
                "requirements": {},
                "payment": {},
                "dockerised": True,
            }
        ]
    )

    assert "Hosted Docker/LXD deployment is currently disabled" not in rendered
    assert "| [EarnApp](earnapp.md) | — | Docker | — | active |" in rendered


def test_generated_service_index_describes_current_earnapp_docker_platform_matrix():
    rendered = sync_docs_nav.render_index(
        [
            {
                "slug": "earnapp",
                "name": "EarnApp",
                "category": "bandwidth",
                "status": "active",
                "requirements": {"residential_ip": True},
                "payment": {"minimum_payout": "$2"},
                "dockerised": True,
            }
        ]
    )

    assert "MacOS/iOS for VN residential proxies" in rendered
    assert "Ubuntu Docker for non-VN residential proxies" in rendered
    assert "| [EarnApp](earnapp.md) | Residential IP | Docker | $2 | platform restricted |" in rendered
    assert "Ubuntu LXD" not in rendered
