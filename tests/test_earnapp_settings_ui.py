from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "app" / "templates" / "settings.html"
APP_JS = ROOT / "app" / "static" / "js" / "app.js"
FLEET = ROOT / "app" / "templates" / "fleet.html"


def test_settings_prioritizes_token_and_proxy_route_health_without_secret_fields():
    template = SETTINGS.read_text(encoding="utf-8")
    javascript = APP_JS.read_text(encoding="utf-8")

    assert template.index('id="earnapp-token-alerts"') < template.index('id="earnapp-account-rows"')
    assert "Collector route" in template
    assert "account.route" in javascript
    assert "egress_ip" in javascript
    assert "checked_at" in javascript
    assert "collector.collected_at" in javascript
    assert "Last collected" in javascript
    assert "collector.usage_current" in javascript
    assert "Current qualified usage" in javascript
    assert "proxy.password" not in javascript
    assert "credentials_enc" not in javascript


def test_fleet_renders_earnapp_node_health_from_worker_provider_state():
    template = FLEET.read_text(encoding="utf-8")

    assert "w.provider_states.earnapp" in template
    assert "EarnApp:" in template
    assert "proxy_health" in template


def test_settings_keeps_earnapp_lxd_values_read_only_under_runtime_policy():
    template = SETTINGS.read_text(encoding="utf-8")

    assert 'data-config="earnapp_lxd_cpu"' in template
    assert 'data-config="earnapp_lxd_memory_mib"' in template
    assert "Runtime deployment disabled" in template
    assert 'id="earnapp-lxd-cpu" data-config="earnapp_lxd_cpu" value="1" disabled' in template
    assert 'id="earnapp-lxd-memory" data-config="earnapp_lxd_memory_mib" value="1024" disabled' in template
    assert "Save EarnApp runtime" not in template


def test_settings_marks_existing_earnapp_nodes_inspection_only():
    template = SETTINGS.read_text(encoding="utf-8")
    javascript = APP_JS.read_text(encoding="utf-8")

    assert "Existing hosted nodes are inspection-only" in template
    assert "Issue ticket" not in javascript
    assert "Recovery disabled by runtime policy" in javascript
