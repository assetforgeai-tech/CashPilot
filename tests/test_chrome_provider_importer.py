from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "contrib" / "chrome-provider-importer"


def test_importer_extension_manifest_is_loadable():
    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 3
    assert "scripting" in manifest["permissions"]
    assert manifest["action"]["default_popup"] == "popup.html"


def test_earnapp_importer_uses_cookie_service_worker_with_narrow_host_permissions():
    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    assert "cookies" in manifest["permissions"]
    assert manifest["background"]["service_worker"] == "background.js"
    assert "<all_urls>" not in manifest["host_permissions"]
    assert {
        "https://earnapp.com/*",
        "https://*.earnapp.com/*",
        "https://4gmt.com/*",
        "https://*.4gmt.com/*",
    }.issubset(set(manifest["host_permissions"]))
    assert "<all_urls>" not in manifest["host_permissions"]


def test_all_provider_imports_use_only_the_https_4gmt_cashpilot_origin():
    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    popup = (EXT / "popup.js").read_text(encoding="utf-8")

    assert "http://42.96.13.215:8080/*" not in manifest["host_permissions"]
    assert not any(permission.startswith("http://") for permission in manifest["host_permissions"])
    assert 'const DEFAULT_SERVER = "https://cashpilot.4gmt.com"' in popup
    assert "42.96.13.215" not in popup
    assert 'url.protocol !== "https:"' in popup
    assert 'hostname === "4gmt.com" || hostname.endsWith(".4gmt.com")' in popup
    assert "url.username" in popup
    assert "url.password" in popup


def test_importer_saves_through_cashpilot_settings_api_only():
    popup = (EXT / "popup.js").read_text(encoding="utf-8")
    assert 'fetch("/api/config"' in popup
    assert 'credentials: "same-origin"' in popup
    assert 'const DEFAULT_SERVER = "https://cashpilot.4gmt.com"' in popup
    assert 'normalizeServer(document.getElementById("server-url").value || DEFAULT_SERVER)' in popup


def test_popup_reports_invalid_cashpilot_urls_instead_of_rejecting_outside_its_error_handler():
    popup = (EXT / "popup.js").read_text(encoding="utf-8")
    save = popup[popup.index("async function save()") : popup.index("function normalizeServer")]

    assert save.index("try {") < save.index("const server = normalizeServer")
    assert save.index("try {") < save.index("await chrome.storage.local.set")
    assert 'setStatus(`<div class="warn">Save failed:' in save


def test_importer_has_explicit_provider_key_mapping():
    extractor = (EXT / "extractor.js").read_text(encoding="utf-8")
    for slug in (
        "earnfm",
        "iproyal",
        "mysterium",
        "packetstream",
        "proxies_sx",
        "proxybase",
        "proxybase-xyz",
        "proxyrack",
        "repocket",
        "spide",
        "traffmonetizer",
        "uprock",
        "urnetwork",
        "wipter",
    ):
        assert slug in extractor
    for key in (
        "earnfm_token",
        "iproyal_collector_email",
        "iproyal_collector_password",
        "mysterium_mmn_api_key",
        "traffmonetizer_token",
        "packetstream_auth_token",
        "packetstream_cid",
        "proxies-sx_api_key",
        "proxybase-xyz_phrase",
        "spide_dashboard_token",
        "urnetwork_api_key",
        "urnetwork_email",
        "urnetwork_password",
        "proxybase_dashboard_access_token",
        "proxyrack_api_key",
        "repocket_api_key",
        "uprock_credentials_json",
        "wipter_email",
    ):
        assert key in extractor


def test_importer_keys_are_backend_settings_keys():
    from app import catalog
    from app.collectors import collector_credential_fields, service_credential_fields

    extractor = (EXT / "extractor.js").read_text(encoding="utf-8")
    imported = set(__import__("re").findall(r'add\("([^"]+)"', extractor))
    known = set()
    for svc in catalog.get_services():
        slug = svc["slug"]
        fields = (
            collector_credential_fields(slug, svc)
            + service_credential_fields(slug, "deploy", svc, fallback=False)
            + service_credential_fields(slug, "dashboard", svc, fallback=False)
        )
        known.update(field["key"] for field in fields)

    assert imported <= known


