from __future__ import annotations

import re

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import main


def _request(path: str = "/api/deploy/bitping") -> Request:
    return Request({"type": "http", "method": "POST", "path": path, "headers": []})

def _patch_alive_proxy_probe(monkeypatch):
    async def fake_probe(_host: str, _port: int, timeout: float = 5.0):
        return {"status": "alive", "protocol": "socks5"}

    monkeypatch.setattr("app.routers.proxies._probe_proxy_confirmed", fake_probe)


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

    async def fake_proxy(_worker_id: int, **_kwargs):
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
    assert sleeps == [600]
    assert re.fullmatch(r"\d{14}\.worker-1\.d", direct_env["TRAFFMONETIZER_DEVICE_NAME"])
    assert re.fullmatch(r"\d{14}\.worker-1\.p", proxy_env["TRAFFMONETIZER_DEVICE_NAME"])
    assert f"--device-name {direct_env['TRAFFMONETIZER_DEVICE_NAME']}" in specs["traffmonetizer-direct"]["command"]
    assert f"--device-name {proxy_env['TRAFFMONETIZER_DEVICE_NAME']}" in specs["traffmonetizer-proxy"]["command"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("slug", "mode", "expected_fields", "expected_suffix"),
    [
        ("iproyal", "proxy", ("IPROYALPAWNS_DEVICE_NAME", "IPROYALPAWNS_DEVICE_ID"), "p"),
        ("proxies-sx", "proxy", ("AGENT_NAME",), "p"),
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

    async def fake_proxy(_worker_id: int, **_kwargs):
        return {"proxy_id": 9, "host": "1.2.3.4", "port": 1080, "protocol": "socks5"}

    async def fake_worker(_worker_id: int):
        return {"id": _worker_id, "name": "worker-1", "system_info": '{"egress_ip": "8.8.8.8"}'}

    async def fake_sleep(_seconds: int):
        return None

    async def fake_logs(_worker_id: int, _slug: str, lines: int = 50):
        return {"logs": "running"}

    def close_spawn(coro):
        coro.close()

    monkeypatch.setattr(main.database, "get_deployment_spec", noop)
    monkeypatch.setattr(main.database, "get_config", config)
    monkeypatch.setattr(main.database, "get_worker", fake_worker)
    monkeypatch.setattr(main.database, "save_provider_instance", noop)
    monkeypatch.setattr(main.database, "record_health_event", noop)
    monkeypatch.setattr(main, "_proxy_for_worker_instance", fake_proxy)
    monkeypatch.setattr(main, "_proxy_worker_deploy", fake_deploy)
    monkeypatch.setattr(main, "_proxy_worker_logs", fake_logs)
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(main, "_spawn", close_spawn)
    if slug == "iproyal":
        _patch_alive_proxy_probe(monkeypatch)

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
            if slug == "proxies-sx":
                assert re.fullmatch(r"\d{14}-8-8-8-8-[dp]", value)
            else:
                assert re.fullmatch(r"\d{14}\.8\.8\.8\.8\.[dp]", value)
            if suffix is not None and slug == "proxies-sx":
                assert value.endswith(f"-{suffix}")
            elif suffix is not None:
                assert value.endswith(f".{suffix}")
        if slug == "proxyrack":
            assert re.fullmatch(r"[A-F0-9]{64}", env["UUID"])


@pytest.mark.asyncio
async def test_earnfm_direct_uses_host_network_and_eapp_hostname(monkeypatch):
    specs: dict[str, dict] = {}

    async def fake_deploy(_worker_id: int, instance_slug: str, spec: dict) -> dict[str, str]:
        specs[instance_slug] = spec
        return {"container_id": f"{instance_slug}-cid"}

    async def noop(*_args, **_kwargs):
        return None

    async def config(*_args, **_kwargs):
        return {"earnfm_token": "token"}

    def close_spawn(coro):
        coro.close()

    monkeypatch.setattr(main.database, "get_deployment_spec", noop)
    monkeypatch.setattr(main.database, "get_config", config)
    monkeypatch.setattr(main.database, "save_provider_instance", noop)
    monkeypatch.setattr(main.database, "record_health_event", noop)
    monkeypatch.setattr(main, "_proxy_worker_deploy", fake_deploy)
    monkeypatch.setattr(main, "_spawn", close_spawn)

    await main.api_deploy(
        _request("/api/deploy/earnfm"),
        "earnfm",
        main.DeployRequest(env={}, hostname="worker-1", mode="direct"),
        worker_id=7,
        _auth={"r": "owner"},
    )

    assert specs["earnfm-direct"]["env"]["GODEBUG"] == "http2client=0"
    assert specs["earnfm-direct"]["network_mode"] == "host"
    assert specs["earnfm-direct"]["hostname"] == "eapp"

@pytest.mark.asyncio
async def test_mysterium_rejects_proxy_mode(monkeypatch):
    specs: dict[str, dict] = {}

    async def fake_deploy(_worker_id: int, instance_slug: str, spec: dict) -> dict[str, str]:
        specs[instance_slug] = spec
        return {"container_id": f"{instance_slug}-cid"}

    async def noop(*_args, **_kwargs):
        return None

    async def config(*_args, **_kwargs):
        return {"mysterium_dashboard_password": "pw", "mysterium_mmn_api_key": "mmn"}

    def close_spawn(coro):
        coro.close()

    monkeypatch.setattr(main.database, "get_deployment_spec", noop)
    monkeypatch.setattr(main.database, "get_config", config)
    monkeypatch.setattr(main.database, "save_provider_instance", noop)
    monkeypatch.setattr(main.database, "record_health_event", noop)
    monkeypatch.setattr(main, "_proxy_worker_deploy", fake_deploy)
    monkeypatch.setattr(main, "_spawn", close_spawn)

    with pytest.raises(HTTPException):
        await main.api_deploy(
            _request("/api/deploy/mysterium"),
            "mysterium",
            main.DeployRequest(env={}, mode="both"),
            worker_id=7,
            _auth={"r": "owner"},
        )

    assert specs == {}


@pytest.mark.asyncio
async def test_iproyal_proxy_masks_ip_used_and_retries(monkeypatch):
    specs: list[dict] = []
    masked: list[tuple[int, str, str]] = []
    removed: list[str] = []
    proxy_ids = [1, 2]
    log_calls = 0

    async def fake_deploy(_worker_id: int, _instance_slug: str, spec: dict) -> dict[str, str]:
        specs.append(spec)
        return {"container_id": f"cid-{len(specs)}"}

    async def config(*_args, **_kwargs):
        return {"iproyal_email": "user@example.com", "iproyal_password": "secret"}

    async def fake_proxy(_worker_id: int, **kwargs):
        assert kwargs == {"provider_slug": "iproyal"}
        proxy_id = proxy_ids.pop(0)
        return {"proxy_id": proxy_id, "host": f"1.1.1.{proxy_id}", "port": 1080, "protocol": "socks5"}

    async def fake_worker(_worker_id: int):
        return {"id": _worker_id, "name": "worker-1", "system_info": '{"egress_ip": "8.8.8.8"}'}

    async def fake_logs(_worker_id: int, _slug: str, lines: int = 50):
        nonlocal log_calls
        log_calls += 1
        return {"logs": '{"error":"ip_used"}' if log_calls == 1 else "running"}

    async def fake_mask(proxy_id: int, provider_slug: str, reason: str):
        masked.append((proxy_id, provider_slug, reason))
        return True

    async def fake_command(_worker_id: int, command: str, slug: str, *, params=None):
        assert command == "remove"
        removed.append(slug)
        return {"status": "ok"}

    async def noop(*_args, **_kwargs):
        return None

    async def fake_sleep(_seconds: int):
        return None

    def close_spawn(coro):
        coro.close()

    monkeypatch.setattr(main.database, "get_deployment_spec", noop)
    monkeypatch.setattr(main.database, "get_config", config)
    monkeypatch.setattr(main.database, "get_worker", fake_worker)
    monkeypatch.setattr(main.database, "save_provider_instance", noop)
    monkeypatch.setattr(main.database, "record_health_event", noop)
    monkeypatch.setattr(main.database, "mask_proxy_for_provider", fake_mask)
    monkeypatch.setattr(main, "_proxy_for_worker_instance", fake_proxy)
    monkeypatch.setattr(main, "_proxy_worker_deploy", fake_deploy)
    monkeypatch.setattr(main, "_proxy_worker_logs", fake_logs)
    monkeypatch.setattr(main, "_proxy_worker_command", fake_command)
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(main, "_spawn", close_spawn)
    _patch_alive_proxy_probe(monkeypatch)

    response = await main.api_deploy(
        _request("/api/deploy/iproyal"),
        "iproyal",
        main.DeployRequest(env={}, hostname="worker-1", mode="proxy"),
        worker_id=7,
        _auth={"r": "owner"},
    )

    assert response["status"] == "deployed"
    assert [spec["proxy"]["proxy_id"] for spec in specs] == [1, 2]
    assert masked == [(1, "iproyal", "ip_used")]
    assert removed == ["iproyal-proxy"]

@pytest.mark.asyncio
async def test_iproyal_proxy_masks_tls_failure_and_retries(monkeypatch):
    specs: list[dict] = []
    masked: list[tuple[int, str, str]] = []
    proxy_ids = [4, 5]
    log_calls = 0

    async def fake_deploy(_worker_id: int, _instance_slug: str, spec: dict) -> dict[str, str]:
        specs.append(spec)
        return {"container_id": f"cid-{len(specs)}"}

    async def config(*_args, **_kwargs):
        return {"iproyal_email": "user@example.com", "iproyal_password": "secret"}

    async def fake_proxy(_worker_id: int, **kwargs):
        assert kwargs == {"provider_slug": "iproyal"}
        proxy_id = proxy_ids.pop(0)
        return {"proxy_id": proxy_id, "host": f"1.1.1.{proxy_id}", "port": 1080, "protocol": "socks5"}

    async def fake_logs(_worker_id: int, _slug: str, lines: int = 50):
        nonlocal log_calls
        log_calls += 1
        return {"logs": "tls: failed to verify certificate: x509: certificate has expired" if log_calls == 1 else "running"}

    async def fake_mask(proxy_id: int, provider_slug: str, reason: str):
        masked.append((proxy_id, provider_slug, reason))
        return True

    async def noop(*_args, **_kwargs):
        return None

    async def fake_sleep(_seconds: int):
        return None

    def close_spawn(coro):
        coro.close()

    monkeypatch.setattr(main.database, "get_deployment_spec", noop)
    monkeypatch.setattr(main.database, "get_config", config)
    monkeypatch.setattr(main.database, "save_provider_instance", noop)
    monkeypatch.setattr(main.database, "record_health_event", noop)
    monkeypatch.setattr(main.database, "mask_proxy_for_provider", fake_mask)
    monkeypatch.setattr(main, "_proxy_for_worker_instance", fake_proxy)
    monkeypatch.setattr(main, "_proxy_worker_deploy", fake_deploy)
    monkeypatch.setattr(main, "_proxy_worker_logs", fake_logs)
    monkeypatch.setattr(main, "_proxy_worker_command", noop)
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(main, "_spawn", close_spawn)
    _patch_alive_proxy_probe(monkeypatch)

    await main.api_deploy(
        _request("/api/deploy/iproyal"),
        "iproyal",
        main.DeployRequest(env={}, hostname="worker-1", mode="proxy"),
        worker_id=7,
        _auth={"r": "owner"},
    )

    assert [spec["proxy"]["proxy_id"] for spec in specs] == [4, 5]
    assert masked == [(4, "iproyal", "tls_failed")]

@pytest.mark.asyncio
async def test_iproyal_proxy_reprobes_and_updates_protocol_before_deploy(monkeypatch):
    specs: list[dict] = []
    updates: list[tuple[dict, dict | None]] = []

    async def fake_deploy(_worker_id: int, _instance_slug: str, spec: dict) -> dict[str, str]:
        specs.append(spec)
        return {"container_id": "cid"}

    async def config(*_args, **_kwargs):
        return {"iproyal_email": "user@example.com", "iproyal_password": "secret"}

    async def fake_proxy(_worker_id: int, **kwargs):
        assert kwargs == {"provider_slug": "iproyal"}
        return {"proxy_id": 7, "host": "1.1.1.7", "port": 1080, "protocol": "http"}

    async def fake_probe(host: str, port: int, timeout: float = 5.0):
        assert host == "1.1.1.7"
        assert port == 1080
        return {"status": "alive", "protocol": "socks5"}

    async def fake_update(results, *, protocols=None):
        updates.append((dict(results), dict(protocols or {})))
        return 1

    async def fake_logs(_worker_id: int, _slug: str, lines: int = 50):
        return {"logs": "running"}

    async def noop(*_args, **_kwargs):
        return None

    async def fake_sleep(_seconds: int):
        return None

    def close_spawn(coro):
        coro.close()

    monkeypatch.setattr(main.database, "get_deployment_spec", noop)
    monkeypatch.setattr(main.database, "get_config", config)
    monkeypatch.setattr(main.database, "save_provider_instance", noop)
    monkeypatch.setattr(main.database, "record_health_event", noop)
    monkeypatch.setattr(main.database, "update_proxy_pool_check_results", fake_update)
    monkeypatch.setattr(main, "_proxy_for_worker_instance", fake_proxy)
    monkeypatch.setattr(main, "_proxy_worker_deploy", fake_deploy)
    monkeypatch.setattr(main, "_proxy_worker_logs", fake_logs)
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(main, "_spawn", close_spawn)
    monkeypatch.setattr("app.routers.proxies._probe_proxy_confirmed", fake_probe)

    await main.api_deploy(
        _request("/api/deploy/iproyal"),
        "iproyal",
        main.DeployRequest(env={}, hostname="worker-1", mode="proxy"),
        worker_id=7,
        _auth={"r": "owner"},
    )

    assert specs[0]["proxy"]["protocol"] == "socks5"
    assert updates == [({7: "alive"}, {7: "socks5"})]

@pytest.mark.asyncio
async def test_iproyal_proxy_probe_failure_masks_and_rotates(monkeypatch):
    specs: list[dict] = []
    masked: list[tuple[int, str, str]] = []
    proxy_ids = [11, 12]

    async def fake_deploy(_worker_id: int, _instance_slug: str, spec: dict) -> dict[str, str]:
        specs.append(spec)
        return {"container_id": f"cid-{len(specs)}"}

    async def config(*_args, **_kwargs):
        return {"iproyal_email": "user@example.com", "iproyal_password": "secret"}

    async def fake_proxy(_worker_id: int, **kwargs):
        assert kwargs == {"provider_slug": "iproyal"}
        proxy_id = proxy_ids.pop(0)
        return {"proxy_id": proxy_id, "host": f"1.1.1.{proxy_id}", "port": 1080, "protocol": "socks5"}

    async def fake_probe(host: str, _port: int, timeout: float = 5.0):
        if host.endswith(".11"):
            return {"status": "dead", "protocol": ""}
        return {"status": "alive", "protocol": "socks5"}

    async def fake_mask(proxy_id: int, provider_slug: str, reason: str):
        masked.append((proxy_id, provider_slug, reason))
        return True

    async def fake_command(_worker_id: int, command: str, slug: str, *, params=None):
        assert command == "remove"
        assert slug == "iproyal-proxy"
        return {"status": "ok"}

    async def noop(*_args, **_kwargs):
        return None

    async def fake_sleep(_seconds: int):
        return None

    def close_spawn(coro):
        coro.close()

    monkeypatch.setattr(main.database, "get_deployment_spec", noop)
    monkeypatch.setattr(main.database, "get_config", config)
    monkeypatch.setattr(main.database, "save_provider_instance", noop)
    monkeypatch.setattr(main.database, "record_health_event", noop)
    monkeypatch.setattr(main.database, "mask_proxy_for_provider", fake_mask)
    monkeypatch.setattr(main, "_proxy_for_worker_instance", fake_proxy)
    monkeypatch.setattr(main, "_proxy_worker_deploy", fake_deploy)
    async def fake_logs(*_args, **_kwargs):
        return {"logs": "running"}

    monkeypatch.setattr(main, "_proxy_worker_logs", fake_logs)
    monkeypatch.setattr(main, "_proxy_worker_command", fake_command)
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(main, "_spawn", close_spawn)
    monkeypatch.setattr("app.routers.proxies._probe_proxy_confirmed", fake_probe)

    await main.api_deploy(
        _request("/api/deploy/iproyal"),
        "iproyal",
        main.DeployRequest(env={}, hostname="worker-1", mode="proxy"),
        worker_id=7,
        _auth={"r": "owner"},
    )

    assert [spec["proxy"]["proxy_id"] for spec in specs] == [12]
    assert masked == [(11, "iproyal", "proxy_probe_failed")]

@pytest.mark.asyncio
async def test_redeploy_uses_current_runtime_settings_over_recorded_env(monkeypatch):
    specs: list[dict] = []

    async def fake_deploy(_worker_id: int, _instance_slug: str, spec: dict) -> dict[str, str]:
        specs.append(spec)
        return {"container_id": "cid"}

    async def recorded(*_args, **_kwargs):
        return {
            "env": {
                "IPROYALPAWNS_EMAIL": "old@example.com",
                "IPROYALPAWNS_PASSWORD": "old-secret",
            },
            "command": "-email old@example.com -password old-secret",
        }

    async def config(*_args, **_kwargs):
        return {"iproyal_email": "new@example.com", "iproyal_password": "new-secret"}

    async def fake_proxy(_worker_id: int, **_kwargs):
        return {"proxy_id": 2, "host": "2.2.2.2", "port": 1080, "protocol": "socks5"}

    async def fake_logs(_worker_id: int, _slug: str, lines: int = 50):
        return {"logs": "running"}

    async def noop(*_args, **_kwargs):
        return None

    async def fake_sleep(_seconds: int):
        return None

    def close_spawn(coro):
        coro.close()

    monkeypatch.setattr(main.database, "get_deployment_spec", recorded)
    monkeypatch.setattr(main.database, "get_config", config)
    monkeypatch.setattr(main.database, "save_provider_instance", noop)
    monkeypatch.setattr(main.database, "record_health_event", noop)
    monkeypatch.setattr(main, "_proxy_for_worker_instance", fake_proxy)
    monkeypatch.setattr(main, "_proxy_worker_deploy", fake_deploy)
    monkeypatch.setattr(main, "_proxy_worker_logs", fake_logs)
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(main, "_spawn", close_spawn)
    _patch_alive_proxy_probe(monkeypatch)

    await main.api_deploy(
        _request("/api/deploy/iproyal"),
        "iproyal",
        main.DeployRequest(env={}, hostname="worker-1", mode="proxy"),
        worker_id=7,
        _auth={"r": "owner"},
    )

    assert specs[0]["env"]["IPROYALPAWNS_EMAIL"] == "new@example.com"
    assert "new@example.com" in specs[0]["command"]
    assert "old@example.com" not in specs[0]["command"]

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

def test_recorded_empty_cap_add_does_not_block_new_catalog_caps():
    merged, divergence = main._merge_recorded_spec(
        {"cap_add": ["NET_ADMIN"]},
        {"cap_add": None},
        {},
    )

    assert merged["cap_add"] == ["NET_ADMIN"]
    assert divergence == []

def test_recorded_cap_add_can_expand_to_catalog_superset():
    merged, divergence = main._merge_recorded_spec(
        {"cap_add": ["NET_ADMIN", "SETUID", "SETGID"]},
        {"cap_add": ["NET_ADMIN"]},
        {},
    )

    assert merged["cap_add"] == ["NET_ADMIN", "SETUID", "SETGID"]
    assert divergence == []
