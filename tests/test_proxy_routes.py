import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app import database, main
from app.main import app
from app.routers import proxies as proxy_routes


@asynccontextmanager
async def _noop_lifespan(_app):
    yield


app.router.lifespan_context = _noop_lifespan


def _owner_user():
    return {"uid": 1, "u": "admin", "r": "owner"}


def _viewer_user():
    return {"uid": 2, "u": "viewer", "r": "viewer"}


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_proxy_provider_pages_require_owner(client):
    with (
        patch("app.main.auth.get_current_user", return_value=_viewer_user()),
        patch("app.routers.pages.auth_module.get_current_user", return_value=_viewer_user()),
    ):
        assert client.get("/proxy-providers").status_code == 403
        assert client.get("/proxy-pool").status_code == 403
        assert client.get("/dashboard").status_code == 200


def test_dashboard_alias_routes_to_dashboard_page(client):
    with patch("app.main.auth.get_current_user", return_value=_owner_user()):
        resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "Dashboard" in resp.text


def test_proxy_provider_list_does_not_expose_secret(client):
    rows = [
        {
            "id": 1,
            "name": "vtproxy",
            "type": "vtproxy",
            "base_url": "https://vtproxy.net",
            "api_key_set": True,
            "enabled": 1,
        }
    ]
    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch("app.main.database.list_proxy_providers", new_callable=AsyncMock, return_value=rows),
    ):
        resp = client.get("/api/proxy-providers")
    assert resp.status_code == 200
    assert "secret-key" not in resp.text
    assert '"api_key":' not in resp.text


def test_proxy_provider_sync_is_owner_only(client):
    with patch("app.main.auth.get_current_user", return_value=_viewer_user()):
        resp = client.post("/api/proxy-providers/1/sync")
    assert resp.status_code == 403


def test_worker_proxy_assignment_sticks(client):
    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch("app.main.database.set_worker_proxy_assignment", new_callable=AsyncMock, return_value=True) as setter,
        patch("app.main.database.get_worker", new_callable=AsyncMock, return_value={"id": 7, "name": "w7"}),
        patch(
            "app.main.database.get_proxy_endpoint",
            new_callable=AsyncMock,
            return_value={"host": "proxy.example.com", "port": 8080, "protocol": "http"},
        ),
        patch("app.main._proxy_to_worker", new_callable=AsyncMock, return_value={"status": "ok"}) as apply,
    ):
        resp = client.post(
            "/api/workers/7/proxy-assignment",
            json={"proxy_id": 3, "mode": "proxy", "fallback": "hold"},
        )
    assert resp.status_code == 200
    assert setter.await_count == 1
    apply.assert_awaited_once()


def test_worker_proxy_lease_applies_to_worker(client):
    lease = {
        "worker_id": 7,
        "proxy_id": 3,
        "mode": "proxy",
        "host": "proxy.example.com",
        "port": 8080,
        "protocol": "http",
    }
    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch("app.main.database.lease_proxy_for_worker", new_callable=AsyncMock, return_value=lease) as lease_fn,
        patch("app.main.database.get_worker", new_callable=AsyncMock, return_value={"id": 7, "name": "w7"}),
        patch("app.main._proxy_to_worker", new_callable=AsyncMock, return_value={"status": "ok"}) as apply,
    ):
        resp = client.post("/api/workers/7/proxy-lease")
    assert resp.status_code == 200
    lease_fn.assert_awaited_once_with(7)
    apply.assert_awaited_once()


def test_worker_proxy_lease_uses_read_only_candidate_when_provider_is_running(client):
    lease = {
        "worker_id": 7,
        "proxy_id": 3,
        "host": "proxy.example.com",
        "port": 8080,
        "protocol": "socks5",
    }
    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch("app.routers.proxies._worker_has_proxy_instances", new_callable=AsyncMock, return_value=True),
        patch(
            "app.routers.proxies.database.find_available_proxy_for_worker",
            new_callable=AsyncMock,
            return_value=lease,
        ) as find,
        patch(
            "app.routers.proxies._rotate_worker_proxy_after_ack", new_callable=AsyncMock, return_value=True
        ) as rotate,
        patch("app.routers.proxies.database.lease_proxy_for_worker", new_callable=AsyncMock) as mutating_lease,
    ):
        resp = client.post("/api/workers/7/proxy-lease")

    assert resp.status_code == 200
    find.assert_awaited_once_with(7)
    rotate.assert_awaited_once_with(7, lease)
    mutating_lease.assert_not_awaited()


def test_worker_proxy_assignment_rejects_missing_proxy_before_active_rotation(client):
    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch("app.main.database.get_worker", new_callable=AsyncMock, return_value={"id": 7, "name": "w7"}),
        patch("app.main.database.get_proxy_endpoint", new_callable=AsyncMock, return_value=None),
        patch("app.routers.proxies._worker_has_proxy_instances", new_callable=AsyncMock, return_value=True),
        patch("app.routers.proxies._rotate_worker_proxy_after_ack", new_callable=AsyncMock) as rotate,
        patch("app.main.database.set_worker_proxy_assignment", new_callable=AsyncMock) as setter,
    ):
        resp = client.post(
            "/api/workers/7/proxy-assignment",
            json={"proxy_id": 99, "mode": "proxy", "fallback": "rotate"},
        )

    assert resp.status_code == 404
    rotate.assert_not_awaited()
    setter.assert_not_awaited()


def test_worker_proxy_assignment_fails_closed_for_direct_mode_with_active_proxy_instances(client):
    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch("app.main.database.get_worker", new_callable=AsyncMock, return_value={"id": 7, "name": "w7"}),
        patch("app.routers.proxies._worker_has_proxy_instances", new_callable=AsyncMock, return_value=True),
        patch("app.main.database.set_worker_proxy_assignment", new_callable=AsyncMock) as setter,
        patch("app.main._proxy_to_worker", new_callable=AsyncMock) as apply,
    ):
        resp = client.post(
            "/api/workers/7/proxy-assignment",
            json={"proxy_id": None, "mode": "direct", "fallback": "hold"},
        )

    assert resp.status_code == 409
    setter.assert_not_awaited()
    apply.assert_not_awaited()


def test_worker_proxy_assignment_passes_requested_fallback_to_active_rotation(client):
    proxy = {"id": 3, "host": "proxy.example.com", "port": 8080, "protocol": "http"}
    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch("app.main.database.get_worker", new_callable=AsyncMock, return_value={"id": 7, "name": "w7"}),
        patch("app.main.database.get_proxy_endpoint", new_callable=AsyncMock, return_value=proxy),
        patch("app.routers.proxies._worker_has_proxy_instances", new_callable=AsyncMock, return_value=True),
        patch(
            "app.routers.proxies._rotate_worker_proxy_after_ack", new_callable=AsyncMock, return_value=True
        ) as rotate,
    ):
        resp = client.post(
            "/api/workers/7/proxy-assignment",
            json={"proxy_id": 3, "mode": "proxy", "fallback": "hold"},
        )

    assert resp.status_code == 200
    rotate.assert_awaited_once_with(7, {**proxy, "proxy_id": 3}, fallback="hold")


@pytest.mark.asyncio
async def test_worker_proxy_instance_detection_ignores_failed_rows():
    rows = [
        {"instance_id": "earnfm-proxy", "mode": "proxy", "status": "failed"},
        {"instance_id": "proxybase-proxy", "mode": "proxy", "status": "running"},
    ]
    with patch("app.routers.proxies.database.list_provider_instances", new_callable=AsyncMock, return_value=rows):
        assert await proxy_routes._worker_has_proxy_instances(7) is True

    with patch(
        "app.routers.proxies.database.list_provider_instances",
        new_callable=AsyncMock,
        return_value=rows[:1],
    ):
        assert await proxy_routes._worker_has_proxy_instances(7) is False


def test_proxy_pool_export_and_recheck_are_owner_only_and_wired(client):
    rows = [
        {
            "id": 1,
            "provider_name": "vtproxy",
            "endpoint": "1.1.1.1:1000",
            "protocol": "socks5",
            "location": "sg",
            "status": "alive",
            "assigned_worker_id": None,
        }
    ]
    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch("app.routers.proxies.database.export_proxy_pool", new_callable=AsyncMock, return_value=rows),
    ):
        export = client.get("/api/proxy-pool/export?status=alive")
    assert export.status_code == 200
    assert "provider_name" in export.text
    assert "vtproxy" in export.text

    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch("app.routers.proxies.database.get_config", new_callable=AsyncMock, return_value={}),
        patch(
            "app.routers.proxies.run_proxy_pool_recheck",
            new_callable=AsyncMock,
            return_value={"checked": 3, "alive": 2, "dead": 1, "rotated": 1},
        ) as mark,
    ):
        recheck = client.post("/api/proxy-pool/recheck", json={"proxy_ids": [1, 2, 3], "concurrency": 4})
    assert recheck.status_code == 200
    assert recheck.json()["checked"] == 3
    mark.assert_awaited_once_with(proxy_ids=[1, 2, 3], concurrency=4)


@pytest.mark.asyncio
async def test_proxy_probe_requires_a_real_tunnel_not_just_handshake():
    calls = []

    class Reader:
        def __init__(self, stage: int):
            self.stage = stage
            self.socks_step = 0
            self.http_step = 0

        async def readexactly(self, n: int):
            if self.stage == 1:
                self.socks_step += 1
                if self.socks_step == 1:
                    return b"\x05\x00"
                if self.socks_step == 2:
                    return b"\x05\x00\x00\x01"
                if self.socks_step == 3:
                    return b"\x00\x00\x00\x00\x00\x00"
            return b""

        async def read(self, n: int):
            if self.stage == 2:
                self.http_step += 1
                if self.http_step == 1:
                    return b"HTTP/1.1 200 Connection established\r\n\r\n"
            return b""

    class Writer:
        def __init__(self, stage: int):
            self.stage = stage

        def write(self, data: bytes):
            calls.append((self.stage, data))

        async def drain(self):
            return None

        def close(self):
            return None

        async def wait_closed(self):
            return None

    async def fake_open_connection(host: str, port: int):
        calls.append((host, port))
        stage = len([item for item in calls if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str)])
        return Reader(stage), Writer(stage)

    async def passthrough(value, timeout=None):
        return await value

    with (
        patch("app.routers.proxies.asyncio.open_connection", side_effect=fake_open_connection),
        patch("app.routers.proxies.asyncio.wait_for", side_effect=passthrough),
    ):
        result = await proxy_routes._probe_proxy_confirmed("1.2.3.4", 1080, retries=1, retry_delay=0)

    assert result["status"] == "dead"
    assert len([item for item in calls if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str)]) >= 2


def test_proxy_pool_import_rechecks_only_imported_proxies(client):
    payload = "1.1.1.1:1000\n2.2.2.2:2000:user:pass\n"
    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch("app.routers.proxies.database.upsert_proxy_provider", new_callable=AsyncMock, return_value=9),
        patch(
            "app.routers.proxies.database.upsert_proxy_endpoints_returning_ids",
            new_callable=AsyncMock,
            return_value=[3, 4],
        ),
        patch("app.routers.proxies.database.create_proxy_import_batch", new_callable=AsyncMock),
        patch("app.routers.proxies.database.get_config", new_callable=AsyncMock, return_value={}),
        patch(
            "app.routers.proxies.run_proxy_pool_recheck",
            new_callable=AsyncMock,
            return_value={"checked": 2, "alive": 2, "dead": 0, "rotated": 0},
        ) as recheck,
    ):
        resp = client.post("/api/proxy-pool/import", json={"text": payload, "provider_name": "manual", "recheck": True})
    assert resp.status_code == 200
    recheck.assert_awaited_once_with(proxy_ids=[3, 4], concurrency=8)


def test_proxy_pool_import_supports_paste_payloads(client):
    payload = """1.1.1.1:1000
2.2.2.2:2000:user:pass
http://3.3.3.3:3000
socks5://user:pass@4.4.4.4:4000
"""
    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch("app.routers.proxies.database.upsert_proxy_provider", new_callable=AsyncMock, return_value=9),
        patch(
            "app.routers.proxies.database.upsert_proxy_endpoints_returning_ids",
            new_callable=AsyncMock,
            return_value=[1, 2, 3, 4],
        ) as upsert,
        patch("app.routers.proxies.database.create_proxy_import_batch", new_callable=AsyncMock),
        patch("app.routers.proxies.database.get_config", new_callable=AsyncMock, return_value={}),
        patch(
            "app.routers.proxies.run_proxy_pool_recheck",
            new_callable=AsyncMock,
            return_value={"checked": 4, "alive": 4, "dead": 0, "rotated": 0},
        ) as recheck,
    ):
        resp = client.post("/api/proxy-pool/import", json={"text": payload, "provider_name": "manual", "recheck": True})
    assert resp.status_code == 200
    assert resp.json()["imported"] == 4
    upsert.assert_awaited_once()
    recheck.assert_awaited_once()


