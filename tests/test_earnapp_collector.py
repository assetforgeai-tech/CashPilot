from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app import database, earnapp_accounts, earnapp_collection, earnapp_recovery, main
from app.collectors import COLLECTOR_MAP, earnapp
from app.collectors.base import EarningsResult
from app.collectors.earnapp import EarnAppAccountCollector, build_proxy_url, normalize_snapshot


def _account(profile: str = "profile-a") -> dict[str, object]:
    return {
        "profile_key": profile,
        "account_name": f"{profile}@example.com",
        "email": f"{profile}@example.com",
        "auth_method": "google",
        "cookies": {
            "auth": {"value": "1"},
            "auth-method": {"value": "google"},
            "oauth-refresh-token": {"value": f"refresh-{profile}"},
            "xsrf-token": {"value": f"xsrf-{profile}"},
        },
    }


async def _seed_proxy(
    provider_id: int,
    suffix: int,
    *,
    status: str = "alive",
    ip_type: str = "residential",
    country_code: str = "VN",
) -> int:
    (proxy_id,) = await database.upsert_proxy_endpoints_returning_ids(
        provider_id,
        [
            {
                "provider_proxy_id": f"proxy-{suffix}",
                "endpoint": f"proxy{suffix}.example:10{suffix:02d}",
                "host": f"proxy{suffix}.example",
                "port": 1000 + suffix,
                "protocol": "socks5",
                "username": f"user-{suffix}",
                "password": f"pass-{suffix}",
                "status": status,
                "exit_ip": f"198.51.100.{suffix}",
                "ip_type": ip_type,
                "country_code": country_code,
            }
        ],
    )
    await database.update_proxy_endpoint_intelligence(
        proxy_id,
        {
            "ip_type": ip_type,
            "ip_type_source": "test",
            "ip_type_confidence": "high",
            "country_code": country_code,
            "country_name": "Vietnam" if country_code == "VN" else "United States",
            "geo_source": "test",
            "geo_confidence": "high",
        },
    )
    await database.save_proxy_probe_result(
        proxy_id,
        profile="earnapp_wss",
        probe_status=status,
        verdict="CID_SET" if status == "alive" else "DECLINE",
        eligibility="eligible" if status == "alive" else "blocked",
        reason="",
        exit_ip=f"198.51.100.{suffix}",
        latency_ms=20,
        probe_version="test",
    )
    return proxy_id


def test_proxy_url_encodes_credentials_and_supports_http_and_socks5():
    assert (
        build_proxy_url(
            {"protocol": "socks5", "host": "proxy.example", "port": 1080, "username": "user@x", "password": "p:a/ss"}
        )
        == "socks5://user%40x:p%3Aa%2Fss@proxy.example:1080"
    )


def test_normalize_snapshot_supports_current_earnapp_money_and_device_shape():
    snapshot = normalize_snapshot(
        {},
        {"balance": 2.31, "earnings_total": 2.31},
        [
            {
                "uuid": "device-a",
                "country": "vn",
                "ips": ["198.51.100.1"],
                "rate": 5,
                "earned": 0.026,
                "earned_total": 0.026,
                "uptime": 13654694,
                "total_uptime": 13654694,
                "billing": "qualified_uptime",
            }
        ],
        {"device-a": [1787700000, 60]},
    )

    assert snapshot == {
        "status": "ok",
        "money_balance": 2.31,
        "money_total": 2.31,
        "online_nodes": 1,
        "offline_nodes": 0,
        "usage_current": 0,
        "usage_total": 0,
        "usage_available_nodes": 0,
        "usage_missing_nodes": 1,
        "devices": [
            {
                "device_id": "device-a",
                "ip": "198.51.100.1",
                "country_code": "VN",
                "rate": 5.0,
                "bandwidth": None,
                "total_bandwidth": None,
                "redeemed_bandwidth": None,
                "earned": 0.026,
                "earned_total": 0.026,
                "uptime": 13654694,
                "total_uptime": 13654694,
                "billing": "qualified_uptime",
                "usage_total": None,
                "usage_current": None,
                "usage_points": 0,
                "usage_available": False,
                "online": True,
            }
        ],
    }
    assert (
        build_proxy_url({"protocol": "http", "host": "2001:db8::1", "port": 8080, "username": "", "password": ""})
        == "http://[2001:db8::1]:8080"
    )


