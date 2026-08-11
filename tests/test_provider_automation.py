from __future__ import annotations

from app import provider_automation


def test_extract_spide_device_key_accepts_cli_output():
    logs = "start\nDevice key: SPIDE-abc_123456\nwaiting"
    assert provider_automation.extract_spide_device_key(logs) == "SPIDE-abc_123456"


def test_spide_auth_headers_accept_cookie_or_bearer():
    cookie = provider_automation.spide_auth_headers("x=1; _token=tok123; y=2")
    assert cookie["Cookie"] == "x=1; _token=tok123; y=2"
    assert cookie["Authorization"] == "Bearer tok123"

    bearer = provider_automation.spide_auth_headers("tok456")
    assert bearer["Authorization"] == "Bearer tok456"

def test_uprock_status_snapshot_extracts_runtime_evidence():
    payload = '{"status":"ok","authenticated":true,"earning":true,"earn_rate":0.25,"version":"v0.0.38"}'
    logs = "connected url=wss://ws.olostep.com?device_id=uprock_00636ab7dd82d6a5&platform=desktop-linux"

    out = provider_automation.uprock_status_snapshot(payload, logs)

    assert out == {
        "ok": True,
        "authenticated": True,
        "earning": True,
        "earn_rate": 0.25,
        "version": "v0.0.38",
        "device_id": "uprock_00636ab7dd82d6a5",
    }
