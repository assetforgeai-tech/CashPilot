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


def test_importer_saves_through_cashpilot_settings_api_only():
    popup = (EXT / "popup.js").read_text(encoding="utf-8")
    assert 'fetch("/api/config"' in popup
    assert 'credentials: "same-origin"' in popup
    assert "http://42.96.13.215" in popup


def test_importer_has_explicit_provider_key_mapping():
    extractor = (EXT / "extractor.js").read_text(encoding="utf-8")
    for slug in (
        "earnfm",
        "grass",
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
        "grass_store_access_token",
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