def test_account_without_nodes_gets_an_exclusive_control_route_that_transfers_to_first_node(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account_id = await earnapp_accounts.import_account(_account())
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            first_proxy = await _seed_proxy(provider_id, 1)
            second_proxy = await _seed_proxy(provider_id, 2)

            route = await earnapp_collection.ensure_collection_route(account_id)
            assert route is not None
            assert route["source"] == "account_control"
            assert route["proxy_id"] == first_proxy

            worker = await database.upsert_worker("worker-a", "worker-a", "http://worker")
            other = await database.lease_proxy_for_provider_instance("test-provider", worker, "other-node")
            assert other is not None and other["proxy_id"] == second_proxy

            node = await earnapp_recovery.provision_node("earnapp-node-a", worker, device_id="device-a")
            assert node["proxy_id"] == first_proxy
            node_route = await earnapp_collection.ensure_collection_route(account_id)
            assert node_route is not None
            assert node_route["source"] == "node"
            assert node_route["logical_node_id"] == "earnapp-node-a"
            assert node_route["proxy_id"] == first_proxy
            control = await database.get_earnapp_account_control_route(account_id, include_released=True)
            assert control is not None
            assert control["state"] == "TRANSFERRED"
            assert control["assigned_logical_node_id"] == "earnapp-node-a"

    asyncio.run(run())


def test_account_control_route_is_excluded_from_legacy_lease_and_manual_assignment(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account_id = await earnapp_accounts.import_account(_account())
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            control_proxy = await _seed_proxy(provider_id, 1)
            free_proxy = await _seed_proxy(provider_id, 2)
            route = await earnapp_collection.ensure_collection_route(account_id)
            assert route is not None and route["proxy_id"] == control_proxy

            manual_worker = await database.upsert_worker("worker-manual", "manual", "http://manual")
            assert await database.set_worker_proxy_assignment(manual_worker, control_proxy) is False

            leased_worker = await database.upsert_worker("worker-lease", "lease", "http://lease")
            lease = await database.lease_proxy_for_worker(leased_worker)
            assert lease is not None and lease["proxy_id"] == free_proxy

    asyncio.run(run())


def test_account_control_route_is_excluded_from_rotation_read_and_commit_paths(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account_id = await earnapp_accounts.import_account(_account())
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            control_proxy = await _seed_proxy(provider_id, 1)
            current_proxy = await _seed_proxy(provider_id, 2)
            free_proxy = await _seed_proxy(provider_id, 3)
            route = await earnapp_collection.ensure_collection_route(account_id)
            assert route is not None and route["proxy_id"] == control_proxy

            worker = await database.upsert_worker("worker-rotate", "rotate", "http://rotate")
            assert await database.set_worker_proxy_assignment(worker, current_proxy, "proxy", "rotate")
            await database.save_provider_instance(
                "protected-example",
                "protected-example-proxy",
                worker_id=worker,
                mode="proxy",
                proxy_id=current_proxy,
                status="running",
            )
            current = await database.get_worker_proxy_assignment(worker)
            candidate = await database.find_available_proxy_for_worker(worker)
            assert candidate is not None and candidate["proxy_id"] == free_proxy

            committed = await database.commit_proxy_rotation(
                worker,
                expected_proxy_id=current_proxy,
                expected_assignment_version=current["assignment_version"],
                new_proxy_id=control_proxy,
                instance_ids=["protected-example-proxy"],
            )
            assert committed is False
            assert (await database.get_worker_proxy_assignment(worker))["proxy_id"] == current_proxy
            assert (await database.get_provider_instance("protected-example-proxy"))["proxy_id"] == current_proxy

    asyncio.run(run())


def test_locked_account_deletion_releases_its_control_route(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account_id = await earnapp_accounts.import_account(_account())
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            await _seed_proxy(provider_id, 1)
            assert await earnapp_collection.ensure_collection_route(account_id) is not None

            assert await database.set_earnapp_account_state(account_id, "ACCOUNT_LOCKED")
            assert await earnapp_accounts.delete_account(account_id)
            route = await database.get_earnapp_account_control_route(account_id, include_released=True)
            assert route is not None
            assert route["state"] == "RELEASED"
            assert route["release_reason"] == "ACCOUNT_DELETED"
            assert route["released_at"]

    asyncio.run(run())


def test_account_without_nodes_rotates_an_unhealthy_control_proxy(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account_id = await earnapp_accounts.import_account(_account())
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            first_proxy = await _seed_proxy(provider_id, 1)
            second_proxy = await _seed_proxy(provider_id, 2)
            first = await earnapp_collection.ensure_collection_route(account_id)
            assert first is not None and first["proxy_id"] == first_proxy

            await database.update_proxy_pool_check_results({first_proxy: "dead"})
            replacement = await earnapp_collection.ensure_collection_route(account_id)

            assert replacement is not None
            assert replacement["proxy_id"] == second_proxy
            assert (await database.get_earnapp_account_control_route(account_id))["proxy_id"] == second_proxy

    asyncio.run(run())


def test_account_without_nodes_rotates_a_control_proxy_blocked_by_latest_earnapp_probe(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account_id = await earnapp_accounts.import_account(_account())
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            first_proxy = await _seed_proxy(provider_id, 1)
            second_proxy = await _seed_proxy(provider_id, 2)
            first = await earnapp_collection.ensure_collection_route(account_id)
            assert first is not None and first["proxy_id"] == first_proxy
            await database.save_proxy_probe_result(
                first_proxy,
                profile="earnapp_wss",
                probe_status="alive",
                verdict="BLACKLIST",
                eligibility="blocked",
                reason="blocked",
                exit_ip="198.51.100.1",
                latency_ms=20,
                probe_version="test",
            )

            replacement = await earnapp_collection.ensure_collection_route(account_id)

            assert replacement is not None
            assert replacement["proxy_id"] == second_proxy
            assert (await database.get_earnapp_account_control_route(account_id))["proxy_id"] == second_proxy

    asyncio.run(run())


def test_existing_account_nodes_never_get_a_separate_control_proxy_when_their_route_is_dead(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account_id = await earnapp_accounts.import_account(_account())
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            first_proxy = await _seed_proxy(provider_id, 1)
            await _seed_proxy(provider_id, 2)
            worker = await database.upsert_worker("worker-a", "worker-a", "http://worker")
            node = await earnapp_recovery.provision_node("earnapp-node-a", worker, device_id="device-a")
            assert node["proxy_id"] == first_proxy

            await database.update_proxy_pool_check_results({first_proxy: "dead"})
            assert await earnapp_collection.ensure_collection_route(account_id) is None
            assert await database.get_earnapp_account_control_route(account_id) is None

    asyncio.run(run())


class _Response:
    def __init__(self, status_code: int, payload: object):
        self.status_code = status_code
        self._payload = payload
        self.headers = {}
        self.request = httpx.Request("GET", "https://earnapp.com/dashboard/api/test")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("request failed", request=self.request, response=self)


class _CurrentShapeClient:
    is_closed = False

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.cookies = dict(kwargs.get("cookies") or {})

    async def get(self, url, **kwargs):
        if url.endswith("/sec/rotate_xsrf"):
            self.cookies["xsrf-token"] = "rotated-xsrf"
            return _Response(200, {"ok": 1})
        if url.endswith("/user_data"):
            return _Response(200, {"email": "owner@example.com"})
        if url.endswith("/money"):
            return _Response(200, {"balance": 2.31, "earnings_total": 2.31})
        if url.endswith("/devices"):
            return _Response(
                200,
                [
                    {
                        "uuid": "device-a",
                        "country": "vn",
                        "ips": ["198.51.100.1"],
                        "rate": 5,
                        "earned": 0.026,
                        "earned_total": 0.026,
                        "uptime": 13654694,
                        "total_uptime": 13654694,
                        "billing": "qualified_uptime",
                    }
                ],
            )

        if url.endswith("/usage"):
            assert kwargs["params"]["step"] == "daily"
            today = datetime.now(UTC).date().isoformat()
            return _Response(
                200,
                [
                    {
                        "_id": "device-a",
                        "name": "Mac A",
                        "data": {today: 13654694},
                    }
                ],
            )
        raise AssertionError(url)

    async def post(self, url, **kwargs):
        if url.endswith("/link_device"):
            assert kwargs["json"] == {
                "uuid": "device-a",
                "platform": "macos",
                "_csrf": "rotated-xsrf",
            }
            return _Response(200, {"error": "This device was already linked"})
        if url.endswith("/device_statuses"):
            return _Response(200, {"device-a": [1787700000, 60]})
        raise AssertionError(url)

    async def aclose(self):
        self.is_closed = True


class _IpBlockedClient:
    is_closed = False

    def __init__(self, **kwargs):
        self.cookies = dict(kwargs.get("cookies") or {})

    async def get(self, url, **_kwargs):
        response = _Response(200, {"ok": 1})
        if url.endswith("/sec/rotate_xsrf"):
            self.cookies["xsrf-token"] = "rotated-xsrf"
            return response
        response = _Response(406, {})
        response.headers["location"] = "https://earnapp.com/dashboard/ip_block"
        return response

    async def aclose(self):
        return None


def test_link_classifies_dashboard_ip_block_as_proxy_blocked(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _IpBlockedClient)
    collector = EarnAppAccountCollector(
        {"cookies": {"xsrf-token": "xsrf"}},
        {"protocol": "http", "host": "proxy.example", "port": 8080},
    )

    result = asyncio.run(collector.link_and_verify_device("sdk-mac-" + "a" * 32))

    assert result == {
        "status": "error",
        "error_kind": "proxy_blocked",
        "error": "EarnApp blocked the account proxy",
    }


def test_link_and_verify_device_exposes_current_workload_counters():
    credentials = {"cookies": {"oauth-refresh-token": "refresh-secret", "xsrf-token": "xsrf-secret"}}
    proxy = {"protocol": "http", "host": "proxy.example", "port": 8080}

    with patch("app.collectors.earnapp.httpx.AsyncClient", side_effect=_CurrentShapeClient):
        result = asyncio.run(EarnAppAccountCollector(credentials, proxy).link_and_verify_device("device-a"))

    assert result["status"] == "online"
    assert result["total_uptime"] == 13654694
    assert result["earned_total"] == 0.026
    assert result["usage_total"] == 13654694.0
    assert result["usage_current"] == 13654694.0
    assert result["usage_points"] == 1


class _RateLimitedLinkClient(_CurrentShapeClient):
    async def post(self, url, **kwargs):
        if url.endswith("/link_device"):
            return _Response(429, {"error": "Too many requests"})
        return await super().post(url, **kwargs)


def test_link_and_verify_device_treats_link_rate_limit_as_pending_before_workload():
    credentials = {"cookies": {"oauth-refresh-token": "refresh-secret", "xsrf-token": "xsrf-secret"}}
    proxy = {"protocol": "http", "host": "proxy.example", "port": 8080}

    with patch("app.collectors.earnapp.httpx.AsyncClient", side_effect=_RateLimitedLinkClient):
        result = asyncio.run(EarnAppAccountCollector(credentials, proxy).link_and_verify_device("device-a"))

    assert result["status"] == "pending"
    assert result["error_kind"] == "rate_limited"
    assert result["device_present"] is True
    assert result["link_attempted"] is True
    assert result["online"] is False


def test_normalize_snapshot_reads_current_and_legacy_bandwidth_counters():
    result = earnapp.normalize_snapshot(
        {},
        {"balance": 0, "earnings_total": 0},
        [
            {
                "uuid": "sdk-mac-current",
                "bw": 123,
                "total_bw": 456,
                "redeem_bw": 78,
            },
            {
                "uuid": "sdk-mac-legacy",
                "bandwidth": 12,
                "total_bandwidth": 34,
                "redeemed_bandwidth": 5,
            },
        ],
        {"sdk-mac-current": True, "sdk-mac-legacy": True},
    )

    assert result["devices"] == [
        {
            "device_id": "sdk-mac-current",
            "ip": "",
            "country_code": "",
            "rate": 0.0,
            "bandwidth": 123.0,
            "total_bandwidth": 456.0,
            "redeemed_bandwidth": 78.0,
            "earned": None,
            "earned_total": None,
            "uptime": None,
            "total_uptime": None,
            "billing": "",
            "usage_total": None,
            "usage_current": None,
            "usage_points": 0,
            "usage_available": False,
            "online": True,
        },
        {
            "device_id": "sdk-mac-legacy",
            "ip": "",
            "country_code": "",
            "rate": 0.0,
            "bandwidth": 12.0,
            "total_bandwidth": 34.0,
            "redeemed_bandwidth": 5.0,
            "earned": None,
            "earned_total": None,
            "uptime": None,
            "total_uptime": None,
            "billing": "",
            "usage_total": None,
            "usage_current": None,
            "usage_points": 0,
            "usage_available": False,
            "online": True,
        },
    ]


def test_normalize_snapshot_preserves_absent_workload_metrics_as_none():
    result = earnapp.normalize_snapshot(
        {},
        {},
        [{"uuid": "sdk-mac-missing", "billing": "qualified_uptime"}],
        {"sdk-mac-missing": True},
    )

    device = result["devices"][0]
    assert device["bandwidth"] is None
    assert device["total_bandwidth"] is None
    assert device["earned_total"] is None
    assert device["uptime"] is None
    assert device["total_uptime"] is None


def test_normalize_snapshot_keeps_current_usage_separate_from_historical_total():
    today = datetime.now(UTC).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    result = earnapp.normalize_snapshot(
        {},
        {},
        [{"uuid": "sdk-mac-current", "billing": "qualified_uptime", "uptime": 18}],
        {"sdk-mac-current": True},
        [
            {
                "_id": "sdk-mac-current",
                "data": {yesterday: 7659, today.isoformat(): 18},
            }
        ],
    )

    device = result["devices"][0]
    assert device["usage_total"] == 7677.0
    assert device["usage_current"] == 18.0


def test_normalize_snapshot_summarizes_account_workload_without_counting_history_twice():
    today = datetime.now(UTC).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    result = earnapp.normalize_snapshot(
        {},
        {},
        [
            {"uuid": "sdk-mac-a", "billing": "qualified_uptime", "uptime": 120},
            {"uuid": "sdk-mac-b", "billing": "qualified_uptime", "uptime": 18},
        ],
        {"sdk-mac-a": True, "sdk-mac-b": True},
        [
            {"_id": "sdk-mac-a", "data": {yesterday: 3600, today.isoformat(): 120}},
            {"_id": "sdk-mac-b", "data": {today.isoformat(): 18}},
        ],
    )

    assert result["usage_current"] == 138.0
    assert result["usage_total"] == 3738.0
    assert result["usage_available_nodes"] == 2
    assert result["usage_missing_nodes"] == 0


def test_normalize_usage_series_supports_per_device_dashboard_rows():
    today = datetime.now(UTC).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    result = earnapp.normalize_usage_series(
        [
            {
                "_id": "sdk-mac-a",
                "name": "Mac A",
                "data": {yesterday: 3600, today.isoformat(): 120},
            },
            {
                "_id": "sdk-mac-b",
                "data": {today.isoformat(): 18},
            },
        ]
    )

    assert result == {
        "sdk-mac-a": {"name": "Mac A", "total": 3720.0, "current": 120.0, "points": 2},
        "sdk-mac-b": {"name": "sdk-mac-b", "total": 18.0, "current": 18.0, "points": 1},
    }


def test_normalize_usage_series_uses_utc_today_instead_of_a_future_key():
    today = datetime.now(UTC).date().isoformat()
    future = "2999-01-01"

    result = earnapp.normalize_usage_series(
        [
            {
                "_id": "sdk-mac-a",
                "data": {today: 120, future: 999999},
            }
        ]
    )

    assert result["sdk-mac-a"]["current"] == 120.0


def test_normalize_usage_series_does_not_treat_historical_usage_as_current():
    today = datetime.now(UTC).date()
    two_days_ago = (today - timedelta(days=2)).isoformat()
    yesterday = (today - timedelta(days=1)).isoformat()
    result = earnapp.normalize_usage_series(
        [
            {
                "_id": "sdk-mac-a",
                "data": {two_days_ago: 3600, yesterday: 120},
            }
        ]
    )

    assert result["sdk-mac-a"]["total"] == 3720.0
    assert result["sdk-mac-a"]["current"] is None


class _Client:
    is_closed = False

    def __init__(self, calls: list[tuple[str, str]], **kwargs):
        self.calls = calls
        self.kwargs = kwargs
        self.cookies = dict(kwargs.get("cookies") or {})

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url))
        if url.endswith("/sec/rotate_xsrf"):
            self.cookies["xsrf-token"] = "rotated-xsrf"
            return _Response(200, {"ok": 1})
        if url.endswith("/user_data"):
            return _Response(200, {"email": "owner@example.com", "money_total": "98.76"})
        if url.endswith("/money"):
            return _Response(200, {"money_balance": "12.34", "money_total": "98.76"})
        if url.endswith("/devices"):
            return _Response(
                200,
                {
                    "devices": [
                        {
                            "device_id": "device-a",
                            "node": {"ip": "198.51.100.1"},
                            "share": {"rate": "0.25"},
                            "bandwidth": 1234,
                        },
                        {
                            "uuid": "device-b",
                            "ip": "198.51.100.2",
                            "rate": 0.5,
                            "bandwidth": 5678,
                        },
                    ]
                },
            )
        if url.endswith("/usage"):
            assert kwargs["params"]["step"] == "daily"
            return _Response(200, [])
        if url.endswith("/payment_methods"):
            return _Response(
                200,
                {
                    "paypal.com": {"value": "paypal.com", "min_redeem": 10, "percentage_fee": 2.0},
                    "wise.com": {"value": "wise.com", "min_redeem": 10, "fixed_fee": 0.5, "disabled": False},
                },
            )
        if url.endswith("/redeem_details"):
            return _Response(404, {"error": "not configured"})
        if url.endswith("/transactions"):
            return _Response(200, [])
        raise AssertionError(url)

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url))
        assert kwargs["headers"]["xsrf-token"] == "rotated-xsrf"
        assert kwargs["headers"]["Origin"] == "https://earnapp.com"
        assert kwargs["headers"]["Referer"] == "https://earnapp.com/dashboard/"
        assert kwargs["json"] == {"data": {"devices": ["device-a", "device-b"]}}
        return _Response(200, {"device-a": [1787700000, 60], "device-b": [0, 0]})

    async def aclose(self):
        self.is_closed = True


def test_collector_rotates_xsrf_routes_every_request_through_account_proxy_and_normalizes_snapshot():
    calls: list[tuple[str, str]] = []
    client_holder: list[_Client] = []

    def factory(**kwargs):
        client = _Client(calls, **kwargs)
        client_holder.append(client)
        return client

    credentials = {
        "cookies": {
            "auth": "1",
            "auth-method": "google",
            "oauth-refresh-token": "refresh-secret",
            "xsrf-token": "old-xsrf-secret",
        }
    }
    proxy = {
        "protocol": "socks5",
        "host": "proxy.example",
        "port": 1080,
        "username": "user",
        "password": "pass",
    }
    with patch("app.collectors.earnapp.httpx.AsyncClient", side_effect=factory):
        snapshot = asyncio.run(EarnAppAccountCollector(credentials, proxy).collect_snapshot())

    assert client_holder[0].kwargs["proxy"] == "socks5://user:pass@proxy.example:1080"
    assert client_holder[0].kwargs["cookies"]["oauth-refresh-token"] == "refresh-secret"
    assert calls == [
        ("GET", "https://earnapp.com/dashboard/api/sec/rotate_xsrf"),
        ("GET", "https://earnapp.com/dashboard/api/user_data"),
        ("GET", "https://earnapp.com/dashboard/api/money"),
        ("GET", "https://earnapp.com/dashboard/api/devices"),
        ("GET", "https://earnapp.com/dashboard/api/usage"),
        ("GET", "https://earnapp.com/dashboard/api/payment_methods"),
        ("GET", "https://earnapp.com/dashboard/api/redeem_details"),
        ("GET", "https://earnapp.com/dashboard/api/transactions"),
        ("POST", "https://earnapp.com/dashboard/api/device_statuses"),
    ]
    assert snapshot == {
        "status": "ok",
        "money_balance": 12.34,
        "money_total": 98.76,
        "online_nodes": 1,
        "offline_nodes": 1,
        "usage_current": 0,
        "usage_total": 0,
        "usage_available_nodes": 0,
        "usage_missing_nodes": 2,
        "payment": {
            "configured": False,
            "method": "",
            "destination_masked": "",
            "methods": [
                {
                    "id": "paypal.com",
                    "label": "paypal.com",
                    "minimum": 10.0,
                    "fee_fixed": None,
                    "fee_percent": 2.0,
                    "disabled": False,
                    "parent": "",
                },
                {
                    "id": "wise.com",
                    "label": "wise.com",
                    "minimum": 10.0,
                    "fee_fixed": 0.5,
                    "fee_percent": None,
                    "disabled": False,
                    "parent": "",
                },
            ],
            "transactions": [],
        },
        "devices": [
            {
                "device_id": "device-a",
                "ip": "198.51.100.1",
                "country_code": "",
                "rate": 0.25,
                "bandwidth": 1234.0,
                "total_bandwidth": None,
                "redeemed_bandwidth": None,
                "earned": None,
                "earned_total": None,
                "uptime": None,
                "total_uptime": None,
                "billing": "",
                "usage_total": None,
                "usage_current": None,
                "usage_points": 0,
                "usage_available": False,
                "online": True,
            },
            {
                "device_id": "device-b",
                "ip": "198.51.100.2",
                "country_code": "",
                "rate": 0.5,
                "bandwidth": 5678.0,
                "total_bandwidth": None,
                "redeemed_bandwidth": None,
                "earned": None,
                "earned_total": None,
                "uptime": None,
                "total_uptime": None,
                "billing": "",
                "usage_total": None,
                "usage_current": None,
                "usage_points": 0,
                "usage_available": False,
                "online": False,
            },
        ],
    }
    assert "refresh-secret" not in json.dumps(snapshot)
    assert "old-xsrf-secret" not in json.dumps(snapshot)


class _PaymentClient:
    is_closed = False

    def __init__(self, calls, **kwargs):
        self.calls = calls
        self.cookies = dict(kwargs.get("cookies") or {})

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, None))
        if url.endswith("/sec/rotate_xsrf"):
            self.cookies["xsrf-token"] = "rotated-xsrf"
            return _Response(200, {"ok": 1})
        if url.endswith("/payment_methods"):
            return _Response(200, {"paypal.com": {"value": "paypal.com", "min_redeem": 10}})
        if url.endswith("/redeem_details"):
            return _Response(200, {"payment_method": "paypal.com", "email": "owner@example.com"})
        if url.endswith("/transactions"):
            return _Response(200, [])
        raise AssertionError(url)

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs.get("json")))
        return _Response(200, {"ok": 1})

    async def delete(self, url, **kwargs):
        self.calls.append(("DELETE", url, None))
        return _Response(200, {"ok": 1})

    async def aclose(self):
        self.is_closed = True