def test_proxy_import_parser_retains_each_raw_line_only_for_encrypted_audit_storage():
    rows = proxy_routes._parse_proxy_import("proxy.example:1000:user:secret\n")

    assert rows == [
        {
            "host": "proxy.example",
            "port": 1000,
            "username": "user",
            "password": "secret",
            "protocol": "socks5",
            "location": "",
            "_raw_line": "proxy.example:1000:user:secret",
        }
    ]


def test_proxy_pool_import_reports_inserted_count_not_parse_count(client):
    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch("app.routers.proxies.database.upsert_proxy_provider", new_callable=AsyncMock, return_value=9),
        patch(
            "app.routers.proxies.database.upsert_proxy_endpoints_returning_ids",
            new_callable=AsyncMock,
            return_value=[1, 2],
        ),
        patch("app.routers.proxies.database.create_proxy_import_batch", new_callable=AsyncMock),
        patch("app.routers.proxies.database.get_config", new_callable=AsyncMock, return_value={}),
        patch(
            "app.routers.proxies.run_proxy_pool_recheck",
            new_callable=AsyncMock,
            return_value={"checked": 2, "alive": 2, "dead": 0, "rotated": 0},
        ),
    ):
        resp = client.post(
            "/api/proxy-pool/import",
            json={"text": "1.1.1.1:1000\n2.2.2.2:2000\n", "provider_name": "manual", "recheck": False},
        )
    assert resp.status_code == 200
    assert resp.json()["imported"] == 2


@pytest.mark.asyncio
async def test_proxy_pool_recheck_uses_decrypted_proxy_credentials():
    rows = [{"id": 7, "host": "proxy.example.com", "port": 1080, "assigned_worker_id": None}]
    proxy = {"id": 7, "host": "proxy.example.com", "port": 1080, "username": "user", "password": "pass"}

    with (
        patch("app.routers.proxies.database.list_proxy_pool", new_callable=AsyncMock, return_value=rows),
        patch("app.routers.proxies.database.get_proxy_endpoint", new_callable=AsyncMock, return_value=proxy) as lookup,
        patch("app.routers.proxies.database.update_proxy_pool_check_results", new_callable=AsyncMock, return_value=1),
        patch("app.routers.proxies.database.save_proxy_probe_result", new_callable=AsyncMock),
        patch("app.routers.proxies.database.reconcile_proxy_duplicates", new_callable=AsyncMock, return_value=0),
        patch(
            "app.routers.proxies._probe_proxy_confirmed",
            new_callable=AsyncMock,
            return_value={"status": "alive", "protocol": "socks5"},
        ) as probe,
    ):
        result = await proxy_routes.run_proxy_pool_recheck(proxy_ids=[7], concurrency=1)

    assert result["status"] == "ok"
    lookup.assert_awaited_once_with(7)
    probe.assert_awaited_once_with("proxy.example.com", 1080, username="user", password="pass")


@pytest.mark.asyncio
async def test_proxy_pool_recheck_persists_proxy_egress_ip():
    rows = [{"id": 7, "host": "proxy.example.com", "port": 1080, "assigned_worker_id": None}]
    proxy = {"id": 7, "host": "proxy.example.com", "port": 1080}

    with (
        patch("app.routers.proxies.database.list_proxy_pool", new_callable=AsyncMock, return_value=rows),
        patch("app.routers.proxies.database.get_proxy_endpoint", new_callable=AsyncMock, return_value=proxy),
        patch(
            "app.routers.proxies.database.update_proxy_pool_check_results", new_callable=AsyncMock, return_value=1
        ) as save,
        patch("app.routers.proxies.database.save_proxy_probe_result", new_callable=AsyncMock),
        patch("app.routers.proxies.database.get_cached_proxy_intelligence", new_callable=AsyncMock, return_value=None),
        patch("app.routers.proxies.lookup_ip_intelligence", new_callable=AsyncMock, return_value={}),
        patch("app.routers.proxies.database.update_proxy_endpoint_intelligence", new_callable=AsyncMock),
        patch("app.routers.proxies.database.reconcile_proxy_duplicates", new_callable=AsyncMock, return_value=0),
        patch(
            "app.routers.proxies._probe_proxy_confirmed",
            new_callable=AsyncMock,
            return_value={"status": "alive", "protocol": "socks5", "exit_ip": "8.8.8.8"},
        ),
    ):
        await proxy_routes.run_proxy_pool_recheck(proxy_ids=[7], concurrency=1)

    save.assert_awaited_once_with(
        {7: "alive"},
        protocols={7: "socks5"},
        exit_ips={7: "8.8.8.8"},
    )


@pytest.mark.asyncio
async def test_generic_recheck_refreshes_ip_intelligence_and_duplicate_groups():
    rows = [{"id": 7, "host": "proxy.example.com", "port": 1080, "assigned_worker_id": None}]
    proxy = {"id": 7, "host": "proxy.example.com", "port": 1080}
    intelligence = {
        "location": "Singapore",
        "country_code": "SG",
        "country_name": "Singapore",
        "ip_type": "residential",
    }

    with (
        patch("app.routers.proxies.database.list_proxy_pool", new_callable=AsyncMock, return_value=rows),
        patch("app.routers.proxies.database.get_proxy_endpoint", new_callable=AsyncMock, return_value=proxy),
        patch(
            "app.routers.proxies._probe_proxy_confirmed",
            new_callable=AsyncMock,
            return_value={"status": "alive", "protocol": "socks5", "exit_ip": "8.8.8.8"},
        ),
        patch("app.routers.proxies.database.update_proxy_pool_check_results", new_callable=AsyncMock, return_value=1),
        patch("app.routers.proxies.database.save_proxy_probe_result", new_callable=AsyncMock) as save_evidence,
        patch("app.routers.proxies.database.get_cached_proxy_intelligence", new_callable=AsyncMock, return_value=None),
        patch(
            "app.routers.proxies.lookup_ip_intelligence", new_callable=AsyncMock, return_value=intelligence
        ) as lookup,
        patch("app.routers.proxies.database.update_proxy_endpoint_intelligence", new_callable=AsyncMock) as save_geo,
        patch(
            "app.routers.proxies.database.reconcile_proxy_duplicates", new_callable=AsyncMock, return_value=2
        ) as dedupe,
    ):
        result = await proxy_routes.run_proxy_pool_recheck(proxy_ids=[7], concurrency=1)

    lookup.assert_awaited_once_with("8.8.8.8")
    save_geo.assert_awaited_once_with(7, intelligence)
    save_evidence.assert_awaited_once()
    dedupe.assert_awaited_once_with()
    assert result["duplicates_marked"] == 2


@pytest.mark.asyncio
async def test_generic_recheck_looks_up_shared_egress_intelligence_once():
    rows = [
        {"id": 7, "host": "one.example", "port": 1080, "assigned_worker_id": None},
        {"id": 8, "host": "two.example", "port": 1080, "assigned_worker_id": None},
    ]

    async def endpoint(proxy_id):
        return {**rows[proxy_id - 7], "protocol": "socks5"}

    with (
        patch("app.routers.proxies.database.list_proxy_pool", new_callable=AsyncMock, return_value=rows),
        patch("app.routers.proxies.database.get_proxy_endpoint", new_callable=AsyncMock, side_effect=endpoint),
        patch(
            "app.routers.proxies._probe_proxy_confirmed",
            new_callable=AsyncMock,
            return_value={"status": "alive", "protocol": "socks5", "exit_ip": "8.8.8.8"},
        ),
        patch("app.routers.proxies.database.update_proxy_pool_check_results", new_callable=AsyncMock, return_value=2),
        patch("app.routers.proxies.database.save_proxy_probe_result", new_callable=AsyncMock),
        patch("app.routers.proxies.database.get_cached_proxy_intelligence", new_callable=AsyncMock, return_value=None),
        patch(
            "app.routers.proxies.lookup_ip_intelligence", new_callable=AsyncMock, return_value={"country_code": "US"}
        ) as lookup,
        patch("app.routers.proxies.database.update_proxy_endpoint_intelligence", new_callable=AsyncMock) as save_geo,
        patch("app.routers.proxies.database.reconcile_proxy_duplicates", new_callable=AsyncMock, return_value=0),
    ):
        await proxy_routes.run_proxy_pool_recheck(concurrency=2)

    lookup.assert_awaited_once_with("8.8.8.8")
    assert save_geo.await_count == 2


@pytest.mark.asyncio
async def test_earnapp_recheck_persists_only_cid_set_as_eligible():
    rows = [
        {"id": 7, "host": "good.example", "port": 1080},
        {"id": 8, "host": "blocked.example", "port": 1080},
    ]
    proxies = {
        7: {**rows[0], "protocol": "socks5", "username": "u", "password": "p"},
        8: {**rows[1], "protocol": "http", "username": "u", "password": "p"},
    }

    async def lookup_proxy(proxy_id):
        return proxies[proxy_id]

    async def probe(host, port, **kwargs):
        if host == "good.example":
            return {
                "verdict": "CID_SET",
                "eligibility": "eligible",
                "reason": "cid",
                "exit_ip": "8.8.8.8",
                "latency_ms": 10,
                "probe_version": "test",
            }
        return {
            "verdict": "BLACKLIST",
            "eligibility": "blocked",
            "reason": "earnapp_blacklist",
            "exit_ip": "9.9.9.9",
            "latency_ms": 20,
            "probe_version": "test",
        }

    with (
        patch("app.routers.proxies.database.list_proxy_pool", new_callable=AsyncMock, return_value=rows),
        patch("app.routers.proxies.database.get_proxy_endpoint", new_callable=AsyncMock, side_effect=lookup_proxy),
        patch("app.routers.proxies.probe_earnapp_proxy", new_callable=AsyncMock, side_effect=probe),
        patch("app.routers.proxies.database.save_proxy_probe_result", new_callable=AsyncMock) as save,
        patch("app.routers.proxies.database.get_cached_proxy_intelligence", new_callable=AsyncMock, return_value=None),
        patch("app.routers.proxies.lookup_ip_intelligence", new_callable=AsyncMock, return_value={}),
        patch("app.routers.proxies.database.update_proxy_endpoint_intelligence", new_callable=AsyncMock),
        patch("app.routers.proxies.database.reconcile_proxy_duplicates", new_callable=AsyncMock, return_value=0),
    ):
        result = await proxy_routes.run_earnapp_proxy_recheck(concurrency=2)

    assert result["eligible"] == 1
    assert result["blocked"] == 1
    assert [call.kwargs["eligibility"] for call in save.await_args_list] == ["eligible", "blocked"]


@pytest.mark.asyncio
async def test_proxy_rotation_keeps_old_assignment_when_worker_rejects_candidate():
    old = {"worker_id": 7, "proxy_id": 1, "fallback": "rotate", "assignment_version": 4}
    candidate = {"id": 2, "proxy_id": 2, "host": "2.2.2.2", "port": 1080, "protocol": "socks5"}
    instances = [{"instance_id": "earnfm-proxy", "mode": "proxy", "proxy_id": 1}]

    with (
        patch("app.routers.proxies.database.get_worker_proxy_assignment", new_callable=AsyncMock, return_value=old),
        patch("app.routers.proxies.database.list_provider_instances", new_callable=AsyncMock, return_value=instances),
        patch("app.routers.proxies.database.commit_proxy_rotation", new_callable=AsyncMock) as commit,
        patch(
            "app.main._proxy_to_worker",
            new_callable=AsyncMock,
            side_effect=proxy_routes.HTTPException(status_code=409, detail="proxy unreachable"),
        ) as apply,
    ):
        ok = await proxy_routes._rotate_worker_proxy_after_ack(7, candidate)

    assert ok is False
    commit.assert_not_awaited()
    assert apply.await_count == 2
    payload = apply.await_args_list[0].kwargs["json"]
    assert payload["instances"] == ["earnfm-proxy"]
    assert payload["proxy"]["proxy_id"] == 2
    assert payload["binding_version"]
    rollback = apply.await_args_list[1].kwargs["json"]
    assert rollback["binding_version"] == payload["binding_version"]
    assert rollback["commit"] is False


