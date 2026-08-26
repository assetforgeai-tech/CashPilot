from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import httpx

from app import database, earnapp_accounts, earnapp_collection, earnapp_recovery
from app.collectors import COLLECTOR_MAP
from app.collectors.earnapp import EarnAppAccountCollector, build_proxy_url


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


async def _seed_proxy(provider_id: int, suffix: int, *, status: str = "alive", ip_type: str = "residential") -> int:
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
            }
        ],
    )
    await database.update_proxy_endpoint_intelligence(
        proxy_id,
        {"ip_type": ip_type, "ip_type_source": "test", "ip_type_confidence": "high"},
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
        ("POST", "https://earnapp.com/dashboard/api/device_statuses"),
    ]
    assert snapshot == {
        "status": "ok",
        "money_balance": 12.34,
        "money_total": 98.76,
        "online_nodes": 1,
        "offline_nodes": 1,
        "devices": [
            {
                "device_id": "device-a",
                "ip": "198.51.100.1",
                "rate": 0.25,
                "bandwidth": 1234.0,
                "online": True,
            },
            {
                "device_id": "device-b",
                "ip": "198.51.100.2",
                "rate": 0.5,
                "bandwidth": 5678.0,
                "online": False,
            },
        ],
    }
    assert "refresh-secret" not in json.dumps(snapshot)
    assert "old-xsrf-secret" not in json.dumps(snapshot)


class _LinkClient:
    is_closed = False

    def __init__(self, calls: list[tuple[str, str]], **kwargs):
        self.calls = calls
        self.kwargs = kwargs
        self.cookies = dict(kwargs.get("cookies") or {})
        self.linked = False

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
        raise AssertionError(url)

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url))
        assert kwargs["headers"]["xsrf-token"] == "rotated-xsrf"
        assert kwargs["headers"]["Origin"] == "https://earnapp.com"
        assert kwargs["headers"]["Referer"] == "https://earnapp.com/dashboard/"
        if url.endswith("/link_device"):
            assert kwargs["json"] == {
                "uuid": "sdk-mac-test",
                "platform": "macos",
            }
            self.linked = True
            return _Response(200, {"status": "ok"})
        if url.endswith("/device_statuses"):
            assert kwargs["json"] == {"data": {"devices": ["sdk-mac-test"]}}
            return _Response(200, {"sdk-mac-test": [1787700000, 120]})
        raise AssertionError(url)

    async def aclose(self):
        self.is_closed = True


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
    assert calls == [
        ("GET", "https://earnapp.com/dashboard/api/sec/rotate_xsrf"),
        ("GET", "https://earnapp.com/dashboard/api/user_data"),
        ("GET", "https://earnapp.com/dashboard/api/devices"),
        ("POST", "https://earnapp.com/dashboard/api/link_device"),
        ("GET", "https://earnapp.com/dashboard/api/devices"),
        ("POST", "https://earnapp.com/dashboard/api/device_statuses"),
    ]
    assert result == {
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