class _RejectedPaymentMethodClient(_PaymentClient):
    async def get(self, url, **kwargs):
        if url.endswith("/payment_methods"):
            self.calls.append(("GET", url, None))
            return _Response(
                200,
                {
                    "paypal.com": {"value": "paypal.com", "disabled": False},
                    "wise.com": {"value": "wise.com", "disabled": True},
                },
            )
        return await super().get(url, **kwargs)


@pytest.mark.parametrize("payment_method", ["wise.com", "unknown.example"])
def test_payment_configuration_rejects_disabled_or_unknown_method_before_mutation(payment_method):
    calls = []
    credentials = {"cookies": {"oauth-refresh-token": "refresh-secret", "xsrf-token": "old-xsrf-secret"}}
    proxy = {"protocol": "socks5", "host": "proxy.example", "port": 1080}
    with patch(
        "app.collectors.earnapp.httpx.AsyncClient",
        side_effect=lambda **kwargs: _RejectedPaymentMethodClient(calls, **kwargs),
    ):
        collector = EarnAppAccountCollector(credentials, proxy)
        with pytest.raises(ValueError, match="payment method is unavailable"):
            asyncio.run(collector.configure_payment(payment_method=payment_method, destination="owner@example.com"))

    assert not any(method == "POST" for method, _url, _body in calls)


