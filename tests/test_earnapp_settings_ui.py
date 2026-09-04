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


def test_settings_renders_sanitized_earnapp_payment_sync_state():
    template = SETTINGS.read_text(encoding="utf-8")
    javascript = APP_JS.read_text(encoding="utf-8")

    assert "Payment" in template
    assert "collector.payment" in javascript
    assert "Auto-redeem" in javascript
    assert "Available methods" in javascript
    assert "destination_masked" in javascript
    assert "transactions" in javascript
    assert "configureEarnAppPayment" in javascript
    assert "disableEarnAppPayment" in javascript
    assert "Set auto-redeem" in javascript
    assert "Disable auto-redeem" in javascript
    assert "paypal_email" not in javascript


def test_fleet_renders_earnapp_node_health_from_worker_provider_state():
    template = FLEET.read_text(encoding="utf-8")

    assert "w.provider_states.earnapp" in template
    assert "EarnApp:" in template
    assert "proxy_health" in template


def test_settings_exposes_authoritative_earnapp_lxd_values():
    template = SETTINGS.read_text(encoding="utf-8")

    assert 'data-config="earnapp_lxd_cpu"' in template
    assert 'data-config="earnapp_lxd_memory_mib"' in template
    assert "EarnApp Docker runtime" in template
    assert 'id="earnapp-lxd-cpu" data-config="earnapp_lxd_cpu" value="1"' in template
    assert 'id="earnapp-lxd-memory" data-config="earnapp_lxd_memory_mib" value="1024"' in template
    assert "Save EarnApp runtime" in template


def test_settings_scopes_recovery_to_ubuntu_and_keeps_apple_inspection_only():
    template = SETTINGS.read_text(encoding="utf-8")
    javascript = APP_JS.read_text(encoding="utf-8")

    assert "EarnApp Docker nodes support" in template
    assert "Issue ticket" in javascript
    assert "MacOS/iOS runtime is inspection-only" in javascript
