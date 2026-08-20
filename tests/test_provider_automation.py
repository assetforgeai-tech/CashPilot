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


def test_wipter_status_snapshot_distinguishes_login_from_setup_and_traffic():
    logs = "\n".join(
        [
            "Wipter setup complete.",
            "Credential stored for service: com.wipter.auth.production",
            "HTTPS Request ID abc",
        ]
    )

    assert provider_automation.wipter_status_snapshot(logs) == {
        "ok": True,
        "authenticated": True,
        "earning": True,
        "traffic_seen": True,
    }


def test_wipter_setup_complete_alone_is_not_authenticated():
    assert provider_automation.wipter_status_snapshot("Wipter setup complete.") == {
        "ok": False,
        "authenticated": False,
        "earning": False,
        "traffic_seen": False,
    }


def test_wipter_status_accepts_persisted_login_state_without_log_marker():
    assert provider_automation.wipter_status_snapshot("HTTPS Request ID abc", login_state_persisted=True) == {
        "ok": True,
        "authenticated": True,
        "earning": True,
        "traffic_seen": True,
    }


def test_wipter_post_login_restart_waits_for_real_login_state():
    from unittest.mock import MagicMock

    container = MagicMock()
    container.logs.side_effect = [b"Wipter setup complete.", b"Saving new token"]

    assert provider_automation.apply_wipter_post_login_restart(container, timeout_seconds=1, poll_seconds=0) is True
    container.restart.assert_called_once()


def test_wipter_restart_scheduler_returns_without_waiting():
    from unittest.mock import MagicMock, patch

    with patch("app.provider_automation.threading.Thread") as thread:
        provider_automation.schedule_wipter_post_login_restart(MagicMock())

    thread.return_value.start.assert_called_once()