def test_payment_configuration_uses_account_proxy_and_never_returns_raw_destination():
    calls = []
    credentials = {"cookies": {"oauth-refresh-token": "refresh-secret", "xsrf-token": "old-xsrf-secret"}}
    proxy = {"protocol": "socks5", "host": "proxy.example", "port": 1080}
    with patch(
        "app.collectors.earnapp.httpx.AsyncClient", side_effect=lambda **kwargs: _PaymentClient(calls, **kwargs)
    ):
        collector = EarnAppAccountCollector(credentials, proxy)
        configured = asyncio.run(
            collector.configure_payment(payment_method="paypal.com", destination="owner@example.com")
        )
        disabled = asyncio.run(collector.disable_payment())

    assert (
        "POST",
        "https://earnapp.com/dashboard/api/redeem_details",
        {"to": "owner@example.com", "payment_method": "paypal.com"},
    ) in calls
    assert ("DELETE", "https://earnapp.com/dashboard/api/redeem_details", None) in calls
    assert configured["configured"] is True
    assert configured["destination_masked"] == "o***@example.com"
    assert disabled["configured"] is False
    assert "owner@example.com" not in json.dumps(configured)
    assert "refresh-secret" not in json.dumps(configured)


class _LinkClient:
    is_closed = False

    def __init__(self, calls: list[tuple[str, str]], **kwargs):
        self.calls = calls
        self.kwargs = kwargs
        self.cookies = dict(kwargs.get("cookies") or {})
        self.linked = False
        self.link_headers: dict[str, str] = {}
        self.link_payload: dict[str, str] = {}

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url))
        if url.endswith("/sec/rotate_xsrf"):
            self.cookies["xsrf-token"] = "rotated-xsrf"
            return _Response(200, {"ok": 1})
        if url.endswith("/user_data"):
            return _Response(200, {"email": "owner@example.com"})
        if url.endswith("/devices"):
            devices = [{"uuid": "sdk-mac-test", "banned": False}] if self.linked else []
            return _Response(200, {"devices": devices})
        if url.endswith("/usage"):
            assert kwargs["params"]["step"] == "daily"
            return _Response(200, [])
        raise AssertionError(url)

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url))
        assert kwargs["headers"]["xsrf-token"] == "rotated-xsrf"
        assert kwargs["headers"]["Origin"] == "https://earnapp.com"
        if url.endswith("/link_device"):
            self.link_headers = dict(kwargs["headers"])
            self.link_payload = dict(kwargs["json"])
            self.linked = True
            return _Response(200, {"status": "ok"})
        if url.endswith("/device_statuses"):
            assert kwargs["json"] == {"data": {"devices": ["sdk-mac-test"]}}
            return _Response(200, {"sdk-mac-test": [1787700000, 120]})
        raise AssertionError(url)

    async def aclose(self):
        self.is_closed = True


