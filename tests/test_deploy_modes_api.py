from __future__ import annotations

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
    assert direct_env["DEVICE_NAME"] == "worker-1-direct"
    assert proxy_env["DEVICE_NAME"] == "worker-1-proxy"

@pytest.mark.asyncio
async def test_traffmonetizer_parallel_modes_get_separate_device_names(monkeypatch):
    specs: dict[str, dict] = {}

    async def fake_deploy(_worker_id: int, instance_slug: str, spec: dict) -> dict[str, str]:
        specs[instance_slug] = spec
        return {"container_id": f"{instance_slug}-cid"}

    async def noop(*_args, **_kwargs):
        return None

    async def config(*_args, **_kwargs):
        return {"traffmonetizer_token": "token"}

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
        _request("/api/deploy/traffmonetizer"),
        "traffmonetizer",
        main.DeployRequest(env={}, hostname="worker-1", mode="both"),
        worker_id=7,
        _auth={"r": "owner"},
    )

    direct_env = specs["traffmonetizer-direct"]["env"]
    proxy_env = specs["traffmonetizer-proxy"]["env"]
    assert direct_env["TRAFFMONETIZER_DEVICE_NAME"] == "worker-1-direct-tm"
    assert proxy_env["TRAFFMONETIZER_DEVICE_NAME"] == "worker-1-proxy-tm"
    assert "--device-name worker-1-direct-tm" in specs["traffmonetizer-direct"]["command"]
    assert "--device-name worker-1-proxy-tm" in specs["traffmonetizer-proxy"]["command"]

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
