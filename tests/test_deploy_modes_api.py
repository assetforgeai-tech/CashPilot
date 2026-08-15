from __future__ import annotations

import re

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import main


def _request(path: str = "/api/deploy/bitping") -> Request:
    return Request({"type": "http", "method": "POST", "path": path, "headers": []})


@pytest.mark.asyncio
async def test_proxy_mode_attaches_proxy_and_direct_mode_does_not(monkeypatch):
    specs: dict[str, dict] = {}

    async def fake_deploy(_worker_id: int, instance_slug: str, spec: dict) -> dict[str, str]:
        specs[instance_slug] = spec
        return {"container_id": f"{instance_slug}-cid"}

    async def noop(*_args, **_kwargs):
        return None

    async def empty_config(*_args, **_kwargs):
        return {"bitping_email": "user@example.com", "bitping_password": "secret"}

    async def fake_proxy(_worker_id: int):
        return {"proxy_id": 9, "host": "1.2.3.4", "port": 1080, "protocol": "socks5"}

    def close_spawn(coro):
        coro.close()

    monkeypatch.setattr(main.database, "get_deployment_spec", noop)
    monkeypatch.setattr(main.database, "get_config", empty_config)
    monkeypatch.setattr(main.database, "save_provider_instance", noop)
    monkeypatch.setattr(main.database, "record_health_event", noop)
    monkeypatch.setattr(main, "_proxy_for_worker_instance", fake_proxy)
    monkeypatch.setattr(main, "_proxy_worker_deploy", fake_deploy)
    monkeypatch.setattr(main, "_spawn", close_spawn)

    await main.api_deploy(_request(), "bitping", main.DeployRequest(env={}, mode="both"), worker_id=7, _auth={"r": "owner"})

    assert set(specs) == {"bitping-direct", "bitping-proxy"}
    assert "proxy" not in specs["bitping-direct"]
    assert specs["bitping-direct"]["egress_mode"] == "direct"
    assert specs["bitping-proxy"]["proxy"]["proxy_id"] == 9
    assert specs["bitping-proxy"]["egress_mode"] == "proxy"
    assert specs["bitping-proxy"]["labels"]["cashpilot.provider"] == "bitping"

@pytest.mark.asyncio
async def test_parallel_modes_get_separate_named_volumes(monkeypatch):
    specs: dict[str, dict] = {}

    async def fake_deploy(_worker_id: int, instance_slug: str, spec: dict) -> dict[str, str]:
        specs[instance_slug] = spec
        return {"container_id": f"{instance_slug}-cid"}

    async def noop(*_args, **_kwargs):
        return None

    async def config(*_args, **_kwargs):
        return {"bitping_email": "user@example.com", "bitping_password": "secret"}

    async def proxy(_worker_id: int):
        return {"proxy_id": 9, "host": "1.2.3.4", "port": 1080, "protocol": "socks5"}

    def close_spawn(coro):
        coro.close()

    monkeypatch.setattr(main.database, "get_deployment_spec", noop)
    monkeypatch.setattr(main.database, "get_config", config)
    monkeypatch.setattr(main.database, "save_provider_instance", noop)
    monkeypatch.setattr(main.database, "record_health_event", noop)
    monkeypatch.setattr(main, "_proxy_for_worker_instance", proxy)
    monkeypatch.setattr(main, "_proxy_worker_deploy", fake_deploy)
    monkeypatch.setattr(main, "_spawn", close_spawn)

    await main.api_deploy(_request(), "bitping", main.DeployRequest(env={}, mode="both"), worker_id=7, _auth={"r": "owner"})

    assert "bitpingd-volume-direct" in specs["bitping-direct"]["volumes"]
    assert "bitpingd-volume-proxy" in specs["bitping-proxy"]["volumes"]

@pytest.mark.asyncio
async def test_proxyrack_parallel_modes_get_separate_uuid_and_device_names(monkeypatch):
    specs: dict[str, dict] = {}

    async def fake_deploy(_worker_id: int, instance_slug: str, spec: dict) -> dict[str, str]:
        specs[instance_slug] = spec
        return {"container_id": f"{instance_slug}-cid"}

    async def noop(*_args, **_kwargs):
        return None

    async def config(*_args, **_kwargs):
        return {"proxyrack_api_key": "api-key"}

    async def proxy(_worker_id: int):
        return {"proxy_id": 9, "host": "1.2.3.4", "port": 1080, "protocol": "socks5"}

    def close_spawn(coro):
        coro.close()

    monkeypatch.setattr(main.database, "get_deployment_spec", noop)
    monkeypatch.setattr(main.database, "get_config", config)
    monkeypatch.setattr(main.database, "save_provider_instance", noop)
    monkeypatch.setattr(main.database, "record_health_event", noop)
    monkeypatch.setattr(main, "_proxy_for_worker_instance", proxy)
    monkeypatch.setattr(main, "_proxy_worker_deploy", fake_deploy)
    monkeypatch.setattr(main, "_spawn", close_spawn)

    await main.api_deploy(
        _request("/api/deploy/proxyrack"),
        "proxyrack",
        main.DeployRequest(env={}, hostname="worker-1", mode="both"),
        worker_id=7,
        _auth={"r": "owner"},
    )

    direct_env = specs["proxyrack-direct"]["env"]
    proxy_env = specs["proxyrack-proxy"]["env"]
    assert direct_env["UUID"] != proxy_env["UUID"]
    assert re.fullmatch(r"\d{14}\.worker-1\.d", direct_env["DEVICE_NAME"])
    assert re.fullmatch(r"\d{14}\.worker-1\.p", proxy_env["DEVICE_NAME"])