class _LinkErrorClient(_LinkClient):
    async def post(self, url, **kwargs):
        if url.endswith("/link_device"):
            self.calls.append(("POST", url))
            return _Response(200, {"error": "The device is not found"})
        return await super().post(url, **kwargs)


class _AlreadyPresentLinkClient(_LinkClient):
    def __init__(self, calls: list[tuple[str, str]], **kwargs):
        super().__init__(calls, **kwargs)
        self.linked = True

    async def post(self, url, **kwargs):
        if url.endswith("/link_device"):
            self.calls.append(("POST", url))
            self.link_headers = dict(kwargs["headers"])
            self.link_payload = dict(kwargs["json"])
            return _Response(200, {"error": "This device was already linked"})
        return await super().post(url, **kwargs)


class _AlreadyLinkedButMissingClient(_AlreadyPresentLinkClient):
    async def post(self, url, **kwargs):
        response = await super().post(url, **kwargs)
        if url.endswith("/link_device"):
            self.linked = False
        return response


def test_link_and_verify_device_uses_account_proxy_and_requires_dashboard_online_evidence():
    calls: list[tuple[str, str]] = []
    clients: list[_LinkClient] = []

    def factory(**kwargs):
        client = _LinkClient(calls, **kwargs)
        clients.append(client)
        return client

    credentials = {
        "cookies": {
            "oauth-refresh-token": "refresh-secret",
            "xsrf-token": "old-xsrf-secret",
        }
    }
    proxy = {
        "protocol": "socks5",
        "host": "proxy.example",
        "port": 1080,
        "username": "user",
        "password": "pass",
    }
    with patch("app.collectors.earnapp.httpx.AsyncClient", side_effect=factory):
        result = asyncio.run(
            EarnAppAccountCollector(credentials, proxy).link_and_verify_device(
                "sdk-mac-test",
                platform="macos",
            )
        )

    assert clients[0].kwargs["proxy"] == "socks5://user:pass@proxy.example:1080"
    assert clients[0].link_headers["Referer"] == "https://earnapp.com/dashboard/link/sdk-mac-test"
    assert clients[0].link_headers["csrf-token"] == "rotated-xsrf"
    assert clients[0].link_headers["x-csrf-token"] == "rotated-xsrf"
    assert clients[0].link_headers["x-xsrf-token"] == "rotated-xsrf"
    assert clients[0].link_payload == {
        "uuid": "sdk-mac-test",
        "platform": "macos",
        "_csrf": "rotated-xsrf",
    }
    assert calls == [
        ("GET", "https://earnapp.com/dashboard/api/sec/rotate_xsrf"),
        ("GET", "https://earnapp.com/dashboard/api/user_data"),
        ("GET", "https://earnapp.com/dashboard/api/devices"),
        ("POST", "https://earnapp.com/dashboard/api/link_device"),
        ("GET", "https://earnapp.com/dashboard/api/devices"),
        ("POST", "https://earnapp.com/dashboard/api/device_statuses"),
        ("GET", "https://earnapp.com/dashboard/api/usage"),
    ]
    assert {
        key: result[key]
        for key in (
            "status",
            "device_id",
            "authenticated",
            "link_attempted",
            "device_present",
            "online",
            "banned",
        )
    } == {
        "status": "online",
        "device_id": "sdk-mac-test",
        "authenticated": True,
        "link_attempted": True,
        "device_present": True,
        "online": True,
        "banned": False,
    }
    assert "refresh-secret" not in json.dumps(result)
    assert "rotated-xsrf" not in json.dumps(result)


