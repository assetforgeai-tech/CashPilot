from __future__ import annotations

import asyncio

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


def test_register_spide_device_uses_form_encoded_raw_setup_contract(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    calls = {}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            calls.update(url=url, kwargs=kwargs)
            return Response()

    monkeypatch.setattr(provider_automation.httpx, "AsyncClient", lambda **_kwargs: Client())
    asyncio.run(provider_automation.register_spide_device("tok", "key", title="node"))
    assert calls["kwargs"]["data"] == {"title": "node", "device_key": "key"}
    assert "json" not in calls["kwargs"]


def test_login_spide_uses_form_encoded_credentials(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"token": "fresh-token"}

    calls = {}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            calls.update(url=url, kwargs=kwargs)
            return Response()

    monkeypatch.setattr(provider_automation.httpx, "AsyncClient", lambda **_kwargs: Client())
    token = asyncio.run(provider_automation.login_spide("user@example.com", "pw"))
    assert token == "fresh-token"
    assert calls["kwargs"]["data"] == {"email": "user@example.com", "password": "pw"}
    assert calls["kwargs"]["headers"]["X-Requested-With"] == "XMLHttpRequest"


def test_login_spide_retries_transient_http_failure(monkeypatch):
    calls = {"count": 0}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            calls["count"] += 1
            if calls["count"] < 3:
                return type(
                    "Response",
                    (),
                    {
                        "status_code": 500,
                        "is_error": True,
                        "text": "retry",
                        "raise_for_status": lambda self: None,
                    },
                )()
            return type(
                "Response",
                (),
                {
                    "status_code": 200,
                    "is_error": False,
                    "raise_for_status": lambda self: None,
                    "json": lambda self: {"token": "fresh-token"},
                },
            )()

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(provider_automation.httpx, "AsyncClient", lambda **_kwargs: Client())
    monkeypatch.setattr(provider_automation.asyncio, "sleep", no_wait)
    assert asyncio.run(provider_automation.login_spide("user@example.com", "pw")) == "fresh-token"
    assert calls["count"] == 3


def test_register_spide_device_retries_transient_http_failure(monkeypatch):
    class Response:
        status_code = 503
        is_error = True
        text = "temporarily unavailable"

        def json(self):
            return {"message": "temporarily unavailable"}

    calls = {"count": 0}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            calls["count"] += 1
            if calls["count"] < 3:
                return Response()

            class Success:
                status_code = 200
                is_error = False

                def json(self):
                    return {"ok": True}

            return Success()

    monkeypatch.setattr(provider_automation.httpx, "AsyncClient", lambda **_kwargs: Client())

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(provider_automation.asyncio, "sleep", no_sleep)
    assert asyncio.run(provider_automation.register_spide_device("tok", "key", title="node")) == {"ok": True}
    assert calls["count"] == 3


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
