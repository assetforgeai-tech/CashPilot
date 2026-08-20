from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def _response(status: int, payload: object):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    if status >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status}")
    return resp


def _client():
    client = MagicMock()
    client.get = AsyncMock()
    return client


class TestProxiesSxCollector:
    def test_collect_sums_pending_payout_when_present(self):
        from app.collectors.proxies_sx import ProxiesSxCollector

        client = _client()
        client.get.return_value = _response(
            200,
            {
                "devices": [
                    {"deviceId": "a", "name": "n1", "pendingPayout": 1.25, "status": "earning"},
                    {"deviceId": "b", "name": "n2", "pendingPayout": "2.75", "status": "listed"},
                ]
            },
        )

        with patch("app.collectors.proxies_sx.httpx.AsyncClient", return_value=client):
            result = asyncio.run(ProxiesSxCollector(api_key="k").collect())

        assert result.error is None
        assert result.balance == 4.0
        assert result.currency == "USD"

    def test_collect_falls_back_to_total_earned(self):
        from app.collectors.proxies_sx import ProxiesSxCollector

        client = _client()
        client.get.return_value = _response(
            200,
            [
                {"deviceId": "a", "name": "n1", "totalEarned": 1.0},
                {"deviceId": "b", "name": "n2", "totalEarned": "2.5"},
            ],
        )

        with patch("app.collectors.proxies_sx.httpx.AsyncClient", return_value=client):
            result = asyncio.run(ProxiesSxCollector(api_key="k").collect())

        assert result.error is None
        assert result.balance == 3.5

    def test_collect_auth_failure(self):
        from app.collectors.proxies_sx import ProxiesSxCollector

        resp = _response(401, {})
        client = _client()
        client.get.return_value = resp

        with patch("app.collectors.proxies_sx.httpx.AsyncClient", return_value=client):
            result = asyncio.run(ProxiesSxCollector(api_key="bad").collect())

        assert result.error is not None
        assert "API key" in result.error

    def test_per_node_treats_online_status_as_online(self):
        from app.collectors.proxies_sx import ProxiesSxCollector

        client = _client()
        client.get.return_value = _response(
            200,
            {"devices": [{"deviceId": "agent-1", "name": "n1", "status": "online"}]},
        )

        with patch("app.collectors.proxies_sx.httpx.AsyncClient", return_value=client):
            devices = asyncio.run(ProxiesSxCollector(api_key="k").get_per_node_earnings())

        assert devices[0]["online"] is True

    def test_per_node_normalizes_dashboard_fields(self):
        from app.collectors.proxies_sx import ProxiesSxCollector

        client = _client()
        client.get.return_value = _response(
            200,
            {
                "devices": [
                    {
                        "deviceId": "agent-1",
                        "name": "peer-a",
                        "status": "listed",
                        "listed": True,
                        "verification": "verified",
                        "speed": "5.6 Mbps",
                        "customerRoutable": "yes",
                        "quality": 55,
                        "traffic": "0.0 MB",
                        "lastSeen": "less than a minute",
                        "pendingPayout": 1.25,
                        "totalEarned": 7.5,
                    }
                ]
            },
        )

        with patch("app.collectors.proxies_sx.httpx.AsyncClient", return_value=client):
            row = asyncio.run(ProxiesSxCollector(api_key="k").get_per_node_earnings())[0]

        assert row["device_id"] == "agent-1"
        assert row["name"] == "peer-a"
        assert row["status"] == "listed"
        assert row["online"] is True
        assert row["listed"] is True
        assert row["verification"] == "verified"
        assert row["speed"] == "5.6 Mbps"
        assert row["customer_routable"] is True
        assert row["quality"] == 55
        assert row["traffic"] == "0.0 MB"
        assert row["last_seen"] == "less than a minute"
        assert row["pending_payout_usd"] == 1.25
        assert row["total_earned_usd"] == 7.5
