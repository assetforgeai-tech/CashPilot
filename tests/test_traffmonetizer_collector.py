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
