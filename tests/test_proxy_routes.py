from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app import database
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
    lease = {"worker_id": 7, "proxy_id": 3, "mode": "proxy", "host": "proxy.example.com", "port": 8080, "protocol": "http"}
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
        patch("app.routers.proxies.run_proxy_pool_recheck", new_callable=AsyncMock, return_value={"checked": 3, "alive": 2, "dead": 1, "rotated": 1}) as mark,
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
        patch("app.routers.proxies.database.upsert_proxy_endpoints", new_callable=AsyncMock, return_value=4),
        patch("app.routers.proxies.database.get_config", new_callable=AsyncMock, return_value={}),
        patch("app.routers.proxies.run_proxy_pool_recheck", new_callable=AsyncMock, return_value={"checked": 2, "alive": 2, "dead": 0, "rotated": 0}) as recheck,
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
        patch("app.routers.proxies.database.upsert_proxy_endpoints", new_callable=AsyncMock, return_value=4) as upsert,
        patch("app.routers.proxies.database.get_config", new_callable=AsyncMock, return_value={}),
        patch("app.routers.proxies.run_proxy_pool_recheck", new_callable=AsyncMock, return_value={"checked": 4, "alive": 4, "dead": 0, "rotated": 0}) as recheck,
    ):
        resp = client.post("/api/proxy-pool/import", json={"text": payload, "provider_name": "manual", "recheck": True})
    assert resp.status_code == 200
    assert resp.json()["imported"] == 4
    upsert.assert_awaited_once()
    recheck.assert_awaited_once()

def test_proxy_pool_import_reports_inserted_count_not_parse_count(client):
    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch("app.routers.proxies.database.upsert_proxy_provider", new_callable=AsyncMock, return_value=9),
        patch("app.routers.proxies.database.upsert_proxy_endpoints", new_callable=AsyncMock, return_value=2),
        patch("app.routers.proxies.database.get_config", new_callable=AsyncMock, return_value={}),
        patch("app.routers.proxies.run_proxy_pool_recheck", new_callable=AsyncMock, return_value={"checked": 2, "alive": 2, "dead": 0, "rotated": 0}),
    ):
        resp = client.post("/api/proxy-pool/import", json={"text": "1.1.1.1:1000\n2.2.2.2:2000\n", "provider_name": "manual", "recheck": False})
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
        patch("app.routers.proxies._probe_proxy_confirmed", new_callable=AsyncMock, return_value={"status": "alive", "protocol": "socks5"}) as probe,
    ):
        result = await proxy_routes.run_proxy_pool_recheck(proxy_ids=[7], concurrency=1)

    assert result["status"] == "ok"
    lookup.assert_awaited_once_with(7)
    probe.assert_awaited_once_with("proxy.example.com", 1080, username="user", password="pass")

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
        patch("app.routers.proxies.database.delete_proxy_endpoints", new_callable=AsyncMock, return_value=3) as delete_dead,
    ):
        resp = client.request("DELETE", "/api/proxy-pool", json={"status": "dead"})
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 3
    delete_dead.assert_awaited_once_with(None, status="dead")

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
                            "slug": "grass",
                            "name": "cashpilot-grass",
                            "status": "running",
                            "image": "grass",
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
        resp = client.post("/api/proxy-pool/scheduler", json={"enabled": True, "interval_minutes": 30, "concurrency": 6})
    assert resp.status_code == 200
    save.assert_awaited_once()

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
            assert again["proxy_id"] == first["proxy_id"]

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
                    {"provider_proxy_id": "dead", "endpoint": "1.1.1.1:1000", "host": "1.1.1.1", "port": 1000, "status": "dead"},
                    {"provider_proxy_id": "alive", "endpoint": "2.2.2.2:1000", "host": "2.2.2.2", "port": 1000, "status": "alive"},
                ],
            )
            worker = await database.upsert_worker("worker-a", "a", "http://a")

            lease = await database.lease_proxy_for_worker(worker)

            assert lease
            assert lease["endpoint"] == "2.2.2.2:1000"

    import asyncio

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
                    {"provider_proxy_id": "a", "endpoint": "1.1.1.1:1000", "host": "1.1.1.1", "port": 1000, "protocol": "http"},
                    {"provider_proxy_id": "b", "endpoint": "2.2.2.2:1000", "host": "2.2.2.2", "port": 1000, "protocol": "socks5"},
                ],
            )
            rows = await database.export_proxy_pool(protocol="http")
            assert [row["protocol"] for row in rows] == ["http"]

    import asyncio

    asyncio.run(run())

def test_service_collect_route_calls_single_collector(client):
    class Result:
        error = None
        platform = "grass"
        balance = 1.25
        currency = "USD"
    class Collector:
        async def close(self):
            return None

    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch("app.main.catalog.get_service", return_value={"name": "Grass", "slug": "grass"}),
        patch("app.main.database.get_config", new_callable=AsyncMock, return_value={}),
        patch("app.collectors.build_one", return_value=(Collector(), [])),
        patch("app.main._collect_bounded", new_callable=AsyncMock, return_value=Result()),
        patch("app.main.database.upsert_earnings", new_callable=AsyncMock) as upsert,
        patch("app.main._detect_payout", new_callable=AsyncMock, return_value=None),
    ):
        resp = client.post("/api/services/grass/collect")
    assert resp.status_code == 200
    upsert.assert_awaited_once()
