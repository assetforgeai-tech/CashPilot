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