def test_popup_requires_scan_before_save_and_hides_values():
    popup = (EXT / "popup.js").read_text(encoding="utf-8")
    assert 'document.getElementById("save").disabled = true' in popup
    assert "Object.keys(payload.data)" in popup
    assert "JSON.stringify(payload.data)" not in popup


def test_popup_saves_in_one_script_injection():
    popup = (EXT / "popup.js").read_text(encoding="utf-8")
    assert popup.count("chrome.scripting.executeScript") == 2
    assert 'files: ["save_to_cashpilot.js"]' not in popup
    assert "window.__cashpilotSaveImportedProviderConfig" not in popup


def test_earnapp_cookie_allowlist_is_exact_and_never_targets_identity_provider_cookies():
    background = (EXT / "background.js").read_text(encoding="utf-8")
    expected = {
        "auth",
        "auth-method",
        "oauth-refresh-token",
        "oauth-token",
        "xsrf-token",
        "brd_sess_id",
        "cg_uuid",
    }
    marker = "const EARNAPP_COOKIE_ALLOWLIST = Object.freeze(["
    start = background.index(marker) + len(marker)
    end = background.index("]);", start)
    actual = set(__import__("re").findall(r'"([^"]+)"', background[start:end]))
    assert actual == expected
    assert 'domain: "earnapp.com"' in background
    assert "accounts.google.com" not in background
    assert "appleid.apple.com" not in background


def test_earnapp_first_import_is_explicit_and_binds_one_chrome_profile_to_one_account():
    popup_html = (EXT / "popup.html").read_text(encoding="utf-8")
    popup = (EXT / "popup.js").read_text(encoding="utf-8")
    background = (EXT / "background.js").read_text(encoding="utf-8")

    assert 'id="earnapp-auth-method"' in popup_html
    assert 'value="google"' in popup_html
    assert 'value="apple"' in popup_html
    assert 'id="import-earnapp"' in popup_html
    assert 'document.getElementById("import-earnapp").addEventListener("click"' in popup
    assert 'type: "IMPORT_EARNAPP_ACCOUNT"' in popup
    assert 'const EARNAPP_BINDING_KEY = "earnappAccountBinding"' in background
    assert "crypto.randomUUID()" in background
    assert "assertSameAccount" in background


def test_earnapp_background_sync_only_runs_after_binding_and_tracks_expiry_metadata():
    background = (EXT / "background.js").read_text(encoding="utf-8")
    assert "decodeJwtExpiry" in background
    assert "expirationDate" in background
    assert "if (!binding) return" in background
    assert "chrome.cookies.onChanged.addListener" in background
    assert "syncBoundEarnAppAccount" in background
    assert 'type: "EARNAPP_SYNC_STATUS"' in background
    assert "periodInMinutes: 15" in background


def test_earnapp_cookie_debounce_does_not_replace_the_periodic_sync_alarm():
    background = (EXT / "background.js").read_text(encoding="utf-8")
    cookie_listener = background[
        background.index("chrome.cookies.onChanged.addListener") : background.index("chrome.alarms.onAlarm.addListener")
    ]
    alarm_listener = background[
        background.index("chrome.alarms.onAlarm.addListener") : background.index(
            "chrome.runtime.onInstalled.addListener"
        )
    ]

    assert 'const EARNAPP_COOKIE_DEBOUNCE_ALARM = "earnapp-cookie-debounce"' in background
    assert "chrome.alarms.create(EARNAPP_COOKIE_DEBOUNCE_ALARM, { delayInMinutes: 0.5 })" in cookie_listener
    assert "EARNAPP_SYNC_ALARM" not in cookie_listener
    assert "alarm.name === EARNAPP_COOKIE_DEBOUNCE_ALARM" in alarm_listener


def test_earnapp_sync_rejects_non_https_or_non_4gmt_destinations_and_hides_secrets():
    background = (EXT / "background.js").read_text(encoding="utf-8")
    popup = (EXT / "popup.js").read_text(encoding="utf-8")

    assert 'url.protocol !== "https:"' in background
    assert 'hostname === "4gmt.com" || hostname.endsWith(".4gmt.com")' in background
    assert '"/api/admin/earnapp/accounts/import"' in background
    assert 'credentials: "same-origin"' in background
    assert "console.log" not in background
    assert "JSON.stringify(cookies)" not in popup