def test_link_and_verify_device_links_an_install_registered_device_before_accepting_already_linked():
    calls: list[tuple[str, str]] = []
    clients: list[_AlreadyPresentLinkClient] = []

    def factory(**kwargs):
        client = _AlreadyPresentLinkClient(calls, **kwargs)
        clients.append(client)
        return client

    credentials = {
        "cookies": {
            "oauth-refresh-token": "refresh-secret",
            "xsrf-token": "old-xsrf-secret",
        }
    }
    proxy = {"protocol": "socks5", "host": "proxy.example", "port": 1080}
    with patch("app.collectors.earnapp.httpx.AsyncClient", side_effect=factory):
        result = asyncio.run(
            EarnAppAccountCollector(credentials, proxy).link_and_verify_device(
                "sdk-mac-test",
                platform="ubuntu",
            )
        )

    assert clients[0].link_payload == {
        "uuid": "sdk-mac-test",
        "platform": "linux",
        "_csrf": "rotated-xsrf",
    }
    assert calls == [
        ("GET", "https://earnapp.com/dashboard/api/sec/rotate_xsrf"),
        ("GET", "https://earnapp.com/dashboard/api/user_data"),
        ("GET", "https://earnapp.com/dashboard/api/devices"),
        ("POST", "https://earnapp.com/dashboard/api/link_device"),
        ("GET", "https://earnapp.com/dashboard/api/devices"),
        ("POST", "https://earnapp.com/dashboard/api/device_statuses"),
        ("GET", "https://earnapp.com/dashboard/api/usage"),
    ]
    assert {
        key: result[key]
        for key in (
            "status",
            "device_id",
            "authenticated",
            "link_attempted",
            "device_present",
            "online",
            "banned",
        )
    } == {
        "status": "online",
        "device_id": "sdk-mac-test",
        "authenticated": True,
        "link_attempted": True,
        "device_present": True,
        "online": True,
        "banned": False,
    }
    assert "refresh-secret" not in json.dumps(result)
    assert "rotated-xsrf" not in json.dumps(result)
    assert "already linked" not in json.dumps(result).lower()


def test_link_and_verify_device_rejects_already_linked_when_authenticated_refetch_loses_uuid():
    calls: list[tuple[str, str]] = []

    def factory(**kwargs):
        return _AlreadyLinkedButMissingClient(calls, **kwargs)

    credentials = {
        "cookies": {
            "oauth-refresh-token": "refresh-secret",
            "xsrf-token": "old-xsrf-secret",
        }
    }
    proxy = {"protocol": "socks5", "host": "proxy.example", "port": 1080}
    with patch("app.collectors.earnapp.httpx.AsyncClient", side_effect=factory):
        result = asyncio.run(EarnAppAccountCollector(credentials, proxy).link_and_verify_device("sdk-mac-test"))

    assert calls == [
        ("GET", "https://earnapp.com/dashboard/api/sec/rotate_xsrf"),
        ("GET", "https://earnapp.com/dashboard/api/user_data"),
        ("GET", "https://earnapp.com/dashboard/api/devices"),
        ("POST", "https://earnapp.com/dashboard/api/link_device"),
        ("GET", "https://earnapp.com/dashboard/api/devices"),
    ]
    assert result == {
        "status": "error",
        "error_kind": "remote",
        "error": "EarnApp rejected device link",
        "device_id": "sdk-mac-test",
        "authenticated": True,
        "link_attempted": True,
        "device_present": False,
        "online": False,
        "banned": False,
    }
    assert "refresh-secret" not in json.dumps(result)
    assert "rotated-xsrf" not in json.dumps(result)
    assert "already linked" not in json.dumps(result).lower()