@pytest.mark.asyncio
async def test_traffmonetizer_parallel_modes_get_separate_device_names(monkeypatch):
    specs: dict[str, dict] = {}
    order: list[str] = []
    sleeps: list[int] = []

    async def fake_deploy(_worker_id: int, instance_slug: str, spec: dict) -> dict[str, str]:
        specs[instance_slug] = spec
        order.append(instance_slug)
        return {"container_id": f"{instance_slug}-cid"}

    async def noop(*_args, **_kwargs):
        return None

    async def config(*_args, **_kwargs):
        return {"traffmonetizer_token": "token"}

    async def proxy(_worker_id: int):
        return {"proxy_id": 9, "host": "1.2.3.4", "port": 1080, "protocol": "socks5"}

    async def fake_sleep(seconds: int):
        sleeps.append(seconds)

    def close_spawn(coro):
        coro.close()

    monkeypatch.setattr(main.database, "get_deployment_spec", noop)
    monkeypatch.setattr(main.database, "get_config", config)
    monkeypatch.setattr(main.database, "save_provider_instance", noop)
    monkeypatch.setattr(main.database, "record_health_event", noop)
    monkeypatch.setattr(main, "_proxy_for_worker_instance", proxy)
    monkeypatch.setattr(main, "_proxy_worker_deploy", fake_deploy)
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(main, "_spawn", close_spawn)

    await main.api_deploy(
        _request("/api/deploy/traffmonetizer"),
        "traffmonetizer",
        main.DeployRequest(env={}, hostname="worker-1", mode="both"),
        worker_id=7,
        _auth={"r": "owner"},
    )

    direct_env = specs["traffmonetizer-direct"]["env"]
    proxy_env = specs["traffmonetizer-proxy"]["env"]
    assert order == ["traffmonetizer-direct", "traffmonetizer-proxy"]
    assert sleeps == [300]
    assert re.fullmatch(r"\d{14}\.worker-1\.d", direct_env["TRAFFMONETIZER_DEVICE_NAME"])
    assert re.fullmatch(r"\d{14}\.worker-1\.p", proxy_env["TRAFFMONETIZER_DEVICE_NAME"])
    assert f"--device-name {direct_env['TRAFFMONETIZER_DEVICE_NAME']}" in specs["traffmonetizer-direct"]["command"]
    assert f"--device-name {proxy_env['TRAFFMONETIZER_DEVICE_NAME']}" in specs["traffmonetizer-proxy"]["command"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("slug", "mode", "expected_fields", "expected_suffix"),
    [
        ("iproyal", "proxy", ("IPROYALPAWNS_DEVICE_NAME", "IPROYALPAWNS_DEVICE_ID"), "p"),
        ("proxybase", "both", ("NAME",), None),
        ("proxyrack", "both", ("DEVICE_NAME",), None),
        ("traffmonetizer", "both", ("TRAFFMONETIZER_DEVICE_NAME",), None),
    ],
)
async def test_standard_device_identity_uses_worker_egress_ip(monkeypatch, slug, mode, expected_fields, expected_suffix):
    specs: dict[str, dict] = {}

    async def fake_deploy(_worker_id: int, instance_slug: str, spec: dict) -> dict[str, str]:
        specs[instance_slug] = spec
        return {"container_id": f"{instance_slug}-cid"}

    async def noop(*_args, **_kwargs):
        return None

    async def config(*_args, **_kwargs):
        return {
            "iproyal_email": "user@example.com",
            "iproyal_password": "secret",
            "proxies-sx_api_key": "api-key",
            "proxybase_deploy_access_token": "deploy-token",
            "proxyrack_api_key": "proxy-key",
            "traffmonetizer_token": "tm-token",
        }

    async def fake_proxy(_worker_id: int):
        return {"proxy_id": 9, "host": "1.2.3.4", "port": 1080, "protocol": "socks5"}

    async def fake_worker(_worker_id: int):
        return {"id": _worker_id, "name": "worker-1", "system_info": '{"egress_ip": "8.8.8.8"}'}

    async def fake_sleep(_seconds: int):
        return None

    def close_spawn(coro):
        coro.close()

    monkeypatch.setattr(main.database, "get_deployment_spec", noop)
    monkeypatch.setattr(main.database, "get_config", config)
    monkeypatch.setattr(main.database, "get_worker", fake_worker)
    monkeypatch.setattr(main.database, "save_provider_instance", noop)
    monkeypatch.setattr(main.database, "record_health_event", noop)
    monkeypatch.setattr(main, "_proxy_for_worker_instance", fake_proxy)
    monkeypatch.setattr(main, "_proxy_worker_deploy", fake_deploy)
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(main, "_spawn", close_spawn)

    await main.api_deploy(
        _request(f"/api/deploy/{slug}"),
        slug,
        main.DeployRequest(env={}, hostname="worker-1", mode=mode),
        worker_id=7,
        _auth={"r": "owner"},
    )

    suffix = expected_suffix or None
    assert specs
    for _instance_slug, spec in specs.items():
        env = spec["env"]
        for field in expected_fields:
            value = env[field]
            assert re.fullmatch(r"\d{14}\.8\.8\.8\.8\.[dp]", value)
            if suffix is not None:
                assert value.endswith(f".{suffix}")
        if slug == "proxyrack":
            assert re.fullmatch(r"[A-F0-9]{64}", env["UUID"])