@pytest.mark.asyncio
async def test_proxy_binding_finalize_rejects_partial_instance_ack():
    with patch(
        "app.main._proxy_to_worker",
        new_callable=AsyncMock,
        return_value={
            "ok": True,
            "binding_version": "rotation_1234567890",
            "action": "rolled_back",
            "finalized_instances": ["earnfm-proxy"],
        },
    ):
        assert (
            await proxy_routes._finalize_worker_proxy_binding(
                7,
                "rotation_1234567890",
                ["earnfm-proxy", "proxybase-proxy"],
                commit=False,
            )
            is False
        )


@pytest.mark.asyncio
async def test_proxy_rotation_attempts_runtime_rollback_when_apply_response_is_lost():
    old = {"worker_id": 7, "proxy_id": 1, "fallback": "rotate", "assignment_version": 4}
    candidate = {"id": 2, "proxy_id": 2, "host": "2.2.2.2", "port": 1080, "protocol": "socks5"}
    instances = [{"instance_id": "earnfm-proxy", "mode": "proxy", "proxy_id": 1}]
    calls = []

    async def worker_call(_worker_id, _method, path, *, json, timeout):
        calls.append((path, json))
        if path.endswith("/apply"):
            raise RuntimeError("response lost after sidecar restart")
        return {
            "ok": True,
            "binding_version": json["binding_version"],
            "action": "rolled_back",
            "finalized_instances": ["earnfm-proxy"],
        }

    with (
        patch("app.routers.proxies.database.get_worker_proxy_assignment", new_callable=AsyncMock, return_value=old),
        patch("app.routers.proxies.database.list_provider_instances", new_callable=AsyncMock, return_value=instances),
        patch("app.routers.proxies.database.commit_proxy_rotation", new_callable=AsyncMock) as commit,
        patch("app.main._proxy_to_worker", new=AsyncMock(side_effect=worker_call)),
    ):
        ok = await proxy_routes._rotate_worker_proxy_after_ack(7, candidate)

    assert ok is False
    commit.assert_not_awaited()
    assert [path for path, _json in calls] == [
        "/api/egress/bindings/apply",
        "/api/egress/bindings/finalize",
    ]
    assert calls[1][1]["commit"] is False


@pytest.mark.asyncio
async def test_proxy_rotation_attempts_runtime_rollback_when_worker_apply_returns_4xx():
    old = {"worker_id": 7, "proxy_id": 1, "fallback": "rotate", "assignment_version": 4}
    candidate = {"id": 2, "proxy_id": 2, "host": "2.2.2.2", "port": 1080, "protocol": "socks5"}
    instances = [{"instance_id": "earnfm-proxy", "mode": "proxy", "proxy_id": 1}]
    calls = []

    async def worker_call(_worker_id, _method, path, *, json, timeout):
        calls.append((path, json))
        if path.endswith("/apply"):
            raise proxy_routes.HTTPException(status_code=409, detail="ambiguous worker apply failure")
        return {
            "ok": True,
            "binding_version": json["binding_version"],
            "action": "rolled_back",
            "finalized_instances": ["earnfm-proxy"],
        }

    with (
        patch("app.routers.proxies.database.get_worker_proxy_assignment", new_callable=AsyncMock, return_value=old),
        patch("app.routers.proxies.database.list_provider_instances", new_callable=AsyncMock, return_value=instances),
        patch("app.routers.proxies.database.commit_proxy_rotation", new_callable=AsyncMock) as commit,
        patch("app.main._proxy_to_worker", new=AsyncMock(side_effect=worker_call)),
    ):
        ok = await proxy_routes._rotate_worker_proxy_after_ack(7, candidate)

    assert ok is False
    commit.assert_not_awaited()
    assert [path for path, _json in calls] == [
        "/api/egress/bindings/apply",
        "/api/egress/bindings/finalize",
    ]
    assert calls[1][1]["commit"] is False


@pytest.mark.asyncio
async def test_proxy_rotation_fails_closed_when_worker_instances_have_mixed_proxy_rows():
    old = {"worker_id": 7, "proxy_id": 1, "fallback": "rotate", "assignment_version": 4}
    candidate = {"id": 3, "proxy_id": 3, "host": "3.3.3.3", "port": 1080, "protocol": "socks5"}
    instances = [
        {"instance_id": "earnfm-proxy", "mode": "proxy", "proxy_id": 1},
        {"instance_id": "proxybase-proxy", "mode": "proxy", "proxy_id": 2},
    ]

    with (
        patch("app.routers.proxies.database.get_worker_proxy_assignment", new_callable=AsyncMock, return_value=old),
        patch("app.routers.proxies.database.list_provider_instances", new_callable=AsyncMock, return_value=instances),
        patch("app.main._proxy_to_worker", new_callable=AsyncMock) as worker_call,
        patch("app.routers.proxies.database.commit_proxy_rotation", new_callable=AsyncMock) as commit,
    ):
        ok = await proxy_routes._rotate_worker_proxy_after_ack(7, candidate)

    assert ok is False
    worker_call.assert_not_awaited()
    commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_proxy_rotation_ignores_failed_proxy_instance_rows():
    old = {"worker_id": 7, "proxy_id": 1, "fallback": "rotate", "assignment_version": 4}
    candidate = {"id": 2, "proxy_id": 2, "host": "2.2.2.2", "port": 1080, "protocol": "socks5"}
    instances = [
        {"instance_id": "stale-proxy", "mode": "proxy", "proxy_id": 9, "status": "failed"},
        {"instance_id": "earnfm-proxy", "mode": "proxy", "proxy_id": 1, "status": "running"},
    ]

    async def worker_call(_worker_id, _method, path, *, json, timeout):
        if path.endswith("/apply"):
            return {
                "ok": True,
                "binding_version": json["binding_version"],
                "proxy_id": 2,
                "observed_exit_ip": "8.8.8.8",
                "applied_instances": ["earnfm-proxy"],
            }
        return {
            "ok": True,
            "binding_version": json["binding_version"],
            "action": "confirmed",
            "finalized_instances": ["earnfm-proxy"],
        }

    with (
        patch("app.routers.proxies.database.get_worker_proxy_assignment", new_callable=AsyncMock, return_value=old),
        patch("app.routers.proxies.database.list_provider_instances", new_callable=AsyncMock, return_value=instances),
        patch(
            "app.routers.proxies.database.commit_proxy_rotation", new_callable=AsyncMock, return_value=True
        ) as commit,
        patch("app.main._proxy_to_worker", new=AsyncMock(side_effect=worker_call)),
    ):
        assert await proxy_routes._rotate_worker_proxy_after_ack(7, candidate) is True

    assert commit.await_args.kwargs["instance_ids"] == ["earnfm-proxy"]


@pytest.mark.asyncio
async def test_proxy_rotation_commits_candidate_only_after_matching_worker_ack():
    old = {"worker_id": 7, "proxy_id": 1, "fallback": "rotate", "assignment_version": 4}
    candidate = {"id": 2, "proxy_id": 2, "host": "2.2.2.2", "port": 1080, "protocol": "socks5"}
    instances = [{"instance_id": "earnfm-proxy", "mode": "proxy", "proxy_id": 1}]

    async def ack(_worker_id, _method, path, *, json, timeout):
        if path.endswith("/apply"):
            return {
                "ok": True,
                "binding_version": json["binding_version"],
                "proxy_id": 2,
                "observed_exit_ip": "8.8.8.8",
                "applied_instances": ["earnfm-proxy"],
            }
        assert path.endswith("/finalize")
        assert json["commit"] is True
        return {
            "ok": True,
            "binding_version": json["binding_version"],
            "action": "confirmed",
            "finalized_instances": ["earnfm-proxy"],
        }

    with (
        patch("app.routers.proxies.database.get_worker_proxy_assignment", new_callable=AsyncMock, return_value=old),
        patch("app.routers.proxies.database.list_provider_instances", new_callable=AsyncMock, return_value=instances),
        patch(
            "app.routers.proxies.database.commit_proxy_rotation",
            new_callable=AsyncMock,
            return_value=True,
        ) as commit,
        patch("app.main._proxy_to_worker", new=AsyncMock(side_effect=ack)) as worker_call,
    ):
        ok = await proxy_routes._rotate_worker_proxy_after_ack(7, candidate)

    assert ok is True
    commit.assert_awaited_once_with(
        7,
        expected_proxy_id=1,
        expected_assignment_version=4,
        new_proxy_id=2,
        instance_ids=["earnfm-proxy"],
        fallback="rotate",
    )
    assert worker_call.await_count == 2


@pytest.mark.asyncio
async def test_proxy_rotation_uses_explicit_fallback_override():
    old = {"worker_id": 7, "proxy_id": 1, "fallback": "rotate", "assignment_version": 4}
    candidate = {"id": 2, "proxy_id": 2, "host": "2.2.2.2", "port": 1080, "protocol": "socks5"}
    instances = [{"instance_id": "earnfm-proxy", "mode": "proxy", "proxy_id": 1}]

    async def worker_call(_worker_id, _method, path, *, json, timeout):
        if path.endswith("/apply"):
            return {
                "ok": True,
                "binding_version": json["binding_version"],
                "proxy_id": 2,
                "observed_exit_ip": "8.8.8.8",
                "applied_instances": ["earnfm-proxy"],
            }
        return {
            "ok": True,
            "binding_version": json["binding_version"],
            "action": "confirmed",
            "finalized_instances": ["earnfm-proxy"],
        }

    with (
        patch("app.routers.proxies.database.get_worker_proxy_assignment", new_callable=AsyncMock, return_value=old),
        patch("app.routers.proxies.database.list_provider_instances", new_callable=AsyncMock, return_value=instances),
        patch(
            "app.routers.proxies.database.commit_proxy_rotation", new_callable=AsyncMock, return_value=True
        ) as commit,
        patch("app.main._proxy_to_worker", new=AsyncMock(side_effect=worker_call)),
    ):
        assert await proxy_routes._rotate_worker_proxy_after_ack(7, candidate, fallback="hold") is True

    assert commit.await_args.kwargs["fallback"] == "hold"


@pytest.mark.asyncio
async def test_proxy_rotations_are_serialized_per_worker():
    old = {"worker_id": 7, "proxy_id": 1, "fallback": "rotate", "assignment_version": 4}
    instances = [{"instance_id": "earnfm-proxy", "mode": "proxy", "proxy_id": 1}]
    first_apply_started = asyncio.Event()
    release_first_apply = asyncio.Event()
    apply_calls = 0

    async def worker_call(_worker_id, _method, path, *, json, timeout):
        nonlocal apply_calls
        if path.endswith("/apply"):
            apply_calls += 1
            if apply_calls == 1:
                first_apply_started.set()
                await release_first_apply.wait()
            return {
                "ok": True,
                "binding_version": json["binding_version"],
                "proxy_id": int(json["proxy"]["proxy_id"]),
                "observed_exit_ip": "8.8.8.8",
                "applied_instances": ["earnfm-proxy"],
            }
        return {
            "ok": True,
            "binding_version": json["binding_version"],
            "action": "confirmed" if json["commit"] else "rolled_back",
            "finalized_instances": ["earnfm-proxy"],
        }

    proxy_routes._proxy_rotation_locks.clear()
    try:
        with (
            patch("app.routers.proxies.database.get_worker_proxy_assignment", new_callable=AsyncMock, return_value=old),
            patch(
                "app.routers.proxies.database.list_provider_instances", new_callable=AsyncMock, return_value=instances
            ),
            patch("app.routers.proxies.database.commit_proxy_rotation", new_callable=AsyncMock, return_value=True),
            patch("app.main._proxy_to_worker", new=AsyncMock(side_effect=worker_call)),
        ):
            first = asyncio.create_task(
                proxy_routes._rotate_worker_proxy_after_ack(
                    7, {"proxy_id": 2, "host": "2.2.2.2", "port": 1080, "protocol": "socks5"}
                )
            )
            await first_apply_started.wait()
            second = asyncio.create_task(
                proxy_routes._rotate_worker_proxy_after_ack(
                    7, {"proxy_id": 3, "host": "3.3.3.3", "port": 1080, "protocol": "socks5"}
                )
            )
            await asyncio.sleep(0)
            assert apply_calls == 1
            release_first_apply.set()
            assert await asyncio.gather(first, second) == [True, True]
    finally:
        proxy_routes._proxy_rotation_locks.clear()


