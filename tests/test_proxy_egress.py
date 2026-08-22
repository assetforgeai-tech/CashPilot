"""Regression tests for the proxy-egress module."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import catalog, database


def test_service_egress_defaults_to_proxy():
    assert catalog.service_egress_mode({"slug": "demo"}) == "proxy"
    assert catalog.service_egress_mode({"slug": "demo", "egress": {"mode": "direct"}}) == "direct"
    assert catalog.service_egress_udp({"slug": "demo", "egress": {"udp": "required"}}) == "required"


def test_validate_rejects_invalid_egress_mode():
    data = {
        "name": "Demo",
        "slug": "demo",
        "category": "bandwidth",
        "status": "active",
        "description": "Demo service",
        "docker": {"image": "demo:latest"},
        "egress": {"mode": "banana"},
    }
    errors = catalog._validate(data, Path("demo.yml"))
    assert any("egress.mode" in err for err in errors), errors


def test_vtproxy_proxy_parser_normalizes_fields():
    from app.proxy_providers.vtproxy import parse_proxies

    payload = {
        "success": True,
        "data": {
            "proxies": [
                {
                    "id": 56291,
                    "endpoint": "dc-t5.proxyvt.com:45884",
                    "username": "user123",
                    "password": "pass456",
                    "protocol": "socks5",
                    "location": "Vietnam",
                    "status": "active",
                    "days_left": 5,
                    "hours_left": 0,
                    "expiry_date": "2026-08-15",
                }
            ]
        },
    }
    proxies = parse_proxies(payload)
    assert proxies == [
        {
            "provider_proxy_id": 56291,
            "endpoint": "dc-t5.proxyvt.com:45884",
            "host": "dc-t5.proxyvt.com",
            "port": 45884,
            "username": "user123",
            "password": "pass456",
            "protocol": "socks5",
            "location": "Vietnam",
            "status": "active",
            "days_left": 5,
            "hours_left": 0,
            "expiry_date": "2026-08-15",
        }
    ]


def test_singbox_config_uses_tun_and_socks_outbound():
    from app.singbox_config import render_tun_proxy_config

    config = render_tun_proxy_config(
        {
            "host": "dc-t5.proxyvt.com",
            "port": 45884,
            "username": "user123",
            "password": "pass456",
            "protocol": "socks5",
        },
        worker_name="vps-main",
    )
    assert config["inbounds"][0]["type"] == "tun"
    assert len(config["inbounds"][0]["interface_name"]) <= 15
    assert config["outbounds"][0]["type"] == "socks"
    assert config["route"]["final"] == "proxy-out"
    assert config["dns"]["strategy"] == "ipv4_only"
    assert {"port": 53, "outbound": "direct"} in config["route"]["rules"]
    assert {"domain": ["dc-t5.proxyvt.com"], "outbound": "direct"} in config["route"]["rules"]


def test_singbox_config_can_use_repocket_safe_tun_name():
    from app.singbox_config import render_tun_proxy_config

    config = render_tun_proxy_config(
        {"host": "proxy.example.com", "port": 1080, "protocol": "socks5"},
        worker_name="repocket-proxy",
        interface_name="cpegress",
    )
    assert config["inbounds"][0]["interface_name"] == "cpegress"


def test_singbox_config_can_route_udp_direct_for_traffmonetizer_proxy():
    from app.singbox_config import render_tun_proxy_config

    config = render_tun_proxy_config(
        {
            "host": "dc-t5.proxyvt.com",
            "port": 45884,
            "username": "user123",
            "password": "pass456",
            "protocol": "socks5",
        },
        worker_name="traffmonetizer-proxy",
        udp_direct=True,
    )
    assert {"network": "udp", "outbound": "direct"} in config["route"]["rules"]
    assert {"network": "tcp", "outbound": "proxy-out"} in config["route"]["rules"]
    assert config["route"]["final"] == "proxy-out"


def test_http_proxy_never_satisfies_udp_required():
    from app import proxy_egress

    mode = proxy_egress.choose_mode(
        requested_mode="proxy",
        service_udp="required",
        proxy={"protocol": "http", "udp_ok": True},
    )
    assert mode == "direct"


def test_socks5_proxy_satisfies_udp_only_when_marked_ok():
    from app import proxy_egress

    assert (
        proxy_egress.choose_mode(
            requested_mode="auto",
            service_udp="required",
            proxy={"protocol": "socks5", "udp_ok": False},
        )
        == "direct"
    )
    assert (
        proxy_egress.choose_mode(
            requested_mode="auto",
            service_udp="required",
            proxy={"protocol": "socks5", "udp_ok": True},
        )
        == "proxy"
    )


def test_direct_provider_bypasses_fake_proxy():
    from app import proxy_egress

    assert (
        proxy_egress.choose_mode(
            requested_mode="direct",
            service_udp="none",
            proxy={"protocol": "socks5", "udp_ok": True},
        )
        == "direct"
    )


def test_auto_chooses_direct_for_udp_when_proxy_cannot_udp():
    from app import proxy_egress

    assert (
        proxy_egress.choose_mode(
            requested_mode="auto",
            service_udp="required",
            proxy={"protocol": "http"},
        )
        == "direct"
    )


def test_init_db_creates_proxy_tables(tmp_path):
    db_path = tmp_path / "cashpilot.db"
    with (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", db_path),
    ):
        asyncio.run(database.init_db())

        async def check():
            conn = await database._get_db()
            try:
                cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = {row["name"] for row in await cur.fetchall()}
            finally:
                await conn.close()
            assert {"proxy_providers", "proxy_endpoints", "proxy_assignments"} <= tables

        asyncio.run(check())


def test_worker_egress_apply_writes_singbox_config(tmp_path):
    from app import worker_api

    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    config_file = tmp_path / "egress" / "sing-box.json"
    worker_api.app.router.lifespan_context = noop_lifespan
    with (
        patch.object(worker_api, "_verify_api_key", lambda _request: None),
        patch.object(worker_api, "_EGRESS_CONFIG_DIR", config_file.parent),
        patch.object(worker_api, "_EGRESS_CONFIG_FILE", config_file),
        TestClient(worker_api.app, raise_server_exceptions=False) as client,
    ):
        resp = client.post(
            "/api/egress/apply",
            json={
                "mode": "proxy",
                "service_udp": "required",
                "worker_name": "w1",
                "proxy": {"host": "proxy.example.com", "port": 8080, "protocol": "http", "password": "secret-pass"},
            },
        )
    assert resp.status_code == 200
    assert resp.json()["mode"] == "direct"
    assert "secret-pass" not in resp.text
    assert config_file.read_text(encoding="utf-8")


def test_worker_proxy_probe_rejects_untrusted_target_before_network():
    from app import worker_api

    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    worker_api.app.router.lifespan_context = noop_lifespan
    with (
        patch.object(worker_api, "_verify_api_key", lambda _request: None),
        patch.object(
            worker_api,
            "_probe_proxy_targets",
            new_callable=AsyncMock,
            return_value={"ok": True, "results": []},
        ) as probe,
        TestClient(worker_api.app, raise_server_exceptions=False) as client,
    ):
        resp = client.post(
            "/api/proxy/probe-targets",
            json={
                "proxy": {"host": "proxy.example.com", "port": 1080},
                "targets": ["http://127.0.0.1:8080/admin"],
            },
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "custom proxy probe targets are not allowed"
    probe.assert_not_awaited()


def test_worker_proxy_binding_apply_returns_redacted_ack():
    from app import worker_api

    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    worker_api.app.router.lifespan_context = noop_lifespan
    proxy = {
        "proxy_id": 17,
        "host": "proxy.example.com",
        "port": 1080,
        "protocol": "socks5",
        "username": "proxy-user",
        "password": "secret-pass",
    }
    with (
        patch.object(worker_api, "_verify_api_key", lambda _request: None),
        patch.object(
            worker_api,
            "_probe_proxy_targets",
            new_callable=AsyncMock,
            return_value={"ok": True, "observed_exit_ip": "8.8.8.8", "results": []},
        ) as probe,
        patch.object(
            worker_api.orchestrator,
            "apply_proxy_binding_batch",
            return_value={
                "applied_instances": ["earnfm-proxy"],
                "config_sha256": "a" * 64,
            },
        ) as apply,
        patch.object(worker_api.asyncio, "to_thread", new_callable=AsyncMock) as to_thread,
        TestClient(worker_api.app, raise_server_exceptions=False) as client,
    ):
        to_thread.return_value = {
            "applied_instances": ["earnfm-proxy"],
            "config_sha256": "a" * 64,
        }
        resp = client.post(
            "/api/egress/bindings/apply",
            json={
                "binding_version": "rotation_1234567890",
                "proxy": proxy,
                "instances": ["earnfm-proxy"],
            },
        )

    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "binding_version": "rotation_1234567890",
        "proxy_id": 17,
        "observed_exit_ip": "8.8.8.8",
        "applied_instances": ["earnfm-proxy"],
        "config_sha256": "a" * 64,
    }
    assert "secret-pass" not in resp.text
    assert "proxy-user" not in resp.text
    probe.assert_awaited_once_with(proxy, worker_api._PROXY_BINDING_PROBE_TARGETS)
    to_thread.assert_awaited_once_with(apply, ["earnfm-proxy"], proxy, "rotation_1234567890")


def test_worker_proxy_binding_apply_rejects_empty_version_without_touching_runtime():
    from app import worker_api

    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    worker_api.app.router.lifespan_context = noop_lifespan
    with (
        patch.object(worker_api, "_verify_api_key", lambda _request: None),
        patch.object(worker_api.orchestrator, "apply_proxy_binding_batch") as apply,
        TestClient(worker_api.app, raise_server_exceptions=False) as client,
    ):
        resp = client.post(
            "/api/egress/bindings/apply",
            json={
                "binding_version": "",
                "proxy": {"proxy_id": 17, "host": "proxy.example.com", "port": 1080},
                "instances": ["earnfm-proxy"],
            },
        )

    assert resp.status_code == 422
    apply.assert_not_called()


def test_worker_proxy_binding_apply_does_not_touch_sidecars_when_local_probe_fails():
    from app import worker_api

    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    worker_api.app.router.lifespan_context = noop_lifespan
    with (
        patch.object(worker_api, "_verify_api_key", lambda _request: None),
        patch.object(
            worker_api,
            "_probe_proxy_targets",
            new_callable=AsyncMock,
            return_value={"ok": False, "observed_exit_ip": "", "results": [{"ok": False, "status_code": 0}]},
        ),
        patch.object(worker_api.orchestrator, "apply_proxy_binding_batch") as apply,
        TestClient(worker_api.app, raise_server_exceptions=False) as client,
    ):
        resp = client.post(
            "/api/egress/bindings/apply",
            json={
                "binding_version": "rotation_1234567890",
                "proxy": {
                    "proxy_id": 17,
                    "host": "proxy.example.com",
                    "port": 1080,
                    "username": "proxy-user",
                    "password": "secret-pass",
                },
                "instances": ["earnfm-proxy"],
            },
        )

    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "proxy_unreachable_from_worker"
    assert "secret-pass" not in resp.text
    assert "proxy-user" not in resp.text
    apply.assert_not_called()


def test_worker_proxy_binding_ack_uses_exit_ip_observed_through_candidate():
    from app import worker_api

    class Response:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = '{"ip":"8.8.4.4"}'

        @staticmethod
        def json():
            return {"ip": "8.8.4.4"}

    class ProxyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _target, headers):
            assert headers["user-agent"] == "Mozilla/5.0"
            return Response()

    with patch.object(worker_api.httpx, "AsyncClient", return_value=ProxyClient()):
        result = asyncio.run(
            worker_api._probe_proxy_targets(
                {"host": "proxy.example.com", "port": 1080, "protocol": "socks5"},
                worker_api._PROXY_BINDING_PROBE_TARGETS,
            )
        )

    assert result["ok"] is True
    assert result["observed_exit_ip"] == "8.8.4.4"


def test_worker_proxy_binding_probe_requires_an_observed_exit_ip():
    from app import worker_api

    class Response:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = '{"ip":"not-a-public-ip"}'

        @staticmethod
        def json():
            return {"ip": "not-a-public-ip"}

    class ProxyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _target, headers):
            return Response()

    with patch.object(worker_api.httpx, "AsyncClient", return_value=ProxyClient()):
        result = asyncio.run(
            worker_api._probe_proxy_targets(
                {"host": "proxy.example.com", "port": 1080, "protocol": "socks5"},
                worker_api._PROXY_BINDING_PROBE_TARGETS,
            )
        )

    assert result["ok"] is False
    assert result["observed_exit_ip"] == ""


def test_worker_proxy_binding_finalize_returns_redacted_result():
    from app import worker_api

    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    worker_api.app.router.lifespan_context = noop_lifespan
    with (
        patch.object(worker_api, "_verify_api_key", lambda _request: None),
        patch.object(worker_api.orchestrator, "finalize_proxy_binding_batch") as finalize,
        patch.object(
            worker_api.asyncio,
            "to_thread",
            new_callable=AsyncMock,
            return_value={"finalized_instances": ["earnfm-proxy"], "action": "confirmed"},
        ) as to_thread,
        TestClient(worker_api.app, raise_server_exceptions=False) as client,
    ):
        resp = client.post(
            "/api/egress/bindings/finalize",
            json={
                "binding_version": "rotation_1234567890",
                "instances": ["earnfm-proxy"],
                "commit": True,
            },
        )

    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "binding_version": "rotation_1234567890",
        "action": "confirmed",
        "finalized_instances": ["earnfm-proxy"],
    }
    to_thread.assert_awaited_once_with(finalize, ["earnfm-proxy"], "rotation_1234567890", commit=True)
