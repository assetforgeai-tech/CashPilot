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
        patch("app.routers.proxies.database.upsert_proxy_endpoints", new_callable=AsyncMock, return_value=4),
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
        patch("app.routers.proxies.database.upsert_proxy_endpoints", new_callable=AsyncMock, return_value=4) as upsert,
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


def test_proxy_pool_import_reports_inserted_count_not_parse_count(client):
    with (
        patch("app.main.auth.get_current_user", return_value=_owner_user()),
        patch("app.routers.proxies.database.upsert_proxy_provider", new_callable=AsyncMock, return_value=9),
        patch("app.routers.proxies.database.upsert_proxy_endpoints", new_callable=AsyncMock, return_value=2),
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
        patch(
            "app.routers.proxies.database.delete_proxy_endpoints", new_callable=AsyncMock, return_value=3
        ) as delete_dead,
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
