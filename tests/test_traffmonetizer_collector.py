import asyncio

import httpx

from app.collectors import traffmonetizer


def test_collector_uses_the_api_host_published_by_the_current_dashboard_bundle():
    assert traffmonetizer.API_BASE == "https://data.traffmonetizer.com/api"


def test_collector_classifies_current_api_validation_error_as_auth():
    class Client:
        async def post(self, *_args, **_kwargs):
            return httpx.Response(422, request=httpx.Request("POST", "https://data.traffmonetizer.com/api/auth/login"))

        async def get(self, *_args, **_kwargs):
            raise AssertionError("balance must not be requested after rejected login")

    collector = traffmonetizer.TraffmonetizerCollector("owner@example.com", "bad")
    collector._get_client = lambda **_kwargs: Client()
    result = asyncio.run(collector.collect())

    assert result.error_kind == "auth"
    assert "credentials rejected" in (result.error or "")


def test_collector_treats_login_rate_limit_as_transient():
    class Client:
        async def post(self, *_args, **_kwargs):
            return httpx.Response(
                429,
                headers={"Retry-After": "60"},
                request=httpx.Request("POST", "https://data.traffmonetizer.com/api/auth/login"),
            )

        async def get(self, *_args, **_kwargs):
            raise AssertionError("balance must not be requested after rate limit")

    collector = traffmonetizer.TraffmonetizerCollector("owner@example.com", "password")
    collector._get_client = lambda **_kwargs: Client()
    result = asyncio.run(collector.collect())

    assert result.error_kind == "transient"
    assert "rate limited" in (result.error or "").lower()


def test_collector_honors_rate_limit_cooldown(monkeypatch):
    traffmonetizer._COOLDOWN_UNTIL = 0.0
    calls = 0

    class Client:
        async def post(self, *_args, **_kwargs):
            nonlocal calls
            calls += 1
            return httpx.Response(
                429,
                headers={"Retry-After": "60"},
                request=httpx.Request("POST", "https://data.traffmonetizer.com/api/auth/login"),
            )

    collector = traffmonetizer.TraffmonetizerCollector("owner@example.com", "password")
    collector._get_client = lambda **_kwargs: Client()
    first = asyncio.run(collector.collect())
    second = asyncio.run(collector.collect())

    assert first.error_kind == "transient"
    assert second.error_kind == "transient"
    assert calls == 1


def test_rate_limit_cooldown_survives_new_collector_instance():
    traffmonetizer._COOLDOWN_UNTIL = 0.0
    calls = 0

    class Client:
        async def post(self, *_args, **_kwargs):
            nonlocal calls
            calls += 1
            return httpx.Response(
                429,
                headers={"Retry-After": "60"},
                request=httpx.Request("POST", "https://data.traffmonetizer.com/api/auth/login"),
            )

    first = traffmonetizer.TraffmonetizerCollector("owner@example.com", "password")
    first._get_client = lambda **_kwargs: Client()
    asyncio.run(first.collect())

    second = traffmonetizer.TraffmonetizerCollector("owner@example.com", "password")
    second._get_client = lambda **_kwargs: Client()
    result = asyncio.run(second.collect())

    assert result.error_kind == "transient"
    assert calls == 1