def test_link_and_verify_device_maps_internal_ubuntu_platform_to_earnapp_linux_wire_contract():
    calls: list[tuple[str, str]] = []
    clients: list[_LinkClient] = []

    def factory(**kwargs):
        client = _LinkClient(calls, **kwargs)
        clients.append(client)
        return client

    credentials = {"cookies": {"oauth-refresh-token": "refresh-secret", "xsrf-token": "old-xsrf-secret"}}
    proxy = {"protocol": "socks5", "host": "proxy.example", "port": 1080}
    with patch("app.collectors.earnapp.httpx.AsyncClient", side_effect=factory):
        result = asyncio.run(
            EarnAppAccountCollector(credentials, proxy).link_and_verify_device(
                "sdk-mac-test",
                platform="ubuntu",
            )
        )

    assert result["status"] == "online"
    assert clients[0].link_payload == {
        "uuid": "sdk-mac-test",
        "platform": "linux",
        "_csrf": "rotated-xsrf",
    }


def test_link_and_verify_device_reports_http_200_api_error_instead_of_pending():
    calls: list[tuple[str, str]] = []

    def factory(**kwargs):
        return _LinkErrorClient(calls, **kwargs)

    credentials = {"cookies": {"oauth-refresh-token": "refresh-secret", "xsrf-token": "old-xsrf-secret"}}
    proxy = {"protocol": "socks5", "host": "proxy.example", "port": 1080}
    with patch("app.collectors.earnapp.httpx.AsyncClient", side_effect=factory):
        result = asyncio.run(EarnAppAccountCollector(credentials, proxy).link_and_verify_device("sdk-mac-test"))

    assert result == {
        "status": "error",
        "error_kind": "remote",
        "error": "EarnApp rejected device link",
        "device_id": "sdk-mac-test",
        "authenticated": True,
        "link_attempted": True,
        "device_present": False,
        "online": False,
        "banned": False,
    }
    assert "The device is not found" not in json.dumps(result)