@pytest.mark.asyncio
async def test_proxy_rotation_rolls_worker_back_when_database_cas_loses():
    old = {"worker_id": 7, "proxy_id": 1, "fallback": "rotate", "assignment_version": 4}
    candidate = {"id": 2, "proxy_id": 2, "host": "2.2.2.2", "port": 1080, "protocol": "socks5"}
    instances = [{"instance_id": "earnfm-proxy", "mode": "proxy", "proxy_id": 1}]
    calls = []

    async def worker_call(_worker_id, _method, path, *, json, timeout):
        calls.append((path, json))
        if path.endswith("/apply"):
            return {
                "ok": True,
                "binding_version": json["binding_version"],
                "proxy_id": 2,
                "observed_exit_ip": "8.8.8.8",
                "applied_instances": ["earnfm-proxy"],
            }
        return {
            "ok": True,
            "binding_version": json["binding_version"],
            "action": "rolled_back",
            "finalized_instances": ["earnfm-proxy"],
        }

    with (
        patch("app.routers.proxies.database.get_worker_proxy_assignment", new_callable=AsyncMock, return_value=old),
        patch("app.routers.proxies.database.list_provider_instances", new_callable=AsyncMock, return_value=instances),
        patch(
            "app.routers.proxies.database.commit_proxy_rotation", new_callable=AsyncMock, return_value=False
        ) as commit,
        patch("app.main._proxy_to_worker", new=AsyncMock(side_effect=worker_call)),
    ):
        ok = await proxy_routes._rotate_worker_proxy_after_ack(7, candidate)

    assert ok is False
    commit.assert_awaited_once()
    assert [path for path, _json in calls] == [
        "/api/egress/bindings/apply",
        "/api/egress/bindings/finalize",
    ]
    assert calls[1][1]["commit"] is False
    assert calls[1][1]["binding_version"] == calls[0][1]["binding_version"]


@pytest.mark.asyncio
async def test_proxy_rotation_refuses_ack_for_another_binding_version():
    old = {"worker_id": 7, "proxy_id": 1, "fallback": "rotate", "assignment_version": 4}
    candidate = {"id": 2, "proxy_id": 2, "host": "2.2.2.2", "port": 1080, "protocol": "socks5"}
    instances = [{"instance_id": "earnfm-proxy", "mode": "proxy", "proxy_id": 1}]

    with (
        patch("app.routers.proxies.database.get_worker_proxy_assignment", new_callable=AsyncMock, return_value=old),
        patch("app.routers.proxies.database.list_provider_instances", new_callable=AsyncMock, return_value=instances),
        patch("app.routers.proxies.database.commit_proxy_rotation", new_callable=AsyncMock) as commit,
        patch(
            "app.main._proxy_to_worker",
            new_callable=AsyncMock,
            return_value={
                "ok": True,
                "binding_version": "stale_12345678",
                "proxy_id": 2,
                "observed_exit_ip": "8.8.8.8",
                "applied_instances": ["earnfm-proxy"],
            },
        ),
    ):
        ok = await proxy_routes._rotate_worker_proxy_after_ack(7, candidate)

    assert ok is False
    commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_proxy_rotation_rolls_worker_back_when_ack_metadata_mismatches():
    old = {"worker_id": 7, "proxy_id": 1, "fallback": "rotate", "assignment_version": 4}
    candidate = {"id": 2, "proxy_id": 2, "host": "2.2.2.2", "port": 1080, "protocol": "socks5"}
    instances = [{"instance_id": "earnfm-proxy", "mode": "proxy", "proxy_id": 1}]
    calls = []

    async def worker_call(_worker_id, _method, path, *, json, timeout):
        calls.append((path, json))
        if path.endswith("/apply"):
            return {
                "ok": True,
                "binding_version": "unexpected-version",
                "proxy_id": 2,
                "observed_exit_ip": "8.8.8.8",
                "applied_instances": ["earnfm-proxy"],
            }
        return {
            "ok": True,
            "binding_version": json["binding_version"],
            "action": "rolled_back",
            "finalized_instances": ["earnfm-proxy"],
        }

    with (
        patch("app.routers.proxies.database.get_worker_proxy_assignment", new_callable=AsyncMock, return_value=old),
        patch("app.routers.proxies.database.list_provider_instances", new_callable=AsyncMock, return_value=instances),
        patch("app.routers.proxies.database.commit_proxy_rotation", new_callable=AsyncMock) as commit,
        patch("app.main._proxy_to_worker", new=AsyncMock(side_effect=worker_call)),
    ):
        ok = await proxy_routes._rotate_worker_proxy_after_ack(7, candidate)

    assert ok is False
    commit.assert_not_awaited()
    assert [path for path, _json in calls] == [
        "/api/egress/bindings/apply",
        "/api/egress/bindings/finalize",
    ]
    assert calls[1][1]["commit"] is False
    assert calls[1][1]["binding_version"] == calls[0][1]["binding_version"]


@pytest.mark.asyncio
async def test_proxy_rotation_keeps_committed_db_state_when_confirm_cleanup_is_unavailable():
    old = {"worker_id": 7, "proxy_id": 1, "fallback": "rotate", "assignment_version": 4}
    candidate = {"id": 2, "proxy_id": 2, "host": "2.2.2.2", "port": 1080, "protocol": "socks5"}
    instances = [{"instance_id": "earnfm-proxy", "mode": "proxy", "proxy_id": 1}]

    async def worker_call(_worker_id, _method, path, *, json, timeout):
        if path.endswith("/apply"):
            return {
                "ok": True,
                "binding_version": json["binding_version"],
                "proxy_id": 2,
                "observed_exit_ip": "8.8.8.8",
                "applied_instances": ["earnfm-proxy"],
            }
        raise proxy_routes.HTTPException(status_code=503, detail="worker unavailable")

    with (
        patch("app.routers.proxies.database.get_worker_proxy_assignment", new_callable=AsyncMock, return_value=old),
        patch("app.routers.proxies.database.list_provider_instances", new_callable=AsyncMock, return_value=instances),
        patch(
            "app.routers.proxies.database.commit_proxy_rotation", new_callable=AsyncMock, return_value=True
        ) as commit,
        patch("app.main._proxy_to_worker", new=AsyncMock(side_effect=worker_call)) as worker_call_mock,
    ):
        ok = await proxy_routes._rotate_worker_proxy_after_ack(7, candidate)

    assert ok is True
    commit.assert_awaited_once()
    assert worker_call_mock.await_count == 3  # apply plus one confirm retry


@pytest.mark.asyncio
async def test_proxy_rotation_refuses_worker_ack_with_unexpected_exit_ip():
    old = {"worker_id": 7, "proxy_id": 1, "fallback": "rotate", "assignment_version": 4}
    candidate = {
        "id": 2,
        "proxy_id": 2,
        "host": "2.2.2.2",
        "port": 1080,
        "protocol": "socks5",
        "exit_ip": "9.9.9.9",
    }
    instances = [{"instance_id": "earnfm-proxy", "mode": "proxy", "proxy_id": 1}]

    with (
        patch("app.routers.proxies.database.get_worker_proxy_assignment", new_callable=AsyncMock, return_value=old),
        patch("app.routers.proxies.database.list_provider_instances", new_callable=AsyncMock, return_value=instances),
        patch("app.routers.proxies.database.commit_proxy_rotation", new_callable=AsyncMock) as commit,
        patch(
            "app.main._proxy_to_worker",
            new_callable=AsyncMock,
            side_effect=lambda *_args, **kwargs: {
                "ok": True,
                "binding_version": kwargs["json"]["binding_version"],
                "proxy_id": 2,
                "observed_exit_ip": "8.8.8.8",
                "applied_instances": ["earnfm-proxy"],
            },
        ),
    ):
        ok = await proxy_routes._rotate_worker_proxy_after_ack(7, candidate)

    assert ok is False
    commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_proxy_pool_recheck_rotates_only_after_worker_ack():
    rows = [
        {"id": 1, "host": "1.1.1.1", "port": 1080, "assigned_worker_id": 7},
        {"id": 2, "host": "2.2.2.2", "port": 1080, "assigned_worker_id": None},
    ]

    async def endpoint(proxy_id: int):
        return {
            "id": proxy_id,
            "proxy_id": proxy_id,
            "host": f"{proxy_id}.{proxy_id}.{proxy_id}.{proxy_id}",
            "port": 1080,
            "protocol": "socks5",
        }

    async def probe(host: str, _port: int, **_kwargs):
        return {"status": "dead" if host == "1.1.1.1" else "alive", "protocol": "socks5"}

    with (
        patch("app.routers.proxies.database.list_proxy_pool", new_callable=AsyncMock, return_value=rows),
        patch("app.routers.proxies.database.get_proxy_endpoint", new_callable=AsyncMock, side_effect=endpoint),
        patch("app.routers.proxies.database.update_proxy_pool_check_results", new_callable=AsyncMock, return_value=2),
        patch("app.routers.proxies.database.save_proxy_probe_result", new_callable=AsyncMock),
        patch("app.routers.proxies.database.reconcile_proxy_duplicates", new_callable=AsyncMock, return_value=0),
        patch(
            "app.routers.proxies.database.find_available_proxy_for_worker",
            new_callable=AsyncMock,
            return_value={"proxy_id": 2, "host": "2.2.2.2", "port": 1080, "protocol": "socks5"},
        ) as available,
        patch("app.routers.proxies._probe_proxy_confirmed", new_callable=AsyncMock, side_effect=probe),
        patch(
            "app.routers.proxies._rotate_worker_proxy_after_ack", new_callable=AsyncMock, return_value=True
        ) as rotate,
        patch("app.routers.proxies.database.set_worker_proxy_assignment", new_callable=AsyncMock) as unsafe_commit,
        patch("app.routers.proxies._apply_proxy_to_worker", new_callable=AsyncMock) as legacy_apply,
    ):
        result = await proxy_routes.run_proxy_pool_recheck(concurrency=1)

    assert result["rotated"] == 1
    rotate.assert_awaited_once()
    assert int(rotate.await_args.args[0]) == 7
    assert int(rotate.await_args.args[1]["proxy_id"]) == 2
    available.assert_awaited_once_with(7)
    unsafe_commit.assert_not_awaited()
    legacy_apply.assert_not_awaited()