@pytest.mark.asyncio
async def test_spide_device_registration_uses_standard_device_identity(monkeypatch):
    captured: list[dict[str, str]] = []

    async def config(key=None, *_args, **_kwargs):
        return "dash-token" if key == "spide_dashboard_token" else {"spide_dashboard_token": "dash-token"}

    async def fake_worker(_worker_id: int):
        return {"id": _worker_id, "name": "worker-1", "system_info": {"egress_ip": "8.8.8.8"}}

    async def fake_logs(_worker_id: int, _slug: str, *, lines: int = 200):
        return {"logs": f"Device key: {_slug.upper()}1234"}

    async def fake_register(token: str, device_key: str, *, title: str, base_url: str = "https://spide.network"):
        captured.append({"token": token, "device_key": device_key, "title": title, "base_url": base_url})
        return {"status": "ok"}

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(main.database, "get_config", config)
    monkeypatch.setattr(main.database, "get_worker", fake_worker)
    monkeypatch.setattr(main.database, "record_health_event", noop)
    monkeypatch.setattr(main, "_proxy_worker_logs", fake_logs)
    monkeypatch.setattr(main.provider_automation, "register_spide_device", fake_register)

    await main._run_post_deploy_automation("spide", 7, "worker-1", ["direct", "proxy"])

    assert [item["token"] for item in captured] == ["dash-token", "dash-token"]
    assert [item["device_key"] for item in captured] == ["SPIDE-DIRECT1234", "SPIDE-PROXY1234"]
    assert re.fullmatch(r"\d{14}\.8\.8\.8\.8\.d", captured[0]["title"])
    assert re.fullmatch(r"\d{14}\.8\.8\.8\.8\.p", captured[1]["title"])

@pytest.mark.asyncio
async def test_host_systemd_deploy_is_blocked(monkeypatch):
    async def noop(*_args, **_kwargs):
        return None

    async def config(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(main.database, "get_deployment_spec", noop)
    monkeypatch.setattr(main.database, "get_config", config)

    with pytest.raises(HTTPException) as exc:
        await main.api_deploy(_request(), "earnapp", main.DeployRequest(env={}, mode="direct"), worker_id=7, _auth={"r": "owner"})

    assert exc.value.status_code == 400
    assert "host_systemd" in str(exc.value.detail)

@pytest.mark.asyncio
async def test_host_systemd_service_is_marked_manual_only(monkeypatch):
    async def noop(*_args, **_kwargs):
        return []

    monkeypatch.setattr(main, "_require_auth_api", lambda _request: None)
    monkeypatch.setattr(main.database, "get_deployments", noop)
    monkeypatch.setattr(main.database, "list_provider_instances", noop)

    svc = await main.api_get_service(_request("/api/services/earnapp"), "earnapp")

    assert svc["deploy_surface"] == "host_systemd"
    assert svc["manual_only"] is True

@pytest.mark.asyncio
async def test_host_systemd_service_list_marks_manual_only(monkeypatch):
    async def noop(*_args, **_kwargs):
        return []

    monkeypatch.setattr(main, "_require_auth_api", lambda _request: None)
    monkeypatch.setattr(main.database, "get_deployments", noop)
    monkeypatch.setattr(main.database, "list_provider_instances", noop)

    services = await main.api_services_available(_request("/api/services/available"))
    earnapp = next(s for s in services if s["slug"] == "earnapp")

    assert earnapp["deploy_surface"] == "host_systemd"
    assert earnapp["manual_only"] is True