def test_collection_persists_sanitized_snapshot_without_registering_legacy_singleton_collector(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account_id = await earnapp_accounts.import_account(_account())
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            await _seed_proxy(provider_id, 1)
            snapshot = {
                "status": "ok",
                "money_balance": 1.5,
                "money_total": 9.5,
                "online_nodes": 1,
                "offline_nodes": 0,
                "devices": [{"device_id": "a", "online": True}],
            }
            with patch.object(EarnAppAccountCollector, "collect_snapshot", return_value=snapshot):
                result = await earnapp_collection.collect_account(account_id)
            assert result == snapshot
            latest = await database.get_latest_earnapp_snapshot(account_id)
            assert latest is not None
            assert latest["money_balance"] == 1.5
            assert latest["online_nodes"] == 1
            assert json.loads(latest["devices_json"]) == [{"device_id": "a", "online": True}]
            assert "credentials" not in json.dumps(latest)

    asyncio.run(run())
    assert "earnapp" not in COLLECTOR_MAP


def test_auth_failure_marks_account_but_proxy_route_failure_does_not(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account_id = await earnapp_accounts.import_account(_account())
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            await _seed_proxy(provider_id, 1)

            with patch.object(
                EarnAppAccountCollector,
                "collect_snapshot",
                return_value={"status": "error", "error_kind": "auth", "error": "authentication rejected"},
            ):
                auth_result = await earnapp_collection.collect_account(account_id)
            assert auth_result["error_kind"] == "auth"
            assert (await earnapp_accounts.list_accounts())[0]["state"] == "AUTH_FAILED"

            assert await database.set_earnapp_account_state(account_id, "ACTIVE")
            with patch.object(
                EarnAppAccountCollector,
                "collect_snapshot",
                return_value={"status": "error", "error_kind": "route", "error": "proxy unavailable"},
            ):
                route_result = await earnapp_collection.collect_account(account_id)
            assert route_result["error_kind"] == "route"
            assert (await earnapp_accounts.list_accounts())[0]["state"] == "ACTIVE"

    asyncio.run(run())


def test_collect_account_fails_over_to_another_account_node_route_on_route_error():
    account = {"credentials": {"cookies": {"oauth-refresh-token": "secret"}}}
    routes = [
        {"logical_node_id": "node-a", "proxy_id": 101, "exit_ip": "198.51.100.1"},
        {"logical_node_id": "node-b", "proxy_id": 102, "exit_ip": "198.51.100.2"},
    ]
    calls: list[int] = []

    class FakeCollector:
        def __init__(self, _credentials, route):
            self.proxy_id = int(route["proxy_id"])

        async def collect_snapshot(self):
            calls.append(self.proxy_id)
            if self.proxy_id == 101:
                return {"status": "error", "error_kind": "route", "error": "EarnApp route unavailable"}
            return {"status": "ok", "online_nodes": 1, "devices": []}

    async def run():
        with (
            patch.object(database, "get_earnapp_account_credentials", AsyncMock(return_value=account)),
            patch.object(earnapp_collection, "_collection_routes", AsyncMock(return_value=routes)),
            patch.object(earnapp_collection, "EarnAppAccountCollector", FakeCollector),
            patch.object(database, "save_earnapp_snapshot", AsyncMock()) as save_snapshot,
        ):
            result = await earnapp_collection.collect_account(7)

        assert result["status"] == "ok"
        assert calls == [101, 102]
        save_snapshot.assert_awaited_once_with(7, result)

    asyncio.run(run())


def test_collect_active_accounts_isolates_failures_and_skips_locked_accounts(monkeypatch):
    accounts = [
        {"id": 1, "state": "ACTIVE"},
        {"id": 2, "state": "AUTH_FAILED"},
        {"id": 3, "state": "ACCOUNT_LOCKED"},
        {"id": 4, "state": "DELETED"},
    ]

    async def collect(account_id):
        if account_id == 1:
            raise RuntimeError("refresh-secret must never escape")
        return {"status": "error", "error_kind": "auth", "error": "authentication rejected"}

    with (
        patch.object(database, "list_earnapp_accounts", return_value=accounts),
        patch.object(earnapp_collection, "collect_account", side_effect=collect),
    ):
        result = asyncio.run(earnapp_collection.collect_active_accounts())

    assert result == {
        "attempted": 2,
        "succeeded": 0,
        "failed": 2,
        "accounts": [
            {"account_id": 1, "status": "error", "error_kind": "internal"},
            {"account_id": 2, "status": "error", "error_kind": "auth"},
        ],
    }
    assert "refresh-secret" not in json.dumps(result)


def test_account_route_status_reports_exact_account_proxy_without_credentials(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account_id = await earnapp_accounts.import_account(_account())
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            proxy_id = await _seed_proxy(provider_id, 1)
            route = await earnapp_collection.ensure_collection_route(account_id)
            assert route is not None and route["proxy_id"] == proxy_id

            status = await earnapp_collection.account_route_status(account_id)
            assert status == {
                "status": "healthy",
                "source": "account_control",
                "proxy_id": proxy_id,
                "egress_ip": "198.51.100.1",
                "country_code": "VN",
                "checked_at": None,
            }
            assert "pass-1" not in json.dumps(status)
            assert "user-1" not in json.dumps(status)

    asyncio.run(run())


def test_scheduled_earnapp_failure_does_not_discard_normal_collector_results():
    async def run():
        collector = type("Collector", (), {"platform": "earnfm"})()
        result = EarningsResult(platform="earnfm", balance=2.5, currency="USD")
        upsert = AsyncMock()

        with (
            patch.object(main, "_collection_deployments", AsyncMock(return_value=[])),
            patch.object(main.database, "get_config", AsyncMock(return_value={})),
            patch("app.collectors.make_collectors", return_value=[collector]),
            patch("app.collectors._close_stale", AsyncMock()),
            patch.object(main, "_collect_with_collector", AsyncMock(return_value=(collector, result))),
            patch.object(
                earnapp_collection,
                "collect_active_accounts",
                AsyncMock(side_effect=RuntimeError("refresh-secret must never escape")),
            ) as collect_earnapp,
            patch.object(main.database, "upsert_earnings", upsert),
            patch.object(main, "_detect_payout", AsyncMock(return_value=None)),
            patch.object(main, "_pending_payout_alerts", AsyncMock(return_value=[])),
            patch.object(main, "_flatline_check", AsyncMock(return_value=[])),
            patch.object(main.metrics, "record_collection_start", return_value=1.0),
            patch.object(main.metrics, "record_collection_end"),
            patch.object(main.exchange_rates, "to_usd", return_value=1.0),
            patch.object(main.catalog, "get_service", return_value=None),
        ):
            await main._run_collection()

        collect_earnapp.assert_awaited_once_with()
        upsert.assert_awaited_once_with(platform="earnfm", balance=2.5, currency="USD", fx_rate_usd=1.0)

    asyncio.run(run())


def test_scheduled_earnapp_partial_failure_marks_run_failed_and_surfaces_one_sanitized_alert():
    async def run():
        previous_alerts = main._collector_alerts
        main._collector_alerts = []
        record_alert = AsyncMock(return_value=False)
        try:
            with (
                patch.object(main, "_collection_deployments", AsyncMock(return_value=[])),
                patch.object(main.database, "get_config", AsyncMock(return_value={})),
                patch("app.collectors.make_collectors", return_value=[]),
                patch("app.collectors._close_stale", AsyncMock()),
                patch.object(
                    earnapp_collection,
                    "collect_active_accounts",
                    AsyncMock(
                        return_value={
                            "attempted": 2,
                            "succeeded": 1,
                            "failed": 1,
                            "accounts": [
                                {"account_id": 1, "status": "ok"},
                                {"account_id": 2, "status": "error", "error_kind": "auth"},
                            ],
                        }
                    ),
                ),
                patch.object(main.database, "record_alert", record_alert),
                patch.object(main, "_pending_payout_alerts", AsyncMock(return_value=[])),
                patch.object(main, "_flatline_check", AsyncMock(return_value=[])),
                patch.object(main.metrics, "record_collection_start", return_value=1.0),
                patch.object(main.metrics, "record_collection_end") as record_end,
            ):
                await main._run_collection()

            message = "1 of 2 EarnApp account collections failed"
            record_alert.assert_awaited_once_with("collector", "earnapp", message, category="auth")
            assert main._collector_alerts == [
                {"kind": "collector", "platform": "earnapp", "error": message, "category": "auth"}
            ]
            record_end.assert_called_once_with(1.0, False, 0)
        finally:
            main._collector_alerts = previous_alerts

    asyncio.run(run())


def test_scheduled_earnapp_recovery_clears_the_durable_account_alert():
    async def run():
        previous_alerts = main._collector_alerts
        main._collector_alerts = [
            {
                "kind": "collector",
                "platform": "earnapp",
                "error": "1 of 1 EarnApp account collections failed",
                "category": "route",
            }
        ]
        clear_alerts = AsyncMock()
        try:
            with (
                patch.object(main, "_collection_deployments", AsyncMock(return_value=[])),
                patch.object(main.database, "get_config", AsyncMock(return_value={})),
                patch("app.collectors.make_collectors", return_value=[]),
                patch("app.collectors._close_stale", AsyncMock()),
                patch.object(
                    earnapp_collection,
                    "collect_active_accounts",
                    AsyncMock(
                        return_value={
                            "attempted": 1,
                            "succeeded": 1,
                            "failed": 0,
                            "accounts": [{"account_id": 1, "status": "ok"}],
                        }
                    ),
                ),
                patch.object(main.database, "clear_alerts", clear_alerts),
                patch.object(main, "_pending_payout_alerts", AsyncMock(return_value=[])),
                patch.object(main, "_flatline_check", AsyncMock(return_value=[])),
                patch.object(main.metrics, "record_collection_start", return_value=1.0),
                patch.object(main.metrics, "record_collection_end"),
            ):
                await main._run_collection()

            clear_alerts.assert_awaited_once_with("collector", "earnapp")
            assert main._collector_alerts == []
        finally:
            main._collector_alerts = previous_alerts

    asyncio.run(run())