def test_proxy_rotation_commit_uses_assignment_version_and_updates_instances_atomically(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("vtproxy", "vtproxy")
            await database.upsert_proxy_endpoints(
                provider_id,
                [
                    {"provider_proxy_id": "a", "endpoint": "1.1.1.1:1000", "host": "1.1.1.1", "port": 1000},
                    {"provider_proxy_id": "b", "endpoint": "2.2.2.2:1000", "host": "2.2.2.2", "port": 1000},
                ],
            )
            worker = await database.upsert_worker("worker-a", "a", "http://a")
            await database.set_worker_proxy_assignment(worker, 1, "proxy", "rotate")
            await database.save_provider_instance(
                "earnfm",
                "earnfm-proxy",
                worker_id=worker,
                mode="proxy",
                proxy_id=1,
                status="running",
            )
            current = await database.get_worker_proxy_assignment(worker)
            assert current["assignment_version"] == 1

            stale = await database.commit_proxy_rotation(
                worker,
                expected_proxy_id=1,
                expected_assignment_version=0,
                new_proxy_id=2,
                instance_ids=["earnfm-proxy"],
                fallback="rotate",
            )
            assert stale is False
            assert (await database.get_worker_proxy_assignment(worker))["proxy_id"] == 1
            assert (await database.get_provider_instance("earnfm-proxy"))["proxy_id"] == 1

            committed = await database.commit_proxy_rotation(
                worker,
                expected_proxy_id=1,
                expected_assignment_version=1,
                new_proxy_id=2,
                instance_ids=["earnfm-proxy"],
                fallback="rotate",
            )
            assert committed is True
            assignment = await database.get_worker_proxy_assignment(worker)
            assert assignment["proxy_id"] == 2
            assert assignment["assignment_version"] == 2
            assert (await database.get_provider_instance("earnfm-proxy"))["proxy_id"] == 2

    import asyncio

    asyncio.run(run())


def test_proxy_assignment_clear_keeps_generation_for_lease_guard(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("vtproxy", "vtproxy")
            await database.upsert_proxy_endpoints(
                provider_id,
                [{"provider_proxy_id": "a", "endpoint": "1.1.1.1:1000", "host": "1.1.1.1", "port": 1000}],
            )
            worker = await database.upsert_worker("worker-a", "a", "http://a")
            await database.set_worker_proxy_assignment(worker, 1, "proxy", "rotate")
            before = await database.get_worker_proxy_assignment(worker)
            assert before["assignment_version"] == 1
            assert await database.clear_worker_proxy_assignment(worker)
            after = await database.get_worker_proxy_assignment(worker)
            assert after["proxy_id"] is None
            assert after["mode"] == "direct"
            assert after["assignment_version"] == 2

    import asyncio

    asyncio.run(run())


def test_proxy_rotation_commit_failure_does_not_leave_provider_instance_on_candidate(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("vtproxy", "vtproxy")
            await database.upsert_proxy_endpoints(
                provider_id,
                [
                    {"provider_proxy_id": "a", "endpoint": "1.1.1.1:1000", "host": "1.1.1.1", "port": 1000},
                    {"provider_proxy_id": "b", "endpoint": "2.2.2.2:1000", "host": "2.2.2.2", "port": 1000},
                ],
            )
            worker = await database.upsert_worker("worker-a", "a", "http://a")
            await database.set_worker_proxy_assignment(worker, 1, "proxy", "rotate")
            await database.save_provider_instance(
                "earnfm", "earnfm-proxy", worker_id=worker, mode="proxy", proxy_id=1, status="running"
            )
            assert not await database.commit_proxy_rotation(
                worker,
                expected_proxy_id=1,
                expected_assignment_version=99,
                new_proxy_id=2,
                instance_ids=["earnfm-proxy"],
            )
            assert (await database.get_worker_proxy_assignment(worker))["proxy_id"] == 1
            assert (await database.get_provider_instance("earnfm-proxy"))["proxy_id"] == 1

    import asyncio

    asyncio.run(run())


def test_find_available_proxy_is_read_only_for_current_assignment(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("vtproxy", "vtproxy")
            await database.upsert_proxy_endpoints(
                provider_id,
                [
                    {"provider_proxy_id": "a", "endpoint": "1.1.1.1:1000", "host": "1.1.1.1", "port": 1000},
                    {"provider_proxy_id": "b", "endpoint": "2.2.2.2:1000", "host": "2.2.2.2", "port": 1000},
                ],
            )
            worker = await database.upsert_worker("worker-a", "a", "http://a")
            await database.set_worker_proxy_assignment(worker, 1, "proxy", "rotate")

            before = await database.get_worker_proxy_assignment(worker)
            candidate = await database.find_available_proxy_for_worker(worker)
            after = await database.get_worker_proxy_assignment(worker)

            assert candidate and candidate["proxy_id"] == 2
            assert after["proxy_id"] == before["proxy_id"] == 1
            assert after["assignment_version"] == before["assignment_version"] == 1

    import asyncio

    asyncio.run(run())


def test_proxy_rotation_commit_rejects_candidate_held_by_another_worker(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("vtproxy", "vtproxy")
            await database.upsert_proxy_endpoints(
                provider_id,
                [
                    {"provider_proxy_id": "a", "endpoint": "1.1.1.1:1000", "host": "1.1.1.1", "port": 1000},
                    {"provider_proxy_id": "b", "endpoint": "2.2.2.2:1000", "host": "2.2.2.2", "port": 1000},
                ],
            )
            worker_a = await database.upsert_worker("worker-a", "a", "http://a")
            worker_b = await database.upsert_worker("worker-b", "b", "http://b")
            await database.set_worker_proxy_assignment(worker_a, 1, "proxy", "rotate")
            await database.save_provider_instance(
                "earnfm", "earnfm-proxy", worker_id=worker_a, mode="proxy", proxy_id=1, status="running"
            )
            current = await database.get_worker_proxy_assignment(worker_a)

            candidate = await database.find_available_proxy_for_worker(worker_a)
            assert candidate and candidate["proxy_id"] == 2
            assert await database.set_worker_proxy_assignment(worker_b, 2, "proxy", "hold")

            committed = await database.commit_proxy_rotation(
                worker_a,
                expected_proxy_id=1,
                expected_assignment_version=current["assignment_version"],
                new_proxy_id=2,
                instance_ids=["earnfm-proxy"],
            )

            assert committed is False
            assert (await database.get_worker_proxy_assignment(worker_a))["proxy_id"] == 1
            assert (await database.get_worker_proxy_assignment(worker_b))["proxy_id"] == 2
            assert (await database.get_provider_instance("earnfm-proxy"))["proxy_id"] == 1

    import asyncio

    asyncio.run(run())


def test_manual_proxy_assignment_rejects_proxy_held_by_another_worker(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("vtproxy", "vtproxy")
            await database.upsert_proxy_endpoints(
                provider_id,
                [{"provider_proxy_id": "a", "endpoint": "1.1.1.1:1000", "host": "1.1.1.1", "port": 1000}],
            )
            worker_a = await database.upsert_worker("worker-a", "a", "http://a")
            worker_b = await database.upsert_worker("worker-b", "b", "http://b")

            assert await database.set_worker_proxy_assignment(worker_a, 1, "proxy", "hold")
            assert await database.set_worker_proxy_assignment(worker_b, 1, "proxy", "hold") is False
            assert (await database.get_worker_proxy_assignment(worker_a))["proxy_id"] == 1
            assert await database.get_worker_proxy_assignment(worker_b) is None

    import asyncio

    asyncio.run(run())


def test_concurrent_manual_proxy_assignments_grant_one_lease(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("vtproxy", "vtproxy")
            await database.upsert_proxy_endpoints(
                provider_id,
                [{"provider_proxy_id": "a", "endpoint": "1.1.1.1:1000", "host": "1.1.1.1", "port": 1000}],
            )
            worker_a = await database.upsert_worker("worker-a", "a", "http://a")
            worker_b = await database.upsert_worker("worker-b", "b", "http://b")

            results = await asyncio.gather(
                database.set_worker_proxy_assignment(worker_a, 1, "proxy", "hold"),
                database.set_worker_proxy_assignment(worker_b, 1, "proxy", "hold"),
            )

            assert sorted(results) == [False, True]
            assignments = [await database.get_worker_proxy_assignment(worker_id) for worker_id in (worker_a, worker_b)]
            assert sum(bool(row and row.get("proxy_id") == 1) for row in assignments) == 1

    import asyncio

    asyncio.run(run())


def test_proxy_rotation_cas_is_atomic_against_unrelated_shared_connection_commit(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("vtproxy", "vtproxy")
            await database.upsert_proxy_endpoints(
                provider_id,
                [
                    {"provider_proxy_id": "a", "endpoint": "1.1.1.1:1000", "host": "1.1.1.1", "port": 1000},
                    {"provider_proxy_id": "b", "endpoint": "2.2.2.2:1000", "host": "2.2.2.2", "port": 1000},
                ],
            )
            worker = await database.upsert_worker("worker-a", "a", "http://a")
            await database.set_worker_proxy_assignment(worker, 1, "proxy", "rotate")
            await database.save_provider_instance(
                "earnfm", "earnfm-proxy", worker_id=worker, mode="proxy", proxy_id=1, status="running"
            )
            current = await database.get_worker_proxy_assignment(worker)
            original_open_transaction_connection = database._open_transaction_connection
            assignment_updated = asyncio.Event()
            continue_cas = asyncio.Event()
            first_call = True

            class PausingConnection:
                def __init__(self, inner):
                    self.inner = inner

                def __getattr__(self, name):
                    return getattr(self.inner, name)

                async def execute(self, sql, *args, **kwargs):
                    result = await self.inner.execute(sql, *args, **kwargs)
                    if "UPDATE proxy_assignments" in str(sql):
                        assignment_updated.set()
                        await continue_cas.wait()
                    return result

                async def close(self):
                    return await self.inner.close()

            async def open_transaction_for_cas():
                nonlocal first_call
                db = await original_open_transaction_connection()
                if first_call:
                    first_call = False
                    return PausingConnection(db)
                return db

            with patch.object(database, "_open_transaction_connection", side_effect=open_transaction_for_cas):
                cas_task = asyncio.create_task(
                    database.commit_proxy_rotation(
                        worker,
                        expected_proxy_id=1,
                        expected_assignment_version=current["assignment_version"],
                        new_proxy_id=2,
                        instance_ids=["earnfm-proxy", "missing-instance"],
                    )
                )
                await asyncio.wait_for(assignment_updated.wait(), timeout=2)
                config_task = asyncio.create_task(database.set_config_bulk({"proxy_race_marker": "1"}))
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(asyncio.shield(config_task), timeout=0.1)
                continue_cas.set()
                assert await cas_task is False
                await config_task

            assignment = await database.get_worker_proxy_assignment(worker)
            instance = await database.get_provider_instance("earnfm-proxy")
            assert assignment["proxy_id"] == 1
            assert instance["proxy_id"] == 1

    import asyncio

    asyncio.run(run())


@pytest.mark.asyncio
async def test_proxy_exit_ip_uses_raw_proxy_tunnel():
    with patch(
        "app.routers.proxies._http_get_via_socks5_proxy",
        new_callable=AsyncMock,
        return_value=b"HTTP/1.1 200 OK\r\nContent-Length: 7\r\n\r\n8.8.8.8",
    ) as fetch:
        exit_ip = await proxy_routes._probe_proxy_exit_ip("proxy.example.com", 1080, protocol="socks5")

    assert exit_ip == "8.8.8.8"
    fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_generic_proxy_probe_reports_elapsed_latency():
    with (
        patch("app.routers.proxies._probe_socks5_proxy", new_callable=AsyncMock, return_value=True),
        patch("app.routers.proxies._probe_proxy_exit_ip", new_callable=AsyncMock, return_value="8.8.8.8"),
        patch("app.routers.proxies.time.perf_counter", side_effect=[100.0, 100.012]),
    ):
        result = await proxy_routes._probe_proxy("proxy.example.com", 1080)

    assert result["status"] == "alive"
    assert result["latency_ms"] == 12


def test_manual_proxy_import_persists_multiple_rows(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            await database.upsert_proxy_endpoints(
                provider_id,
                [
                    {"host": "1.1.1.1", "port": 1000, "protocol": "http"},
                    {"host": "2.2.2.2", "port": 2000, "protocol": "socks5"},
                ],
            )
            rows = await database.list_proxy_pool()
            assert len(rows) == 2
            assert {row["endpoint"] for row in rows} == {"1.1.1.1:1000", "2.2.2.2:2000"}

    import asyncio

    asyncio.run(run())


def test_manual_assignment_rejects_duplicate_noncanonical_and_scoped_egress(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            proxy_ids = await database.upsert_proxy_endpoints_returning_ids(
                provider_id,
                [
                    {"provider_proxy_id": "canonical", "host": "1.1.1.1", "port": 1000},
                    {"provider_proxy_id": "duplicate", "host": "2.2.2.2", "port": 2000},
                ],
            )
            for proxy_id in proxy_ids:
                await database.save_proxy_probe_result(
                    proxy_id,
                    profile="generic",
                    probe_status="alive",
                    verdict="ALIVE",
                    eligibility="eligible",
                    reason="",
                    exit_ip="8.8.8.8",
                    latency_ms=10,
                    probe_version="test",
                )
            await database.reconcile_proxy_duplicates()
            scoped_worker = await database.upsert_worker("scoped", "scoped", "http://scoped")
            manual_worker = await database.upsert_worker("manual", "manual", "http://manual")

            assert await database.set_worker_proxy_assignment(manual_worker, proxy_ids[1], "proxy", "hold") is False
            assert await database.lease_proxy_for_provider_instance("future", scoped_worker, "future-1")
            assert await database.set_worker_proxy_assignment(manual_worker, proxy_ids[0], "proxy", "hold") is False

    asyncio.run(run())


def test_proxy_pool_schema_adds_intelligence_evidence_imports_and_scoped_leases(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            db = await database._get_db()
            endpoint_cols = {
                row["name"] for row in await (await db.execute("PRAGMA table_info(proxy_endpoints)")).fetchall()
            }
            tables = {
                row["name"]
                for row in await (await db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")).fetchall()
            }

            assert {
                "country_code",
                "country_name",
                "geo_source",
                "geo_confidence",
                "geo_checked_at",
                "ip_type",
                "ip_type_source",
                "ip_type_confidence",
                "ip_type_checked_at",
                "duplicate_egress",
                "canonical_proxy_id",
                "duplicate_reason",
            } <= endpoint_cols
            assert {
                "proxy_probe_results",
                "proxy_import_batches",
                "proxy_import_rows",
                "provider_proxy_leases",
            } <= tables

    asyncio.run(run())


def test_proxy_pool_schema_migrates_a_v17_database_without_losing_existing_rows(tmp_path):
    async def run():
        db_path = tmp_path / "proxy-v17.db"
        import aiosqlite

        async with aiosqlite.connect(db_path) as db:
            await db.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE workers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL DEFAULT '',
                    url TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'online',
                    containers TEXT NOT NULL DEFAULT '[]',
                    apps TEXT NOT NULL DEFAULT '[]',
                    system_info TEXT NOT NULL DEFAULT '{}',
                    last_heartbeat TEXT,
                    api_key_enc TEXT,
                    key_confirmed INTEGER NOT NULL DEFAULT 0,
                    key_issued_at TEXT,
                    registered_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE proxy_providers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    base_url TEXT NOT NULL DEFAULT '',
                    api_key_enc TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_synced_at TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    UNIQUE(type, name)
                );
                CREATE TABLE proxy_endpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider_id INTEGER,
                    provider_proxy_id TEXT,
                    endpoint TEXT NOT NULL,
                    host TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    protocol TEXT NOT NULL CHECK(protocol IN ('http', 'socks5')),
                    username TEXT NOT NULL DEFAULT '',
                    password_enc TEXT NOT NULL DEFAULT '',
                    location TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'unknown',
                    expiry_date TEXT,
                    days_left INTEGER,
                    hours_left INTEGER,
                    exit_ip TEXT,
                    udp_ok INTEGER,
                    latency_ms INTEGER,
                    last_synced_at TEXT,
                    last_checked_at TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY(provider_id) REFERENCES proxy_providers(id) ON DELETE SET NULL,
                    UNIQUE(provider_id, provider_proxy_id)
                );
                CREATE TABLE proxy_assignments (
                    worker_id INTEGER PRIMARY KEY,
                    proxy_id INTEGER,
                    mode TEXT NOT NULL DEFAULT 'proxy',
                    fallback TEXT NOT NULL DEFAULT 'hold',
                    assignment_version INTEGER NOT NULL DEFAULT 0,
                    applied_at TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY(worker_id) REFERENCES workers(id) ON DELETE CASCADE,
                    FOREIGN KEY(proxy_id) REFERENCES proxy_endpoints(id) ON DELETE SET NULL
                );
                CREATE TABLE proxy_provider_masks (
                    proxy_id INTEGER NOT NULL,
                    provider_slug TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    masked_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY(proxy_id, provider_slug),
                    FOREIGN KEY(proxy_id) REFERENCES proxy_endpoints(id) ON DELETE CASCADE
                );
                INSERT INTO workers (id, client_id, name, url) VALUES (1, 'worker-v17', 'v17', 'http://v17');
                INSERT INTO proxy_providers (id, name, type) VALUES (1, 'manual', 'manual');
                INSERT INTO proxy_endpoints
                    (id, provider_id, provider_proxy_id, endpoint, host, port, protocol, location, status, exit_ip)
                VALUES (1, 1, 'legacy-1', '1.1.1.1:1000', '1.1.1.1', 1000, 'http', 'SG', 'alive', '8.8.8.8');
                INSERT INTO proxy_assignments (worker_id, proxy_id, assignment_version) VALUES (1, 1, 4);
                INSERT INTO proxy_provider_masks (proxy_id, provider_slug, reason) VALUES (1, 'iproyal', 'ip_used');
                PRAGMA user_version = 17;
                """
            )
            await db.commit()

        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", db_path):
            await database.init_db()
            db = await database._get_db()
            version = (await (await db.execute("PRAGMA user_version")).fetchone())[0]
            columns = {row["name"] for row in await (await db.execute("PRAGMA table_info(proxy_endpoints)")).fetchall()}
            endpoint = await (await db.execute("SELECT * FROM proxy_endpoints WHERE id = 1")).fetchone()
            assignment = await (await db.execute("SELECT * FROM proxy_assignments WHERE worker_id = 1")).fetchone()
            mask = await (await db.execute("SELECT * FROM proxy_provider_masks WHERE proxy_id = 1")).fetchone()
            tables = {
                row["name"]
                for row in await (await db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")).fetchall()
            }

            assert version == 18
            assert {
                "country_code",
                "country_name",
                "geo_source",
                "geo_confidence",
                "ip_type",
                "duplicate_egress",
                "canonical_proxy_id",
                "duplicate_reason",
            } <= columns
            assert {
                "proxy_probe_results",
                "proxy_import_batches",
                "proxy_import_rows",
                "provider_proxy_leases",
            } <= tables
            assert endpoint["provider_proxy_id"] == "legacy-1"
            assert endpoint["location"] == "SG"
            assert assignment["proxy_id"] == 1
            assert assignment["assignment_version"] == 4
            assert mask["reason"] == "ip_used"

    asyncio.run(run())


def test_duplicate_egress_keeps_raw_rows_and_selects_one_canonical_proxy(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            proxy_ids = await database.upsert_proxy_endpoints_returning_ids(
                provider_id,
                [
                    {"provider_proxy_id": "slow", "host": "1.1.1.1", "port": 1000, "latency_ms": 90},
                    {"provider_proxy_id": "fast", "host": "2.2.2.2", "port": 2000, "latency_ms": 20},
                    {"provider_proxy_id": "other", "host": "3.3.3.3", "port": 3000, "latency_ms": 10},
                ],
            )
            for proxy_id, latency, exit_ip in zip(
                proxy_ids, (90, 20, 10), ("8.8.8.8", "8.8.8.8", "9.9.9.9"), strict=True
            ):
                await database.save_proxy_probe_result(
                    proxy_id,
                    profile="generic",
                    probe_status="alive",
                    verdict="ALIVE",
                    eligibility="eligible",
                    reason="",
                    exit_ip=exit_ip,
                    latency_ms=latency,
                    probe_version="test",
                )
            await database.reconcile_proxy_duplicates()
            rows = {row["id"]: row for row in await database.list_proxy_pool()}

            assert rows[proxy_ids[1]]["duplicate_egress"] is False
            assert rows[proxy_ids[1]]["canonical_proxy_id"] == proxy_ids[1]
            assert rows[proxy_ids[0]]["duplicate_egress"] is True
            assert rows[proxy_ids[0]]["canonical_proxy_id"] == proxy_ids[1]
            assert rows[proxy_ids[2]]["duplicate_egress"] is False

    asyncio.run(run())


def test_duplicate_egress_prefers_latest_earnapp_cid_set_over_generic_eligibility(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            proxy_ids = await database.upsert_proxy_endpoints_returning_ids(
                provider_id,
                [
                    {"provider_proxy_id": "blocked", "host": "1.1.1.1", "port": 1000},
                    {"provider_proxy_id": "eligible", "host": "2.2.2.2", "port": 2000},
                ],
            )
            for proxy_id in proxy_ids:
                await database.save_proxy_probe_result(
                    proxy_id,
                    profile="generic",
                    probe_status="alive",
                    verdict="ALIVE",
                    eligibility="eligible",
                    reason="",
                    exit_ip="8.8.8.8",
                    latency_ms=10,
                    probe_version="test",
                )
            await database.save_proxy_probe_result(
                proxy_ids[0],
                profile="earnapp_wss",
                probe_status="alive",
                verdict="BLACKLIST",
                eligibility="blocked",
                reason="earnapp_blacklist",
                exit_ip="8.8.8.8",
                latency_ms=5,
                probe_version="test",
            )
            await database.save_proxy_probe_result(
                proxy_ids[1],
                profile="earnapp_wss",
                probe_status="alive",
                verdict="CID_SET",
                eligibility="eligible",
                reason="cid",
                exit_ip="8.8.8.8",
                latency_ms=20,
                probe_version="test",
            )

            await database.reconcile_proxy_duplicates()
            rows = {row["id"]: row for row in await database.list_proxy_pool()}

            assert rows[proxy_ids[1]]["duplicate_egress"] is False
            assert rows[proxy_ids[1]]["canonical_proxy_id"] == proxy_ids[1]
            assert rows[proxy_ids[0]]["duplicate_egress"] is True

    asyncio.run(run())


def test_duplicate_reconciliation_does_not_revoke_existing_bound_endpoints(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            proxy_ids = await database.upsert_proxy_endpoints_returning_ids(
                provider_id,
                [
                    {"provider_proxy_id": "bound-a", "host": "1.1.1.1", "port": 1000},
                    {"provider_proxy_id": "bound-b", "host": "2.2.2.2", "port": 2000},
                    {"provider_proxy_id": "unbound", "host": "3.3.3.3", "port": 3000},
                ],
            )
            workers = [
                await database.upsert_worker("worker-a", "a", "http://a"),
                await database.upsert_worker("worker-b", "b", "http://b"),
            ]
            assert await database.set_worker_proxy_assignment(workers[0], proxy_ids[0])
            assert await database.set_worker_proxy_assignment(workers[1], proxy_ids[1])
            for proxy_id in proxy_ids:
                await database.save_proxy_probe_result(
                    proxy_id,
                    profile="generic",
                    probe_status="alive",
                    verdict="ALIVE",
                    eligibility="eligible",
                    reason="",
                    exit_ip="8.8.8.8",
                    latency_ms=10,
                    probe_version="test",
                )

            await database.reconcile_proxy_duplicates()
            rows = {row["id"]: row for row in await database.list_proxy_pool()}

            assert rows[proxy_ids[0]]["duplicate_egress"] is False
            assert rows[proxy_ids[1]]["duplicate_egress"] is True
            assert rows[proxy_ids[2]]["duplicate_egress"] is True
            assert (await database.get_worker_proxy_assignment(workers[0]))["proxy_id"] == proxy_ids[0]
            assert (await database.get_worker_proxy_assignment(workers[1]))["proxy_id"] == proxy_ids[1]

    asyncio.run(run())


def test_proxy_intelligence_cache_preserves_verified_fields_on_unknown_refresh(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            (proxy_id,) = await database.upsert_proxy_endpoints_returning_ids(
                provider_id, [{"provider_proxy_id": "one", "host": "1.1.1.1", "port": 1000}]
            )
            await database.save_proxy_probe_result(
                proxy_id,
                profile="generic",
                probe_status="alive",
                verdict="ALIVE",
                eligibility="eligible",
                reason="",
                exit_ip="8.8.8.8",
                latency_ms=10,
                probe_version="test",
            )
            await database.update_proxy_endpoint_intelligence(
                proxy_id,
                {
                    "location": "United States",
                    "country_code": "US",
                    "country_name": "United States",
                    "geo_source": "ipwho.is",
                    "geo_confidence": "verified",
                    "ip_type": "datacenter",
                    "ip_type_source": "ipapi.is",
                    "ip_type_confidence": "verified",
                },
            )
            await database.update_proxy_endpoint_intelligence(
                proxy_id,
                {
                    "location": "Unknown",
                    "country_code": "",
                    "country_name": "",
                    "geo_source": "",
                    "geo_confidence": "unknown",
                    "ip_type": "unknown",
                    "ip_type_source": "",
                    "ip_type_confidence": "unknown",
                },
            )

            cached = await database.get_cached_proxy_intelligence("8.8.8.8")
            row = (await database.list_proxy_pool())[0]
            assert cached and cached["country_code"] == "US"
            assert cached["ip_type"] == "datacenter"
            assert row["location"] == "United States"
            assert row["geo_source"] == "ipwho.is"

    asyncio.run(run())


def test_proxy_intelligence_cache_retries_when_only_one_source_is_fresh(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            (proxy_id,) = await database.upsert_proxy_endpoints_returning_ids(
                provider_id, [{"provider_proxy_id": "one", "host": "1.1.1.1", "port": 1000}]
            )
            await database.save_proxy_probe_result(
                proxy_id,
                profile="generic",
                probe_status="alive",
                verdict="ALIVE",
                eligibility="eligible",
                reason="",
                exit_ip="8.8.8.8",
                latency_ms=10,
                probe_version="test",
            )
            await database.update_proxy_endpoint_intelligence(
                proxy_id,
                {
                    "location": "United States",
                    "country_code": "US",
                    "country_name": "United States",
                    "geo_source": "ipwho.is",
                    "geo_confidence": "verified",
                    "ip_type": "unknown",
                    "ip_type_source": "",
                    "ip_type_confidence": "unknown",
                },
            )

            assert await database.get_cached_proxy_intelligence("8.8.8.8") is None

    asyncio.run(run())


def test_earnapp_probe_keeps_generic_latency_separate(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            (proxy_id,) = await database.upsert_proxy_endpoints_returning_ids(
                provider_id, [{"provider_proxy_id": "one", "host": "1.1.1.1", "port": 1000}]
            )
            await database.save_proxy_probe_result(
                proxy_id,
                profile="generic",
                probe_status="alive",
                verdict="ALIVE",
                eligibility="eligible",
                reason="",
                exit_ip="8.8.8.8",
                latency_ms=11,
                probe_version="generic-test",
            )
            await database.save_proxy_probe_result(
                proxy_id,
                profile="earnapp_wss",
                probe_status="alive",
                verdict="CID_SET",
                eligibility="eligible",
                reason="cid",
                exit_ip="8.8.8.8",
                latency_ms=99,
                probe_version="earnapp-test",
            )

            row = (await database.list_proxy_pool())[0]
            assert row["latency_ms"] == 11
            assert row["earnapp_latency_ms"] == 99

    asyncio.run(run())


def test_duplicate_export_masks_credentials_by_default_and_can_restore_raw_import(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            parsed = proxy_routes._parse_proxy_import(
                "one.example:1000:user-one:pass-one\ntwo.example:2000:user-two:pass-two\n"
            )
            proxy_ids = await database.upsert_proxy_endpoints_returning_ids(provider_id, parsed)
            await database.create_proxy_import_batch(
                provider_id,
                source_name="manual",
                raw_input="\n".join(row["_raw_line"] for row in parsed),
                parsed_rows=parsed,
                proxy_ids=proxy_ids,
            )
            for proxy_id in proxy_ids:
                await database.save_proxy_probe_result(
                    proxy_id,
                    profile="generic",
                    probe_status="alive",
                    verdict="ALIVE",
                    eligibility="eligible",
                    reason="",
                    exit_ip="8.8.8.8",
                    latency_ms=10,
                    probe_version="test",
                )
            await database.reconcile_proxy_duplicates()

            masked = await database.export_duplicate_proxy_rows(raw=False)
            raw = await database.export_duplicate_proxy_rows(raw=True)

            assert len(masked) == len(raw) == 1
            assert "pass-two" not in str(masked)
            assert raw[0]["raw_proxy"] == "two.example:2000:user-two:pass-two"

    asyncio.run(run())


def test_earnapp_scoped_lease_requires_cid_set_and_never_mutates_worker_assignment(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            proxy_ids = await database.upsert_proxy_endpoints_returning_ids(
                provider_id,
                [
                    {"provider_proxy_id": "blocked", "host": "1.1.1.1", "port": 1000},
                    {"provider_proxy_id": "good", "host": "2.2.2.2", "port": 2000},
                ],
            )
            worker_id = await database.upsert_worker("worker-a", "a", "http://a")
            for proxy_id, exit_ip in zip(proxy_ids, ("8.8.8.8", "9.9.9.9"), strict=True):
                await database.save_proxy_probe_result(
                    proxy_id,
                    profile="generic",
                    probe_status="alive",
                    verdict="ALIVE",
                    eligibility="eligible",
                    reason="",
                    exit_ip=exit_ip,
                    latency_ms=10,
                    probe_version="test",
                )
            await database.save_proxy_probe_result(
                proxy_ids[0],
                profile="earnapp_wss",
                probe_status="alive",
                verdict="BLACKLIST",
                eligibility="blocked",
                reason="earnapp_blacklist",
                exit_ip="8.8.8.8",
                latency_ms=10,
                probe_version="test",
            )
            await database.save_proxy_probe_result(
                proxy_ids[1],
                profile="earnapp_wss",
                probe_status="alive",
                verdict="CID_SET",
                eligibility="eligible",
                reason="cid",
                exit_ip="9.9.9.9",
                latency_ms=20,
                probe_version="test",
            )
            await database.reconcile_proxy_duplicates()

            lease = await database.lease_proxy_for_provider_instance("earnapp", worker_id, "earnapp-1")

            assert lease and lease["proxy_id"] == proxy_ids[1]
            assert lease["provider_slug"] == "earnapp"
            assert await database.get_worker_proxy_assignment(worker_id) is None

    asyncio.run(run())


def test_provider_scoped_lease_is_idempotent_for_the_same_instance(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            (proxy_id,) = await database.upsert_proxy_endpoints_returning_ids(
                provider_id, [{"provider_proxy_id": "one", "host": "1.1.1.1", "port": 1000}]
            )
            await database.save_proxy_probe_result(
                proxy_id,
                profile="generic",
                probe_status="alive",
                verdict="ALIVE",
                eligibility="eligible",
                reason="",
                exit_ip="8.8.8.8",
                latency_ms=10,
                probe_version="test",
            )
            worker_id = await database.upsert_worker("worker-a", "a", "http://a")

            first = await database.lease_proxy_for_provider_instance("future", worker_id, "future-1")
            second = await database.lease_proxy_for_provider_instance("future", worker_id, "future-1")

            assert first and second
            assert first["proxy_id"] == second["proxy_id"] == proxy_id

    asyncio.run(run())


def test_new_scoped_leases_never_share_an_egress_ip_across_providers(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            proxy_ids = await database.upsert_proxy_endpoints_returning_ids(
                provider_id,
                [
                    {"provider_proxy_id": "first", "host": "1.1.1.1", "port": 1000},
                    {"provider_proxy_id": "same-egress", "host": "2.2.2.2", "port": 2000},
                    {"provider_proxy_id": "other-egress", "host": "3.3.3.3", "port": 3000},
                ],
            )
            for proxy_id, exit_ip in zip(proxy_ids, ("8.8.8.8", "8.8.8.8", "9.9.9.9"), strict=True):
                await database.save_proxy_probe_result(
                    proxy_id,
                    profile="generic",
                    probe_status="alive",
                    verdict="ALIVE",
                    eligibility="eligible",
                    reason="",
                    exit_ip=exit_ip,
                    latency_ms=10,
                    probe_version="test",
                )
                await database.save_proxy_probe_result(
                    proxy_id,
                    profile="earnapp_wss",
                    probe_status="alive",
                    verdict="CID_SET",
                    eligibility="eligible",
                    reason="cid",
                    exit_ip=exit_ip,
                    latency_ms=10,
                    probe_version="test",
                )
            await database.reconcile_proxy_duplicates()
            worker_a = await database.upsert_worker("worker-a", "a", "http://a")
            worker_b = await database.upsert_worker("worker-b", "b", "http://b")

            first = await database.lease_proxy_for_provider_instance("earnapp", worker_a, "earnapp-1")
            second = await database.lease_proxy_for_provider_instance("future-provider", worker_b, "future-1")

            assert first and first["exit_ip"] == "8.8.8.8"
            assert second and second["exit_ip"] == "9.9.9.9"

    asyncio.run(run())


def test_legacy_worker_lease_skips_duplicate_and_scoped_egress_for_new_assignments(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            proxy_ids = await database.upsert_proxy_endpoints_returning_ids(
                provider_id,
                [
                    {"provider_proxy_id": "leased", "host": "1.1.1.1", "port": 1000},
                    {"provider_proxy_id": "same-egress", "host": "2.2.2.2", "port": 2000},
                    {"provider_proxy_id": "free", "host": "3.3.3.3", "port": 3000},
                ],
            )
            for proxy_id, exit_ip in zip(proxy_ids, ("8.8.8.8", "8.8.8.8", "9.9.9.9"), strict=True):
                await database.save_proxy_probe_result(
                    proxy_id,
                    profile="generic",
                    probe_status="alive",
                    verdict="ALIVE",
                    eligibility="eligible",
                    reason="",
                    exit_ip=exit_ip,
                    latency_ms=10,
                    probe_version="test",
                )
            await database.reconcile_proxy_duplicates()
            scoped_worker = await database.upsert_worker("worker-scoped", "scoped", "http://scoped")
            legacy_worker = await database.upsert_worker("worker-legacy", "legacy", "http://legacy")
            scoped = await database.lease_proxy_for_provider_instance("future-provider", scoped_worker, "future-1")
            legacy = await database.lease_proxy_for_worker(legacy_worker)

            assert scoped and scoped["exit_ip"] == "8.8.8.8"
            assert legacy and legacy["exit_ip"] == "9.9.9.9"

    asyncio.run(run())


def test_delete_all_proxy_pool_cascades_pool_state_and_preserves_provider_config(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            proxy_ids = await database.upsert_proxy_endpoints_returning_ids(
                provider_id,
                [
                    {"provider_proxy_id": "legacy", "host": "1.1.1.1", "port": 1000},
                    {"provider_proxy_id": "scoped", "host": "2.2.2.2", "port": 2000},
                ],
            )
            await database.create_proxy_import_batch(
                provider_id,
                source_name="manual",
                raw_input="1.1.1.1:1000\n2.2.2.2:2000",
                parsed_rows=[{"_raw_line": "1.1.1.1:1000"}, {"_raw_line": "2.2.2.2:2000"}],
                proxy_ids=proxy_ids,
            )
            for proxy_id, exit_ip in zip(proxy_ids, ("8.8.8.8", "9.9.9.9"), strict=True):
                await database.save_proxy_probe_result(
                    proxy_id,
                    profile="generic",
                    probe_status="alive",
                    verdict="ALIVE",
                    eligibility="eligible",
                    reason="cid",
                    exit_ip=exit_ip,
                    latency_ms=10,
                    probe_version="test",
                )
            await database.save_proxy_probe_result(
                proxy_ids[1],
                profile="earnapp_wss",
                probe_status="alive",
                verdict="CID_SET",
                eligibility="eligible",
                reason="cid",
                exit_ip="9.9.9.9",
                latency_ms=10,
                probe_version="test",
            )
            await database.reconcile_proxy_duplicates()
            legacy_worker = await database.upsert_worker("worker-legacy", "legacy", "http://legacy")
            scoped_worker = await database.upsert_worker("worker-scoped", "scoped", "http://scoped")
            assert await database.set_worker_proxy_assignment(legacy_worker, proxy_ids[0])
            assert await database.lease_proxy_for_provider_instance("earnapp", scoped_worker, "earnapp-1")
            await database.mask_proxy_for_provider(proxy_ids[0], "iproyal", "ip_used")
            await database.save_provider_instance(
                "protected-example",
                "protected-example-1",
                worker_id=legacy_worker,
                mode="proxy",
                proxy_id=proxy_ids[0],
                status="running",
            )

            deleted = await database.delete_all_proxy_pool()
            db = await database._get_db()
            counts = {}
            for table in (
                "proxy_endpoints",
                "proxy_assignments",
                "proxy_provider_masks",
                "proxy_probe_results",
                "provider_proxy_leases",
                "proxy_import_batches",
                "proxy_import_rows",
            ):
                counts[table] = (await (await db.execute(f"SELECT COUNT(*) AS n FROM {table}")).fetchone())["n"]
            provider_instance = await database.get_provider_instance("protected-example-1")

            assert deleted == 2
            assert counts == {
                "proxy_endpoints": 0,
                "proxy_assignments": 0,
                "proxy_provider_masks": 0,
                "proxy_probe_results": 0,
                "provider_proxy_leases": 0,
                "proxy_import_batches": 0,
                "proxy_import_rows": 0,
            }
            assert provider_instance is not None
            assert provider_instance["proxy_id"] is None
            assert await database.get_proxy_provider(provider_id) is not None

    asyncio.run(run())


def test_delete_all_proxy_pool_rolls_back_everything_if_endpoint_delete_fails(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            (proxy_id,) = await database.upsert_proxy_endpoints_returning_ids(
                provider_id, [{"provider_proxy_id": "one", "host": "1.1.1.1", "port": 1000}]
            )
            worker_id = await database.upsert_worker("worker-a", "a", "http://a")
            assert await database.set_worker_proxy_assignment(worker_id, proxy_id)
            db = await database._get_db()
            await db.execute(
                """
                CREATE TRIGGER fail_proxy_pool_delete
                BEFORE DELETE ON proxy_endpoints
                BEGIN
                    SELECT RAISE(ABORT, 'simulated delete failure');
                END
                """
            )
            await db.commit()

            with pytest.raises(Exception, match="simulated delete failure"):
                await database.delete_all_proxy_pool()

            assignment_count = (await (await db.execute("SELECT COUNT(*) AS n FROM proxy_assignments")).fetchone())["n"]
            endpoint_count = (await (await db.execute("SELECT COUNT(*) AS n FROM proxy_endpoints")).fetchone())["n"]
            assert assignment_count == 1
            assert endpoint_count == 1

    asyncio.run(run())


def test_proxy_pool_delete_selected_and_dead(client):
    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch("app.routers.proxies.database.delete_proxy_endpoints", new_callable=AsyncMock, return_value=2) as delete,
    ):
        resp = client.request("DELETE", "/api/proxy-pool", json={"proxy_ids": [1, 2]})
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 2
    delete.assert_awaited_once_with([1, 2], status=None)

    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch(
            "app.routers.proxies.database.delete_proxy_endpoints", new_callable=AsyncMock, return_value=3
        ) as delete_dead,
    ):
        resp = client.request("DELETE", "/api/proxy-pool", json={"status": "dead"})
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 3
    delete_dead.assert_awaited_once_with(None, status="dead")


def test_proxy_pool_delete_all_requires_two_exact_confirmations(client):
    with patch("app.main.auth.get_current_user", return_value=_owner_user()):
        first = client.request(
            "DELETE", "/api/proxy-pool", json={"delete_all": True, "confirmation": "DELETE ALL PROXY POOL"}
        )
    assert first.status_code == 400

    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch(
            "app.routers.proxies.database.delete_all_proxy_pool", new_callable=AsyncMock, return_value=7
        ) as delete_all,
    ):
        second = client.request(
            "DELETE",
            "/api/proxy-pool",
            json={
                "delete_all": True,
                "confirmation": "DELETE ALL PROXY POOL",
                "confirmation_again": "DELETE ALL PROXY POOL",
            },
        )
    assert second.status_code == 200
    assert second.json()["deleted"] == 7
    delete_all.assert_awaited_once_with()


def test_provider_scoped_lease_route_does_not_call_worker_level_assignment(client):
    lease = {"provider_slug": "earnapp", "worker_id": 3, "instance_id": "earn-1", "proxy_id": 8}
    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch(
            "app.routers.proxies.database.lease_proxy_for_provider_instance",
            new_callable=AsyncMock,
            return_value=lease,
        ) as lease_proxy,
    ):
        response = client.post(
            "/api/proxy-pool/provider-lease",
            json={"provider_slug": "earnapp", "worker_id": 3, "instance_id": "earn-1"},
        )
    assert response.status_code == 200
    assert response.json()["lease"] == lease
    lease_proxy.assert_awaited_once_with("earnapp", 3, "earn-1")


def test_provider_scoped_release_route_releases_only_the_requested_instance(client):
    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch(
            "app.routers.proxies.database.release_proxy_for_provider_instance",
            new_callable=AsyncMock,
            return_value=True,
        ) as release_proxy,
    ):
        response = client.post(
            "/api/proxy-pool/provider-release",
            json={"provider_slug": "EarnApp", "worker_id": 3, "instance_id": "earn-1"},
        )

    assert response.status_code == 200
    assert response.json()["released"] is True
    release_proxy.assert_awaited_once_with("EarnApp", 3, "earn-1", reason="manual release")


def test_duplicate_export_supports_masked_default_and_explicit_raw_mode(client):
    rows = [
        {
            "id": 5,
            "endpoint": "proxy.example:1000",
            "username": "secret-user",
            "password": "secret-pass",
            "exit_ip": "8.8.8.8",
            "duplicate_egress": True,
            "canonical_proxy_id": 4,
            "duplicate_reason": "duplicate egress 8.8.8.8",
        }
    ]
    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch("app.routers.proxies.database.export_duplicate_proxy_rows", new_callable=AsyncMock, return_value=rows),
    ):
        masked = client.get("/api/proxy-pool/duplicates/export")
    assert masked.status_code == 200
    assert "secret-pass" not in masked.text
    assert "duplicate egress" in masked.text

    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch("app.routers.proxies.database.export_duplicate_proxy_rows", new_callable=AsyncMock, return_value=rows),
    ):
        raw = client.get("/api/proxy-pool/duplicates/export?raw=true")
    assert raw.status_code == 200
    assert "secret-pass" in raw.text


def test_active_services_counts_deployed_rows_not_running_only(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "summary.db"):
            await database.init_db()
            await database.save_deployment("proxybase-xyz", "c2", status="external")
            from app import main as app_main

            with (
                patch(
                    "app.main._get_all_worker_containers",
                    new_callable=AsyncMock,
                    return_value=[
                        {
                            "slug": "earnfm",
                            "name": "cashpilot-earnfm",
                            "status": "running",
                            "image": "earnfm",
                            "_node": "w1",
                            "_worker_id": 7,
                            "_has_docker": True,
                            "_is_android": False,
                        }
                    ],
                ),
                patch("app.main._require_reader", lambda request: None),
            ):
                summary = await app_main.api_earnings_summary(object())
            assert summary["active_services"] == 2

    import asyncio

    asyncio.run(run())


def test_proxy_pool_scheduler_settings_are_persisted(client):
    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch("app.routers.proxies.database.get_config", new_callable=AsyncMock, return_value={}),
        patch("app.routers.proxies.database.set_config_bulk", new_callable=AsyncMock) as save,
    ):
        resp = client.post(
            "/api/proxy-pool/scheduler", json={"enabled": True, "interval_minutes": 30, "concurrency": 6}
        )
    assert resp.status_code == 200
    save.assert_awaited_once()


def test_proxy_pool_scheduler_interval_is_not_a_one_minute_loop():
    settings = proxy_routes._proxy_scheduler_settings(
        {
            "proxy_pool_recheck_enabled": "true",
            "proxy_pool_recheck_interval_minutes": "1",
            "proxy_pool_recheck_concurrency": "8",
        }
    )

    assert settings["enabled"] is True
    assert settings["interval_minutes"] == 15


def test_proxy_lease_picks_one_unassigned_proxy_per_worker(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("vtproxy", "vtproxy")
            await database.upsert_proxy_endpoints(
                provider_id,
                [
                    {"provider_proxy_id": "a", "endpoint": "1.1.1.1:1000", "host": "1.1.1.1", "port": 1000},
                    {"provider_proxy_id": "b", "endpoint": "2.2.2.2:1000", "host": "2.2.2.2", "port": 1000},
                ],
            )
            worker_a = await database.upsert_worker("worker-a", "a", "http://a")
            worker_b = await database.upsert_worker("worker-b", "b", "http://b")

            first = await database.lease_proxy_for_worker(worker_a)
            second = await database.lease_proxy_for_worker(worker_b)
            again = await database.lease_proxy_for_worker(worker_a)

            assert first and second
            assert first["proxy_id"] != second["proxy_id"]
            assert first["assignment_version"] == 1
            assert second["assignment_version"] == 1
            assert again["proxy_id"] == first["proxy_id"]
            assert again["assignment_version"] == 1

    import asyncio

    asyncio.run(run())


def test_proxy_lease_skips_dead_proxies(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("vtproxy", "vtproxy")
            await database.upsert_proxy_endpoints(
                provider_id,
                [
                    {
                        "provider_proxy_id": "dead",
                        "endpoint": "1.1.1.1:1000",
                        "host": "1.1.1.1",
                        "port": 1000,
                        "status": "dead",
                    },
                    {
                        "provider_proxy_id": "alive",
                        "endpoint": "2.2.2.2:1000",
                        "host": "2.2.2.2",
                        "port": 1000,
                        "status": "alive",
                    },
                ],
            )
            worker = await database.upsert_worker("worker-a", "a", "http://a")

            lease = await database.lease_proxy_for_worker(worker)

            assert lease
            assert lease["endpoint"] == "2.2.2.2:1000"

    import asyncio

    asyncio.run(run())


def test_proxy_lease_clears_dead_worker_assignment_before_releasing_new_proxy(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("vtproxy", "vtproxy")
            await database.upsert_proxy_endpoints(
                provider_id,
                [
                    {
                        "provider_proxy_id": "dead",
                        "endpoint": "1.1.1.1:1000",
                        "host": "1.1.1.1",
                        "port": 1000,
                        "status": "alive",
                    },
                    {
                        "provider_proxy_id": "alive",
                        "endpoint": "2.2.2.2:1000",
                        "host": "2.2.2.2",
                        "port": 1000,
                        "status": "alive",
                    },
                ],
            )
            worker = await database.upsert_worker("worker-a", "a", "http://a")
            await database.set_worker_proxy_assignment(worker, 1, "proxy", "hold")

            with (
                patch(
                    "app.main.database.get_worker_proxy_assignment",
                    new_callable=AsyncMock,
                    return_value={
                        "worker_id": worker,
                        "proxy_id": 1,
                        "host": "1.1.1.1",
                        "port": 1000,
                        "username": "",
                        "password": "",
                    },
                ),
                patch("app.main.database.proxy_masked_for_provider", new_callable=AsyncMock, return_value=False),
                patch(
                    "app.main.database.clear_worker_proxy_assignment", new_callable=AsyncMock, return_value=True
                ) as clear,
                patch(
                    "app.main.database.lease_proxy_for_worker",
                    new_callable=AsyncMock,
                    return_value={
                        "worker_id": worker,
                        "proxy_id": 2,
                        "host": "2.2.2.2",
                        "port": 1000,
                    },
                ) as lease,
                patch(
                    "app.routers.proxies._probe_proxy_confirmed",
                    new_callable=AsyncMock,
                    return_value={"status": "dead"},
                ),
            ):
                proxy = await main._proxy_for_worker_instance(worker)

            assert proxy["proxy_id"] == 2
            clear.assert_awaited_once_with(worker)
            lease.assert_awaited_once_with(worker, provider_slug=None)

    import asyncio

    asyncio.run(run())


def test_proxy_lease_rotates_active_sidecars_before_returning_replacement():
    async def run():
        old = {
            "worker_id": 7,
            "proxy_id": 1,
            "host": "1.1.1.1",
            "port": 1000,
            "username": "",
            "password": "",
        }
        candidate = {"proxy_id": 2, "host": "2.2.2.2", "port": 1000, "protocol": "socks5"}
        with (
            patch("app.main.database.get_worker_proxy_assignment", new_callable=AsyncMock, return_value=old),
            patch("app.main.database.proxy_masked_for_provider", new_callable=AsyncMock, return_value=False),
            patch(
                "app.routers.proxies._probe_proxy_confirmed",
                new_callable=AsyncMock,
                return_value={"status": "dead"},
            ),
            patch("app.routers.proxies._worker_has_proxy_instances", new_callable=AsyncMock, return_value=True),
            patch(
                "app.main.database.find_available_proxy_for_worker",
                new_callable=AsyncMock,
                return_value=candidate,
            ) as find,
            patch(
                "app.routers.proxies._rotate_worker_proxy_after_ack", new_callable=AsyncMock, return_value=True
            ) as rotate,
            patch("app.main.database.clear_worker_proxy_assignment", new_callable=AsyncMock) as clear,
            patch("app.main.database.lease_proxy_for_worker", new_callable=AsyncMock) as lease,
        ):
            proxy = await main._proxy_for_worker_instance(7)

        assert proxy == candidate
        find.assert_awaited_once_with(7, provider_slug=None)
        rotate.assert_awaited_once_with(7, candidate)
        clear.assert_not_awaited()
        lease.assert_not_awaited()

    asyncio.run(run())


def test_proxy_mask_is_provider_specific_for_pawns(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("vtproxy", "vtproxy")
            await database.upsert_proxy_endpoints(
                provider_id,
                [
                    {"provider_proxy_id": "a", "endpoint": "1.1.1.1:1000", "host": "1.1.1.1", "port": 1000},
                    {"provider_proxy_id": "b", "endpoint": "2.2.2.2:1000", "host": "2.2.2.2", "port": 1000},
                ],
            )
            worker_a = await database.upsert_worker("worker-a", "a", "http://a")
            worker_b = await database.upsert_worker("worker-b", "b", "http://b")

            first = await database.lease_proxy_for_worker(worker_a)
            assert first
            assert await database.mask_proxy_for_provider(int(first["proxy_id"]), "iproyal", "ip_used")
            pawns = await database.lease_proxy_for_worker(worker_a, provider_slug="iproyal")
            generic = await database.lease_proxy_for_worker(worker_b)

            assert pawns and pawns["proxy_id"] != first["proxy_id"]
            assert generic and generic["proxy_id"] == first["proxy_id"]

    import asyncio

    asyncio.run(run())


def test_proxy_pool_export_can_filter_by_protocol(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "proxy.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("vtproxy", "vtproxy")
            await database.upsert_proxy_endpoints(
                provider_id,
                [
                    {
                        "provider_proxy_id": "a",
                        "endpoint": "1.1.1.1:1000",
                        "host": "1.1.1.1",
                        "port": 1000,
                        "protocol": "http",
                    },
                    {
                        "provider_proxy_id": "b",
                        "endpoint": "2.2.2.2:1000",
                        "host": "2.2.2.2",
                        "port": 1000,
                        "protocol": "socks5",
                    },
                ],
            )
            rows = await database.export_proxy_pool(protocol="http")
            assert [row["protocol"] for row in rows] == ["http"]

    import asyncio

    asyncio.run(run())


def test_service_collect_route_calls_single_collector(client):
    class Result:
        error = None
        platform = "earnfm"
        balance = 1.25
        currency = "USD"

    class Collector:
        async def close(self):
            return None

    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch("app.main.catalog.get_service", return_value={"name": "EarnFM", "slug": "earnfm"}),
        patch("app.main.database.get_config", new_callable=AsyncMock, return_value={}),
        patch("app.collectors.build_one", return_value=(Collector(), [])),
        patch("app.main._collect_bounded", new_callable=AsyncMock, return_value=Result()),
        patch("app.main.database.upsert_earnings", new_callable=AsyncMock) as upsert,
        patch("app.main._detect_payout", new_callable=AsyncMock, return_value=None),
    ):
        resp = client.post("/api/services/earnfm/collect")
    assert resp.status_code == 200
    upsert.assert_awaited_once()
