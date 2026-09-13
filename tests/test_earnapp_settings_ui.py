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
    assert "active_nodes" in javascript
    assert "recovery_nodes" in javascript
    assert "planned_nodes" in javascript
    assert "proxy.password" not in javascript
    assert "credentials_enc" not in javascript


def test_settings_displays_cookie_expiry_evidence_when_jwt_expiry_is_missing():
    javascript = APP_JS.read_text(encoding="utf-8")
    assert "account.cookie_expires_at" in javascript
    assert "token_expiry_source" in javascript
    assert "evidence" in javascript


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


def test_earnapp_payment_uses_inline_modal_instead_of_prompt():
    template = SETTINGS.read_text(encoding="utf-8")
    javascript = APP_JS.read_text(encoding="utf-8")
    start = javascript.index("async function configureEarnAppPayment")
    end = javascript.index("async function disableEarnAppPayment", start)
    payment_function = javascript[start:end]
    assert 'id="earnapp-payment-modal"' in template
    assert "earnapp-payment-method" in template
    assert 'id="earnapp-payment-modal-destination"' in template
    assert template.count('id="earnapp-paypal-destination"') == 1
    assert template.count('id="earnapp-payment-modal-destination"') == 1
    assert "getElementById('earnapp-payment-modal-destination')" in payment_function
    assert "window.prompt" not in payment_function


def test_earnapp_capacity_exposes_sticky_owned_egress():
    template = SETTINGS.read_text(encoding="utf-8")
    javascript = APP_JS.read_text(encoding="utf-8")
    assert "Owned egress" in template
    assert "capacity.sticky_owned" in javascript
    assert "/payment/paypal-pool" in javascript


def test_settings_exposes_paypal_pool_controls_without_raw_destinations():
    template = SETTINGS.read_text(encoding="utf-8")
    javascript = APP_JS.read_text(encoding="utf-8")
    assert 'id="earnapp-paypal-pool"' in template
    assert template.index('id="earnapp-paypal-pool"') < template.index('id="earnapp-payment-modal"')
    assert template.index('id="earnapp-paypal-pool"') < template.index('class="earnapp-account-grid"')
    assert template.index('id="earnapp-paypal-pool"') < template.index('id="earnapp-proxy-capacity"')
    assert "loadEarnAppPayPalPool" in javascript
    assert "addEarnAppPayPal" in javascript
    assert "destination_masked" in javascript


def test_paypal_pool_is_prominent_and_self_describing():
    template = SETTINGS.read_text(encoding="utf-8")
    assert 'aria-labelledby="earnapp-paypal-pool-title"' in template
    assert 'id="earnapp-paypal-pool-title"' in template
    assert "Settings &gt; EarnApp Account Pool" in template
    assert "earnapp-paypal-settings" in template


def test_settings_exposes_a_paypal_quick_link_before_long_sections():
    template = SETTINGS.read_text(encoding="utf-8")
    assert 'id="settings-quick-links"' in template
    assert 'href="#earnapp-paypal-pool"' in template
    assert template.index('id="settings-quick-links"') < template.index('id="earnapp-account-pool"')


def test_settings_quick_links_separate_provider_control_plane_sections():
    template = SETTINGS.read_text(encoding="utf-8")
    for anchor, label in (
        ("#provider-account-pools", "Accounts"),
        ("#earnapp-account-pool", "EarnApp input"),
        ("#earnapp-runtime-settings", "Runtime"),
        ("#earnapp-reconciliation", "Collector health"),
    ):
        assert f'href="{anchor}"' in template
        assert label in template


def test_settings_shows_read_only_earnapp_reconciliation():
    template = SETTINGS.read_text(encoding="utf-8")
    javascript = APP_JS.read_text(encoding="utf-8")
    assert 'id="earnapp-reconciliation"' in template
    assert 'id="earnapp-reconciliation-list"' in template
    assert "/api/admin/earnapp/reconciliation" in javascript
    assert "missing_from_worker" in javascript
    assert "untracked_on_worker" in javascript


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


def test_settings_save_preserves_explicitly_disabled_platform_checks():
    script = (ROOT / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert "if (input.type === 'checkbox' || val)" in script


def test_settings_scopes_recovery_to_all_docker_platforms():
    template = SETTINGS.read_text(encoding="utf-8")
    javascript = APP_JS.read_text(encoding="utf-8")

    assert "EarnApp Docker nodes support" in template
    assert "Issue ticket" in javascript
    assert "MacOS/iOS runtime is inspection-only" not in javascript
    assert "Docker runtime recovery" in javascript


def test_earnapp_notice_matches_docker_only_runtime():
    javascript = APP_JS.read_text(encoding="utf-8")

    assert "official Ubuntu x64 in Docker" in javascript
    assert "Ubuntu LXD CPU/RAM" not in javascript
    assert "official Ubuntu x64 in LXD" not in javascript
