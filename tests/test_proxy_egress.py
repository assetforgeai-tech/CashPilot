"""Regression tests for the proxy-egress module."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

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

    assert proxy_egress.choose_mode(
        requested_mode="auto",
        service_udp="required",
        proxy={"protocol": "socks5", "udp_ok": False},
    ) == "direct"
    assert proxy_egress.choose_mode(
        requested_mode="auto",
        service_udp="required",
        proxy={"protocol": "socks5", "udp_ok": True},
    ) == "proxy"

def test_direct_provider_bypasses_fake_proxy():
    from app import proxy_egress

    assert proxy_egress.choose_mode(
        requested_mode="direct",
        service_udp="none",
        proxy={"protocol": "socks5", "udp_ok": True},
    ) == "direct"

def test_auto_chooses_direct_for_udp_when_proxy_cannot_udp():
    from app import proxy_egress

    assert proxy_egress.choose_mode(
        requested_mode="auto",
        service_udp="required",
        proxy={"protocol": "http"},
    ) == "direct"


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
