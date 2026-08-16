from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import earnapp_qemu, main, orchestrator


def test_earnapp_qemu_command_boots_ubuntu_2404_with_random_hardware_and_guest_systemd():
    identity = earnapp_qemu.new_identity("earnapp-proxy")
    command = earnapp_qemu.render_qemu_command(identity)

    assert "ubuntu-24.04-server-cloudimg-amd64.img" in command
    assert "qemu-system-x86_64" in command
    assert f"-uuid {identity.uuid}" in command
    assert f"mac={identity.mac}" in command
    assert "file=earnapp.qcow2,if=none,id=drive0,format=qcow2" in command
    assert f"virtio-blk-pci,drive=drive0,serial={identity.serial}" in command
    assert "format=qcow2,serial=" not in command
    assert "manufacturer=CashPilot" in command
    assert "[ systemctl, enable, --now, earnapp-bootstrap.service ]" in command
    assert "systemctl restart earnapp earnapp_upgrader" in command
    assert "https://brightdata.com/static/earnapp/install.sh" in command
    assert "https://earnapp.com/dashboard/api/link_device" in command
    assert "\nCLOUD\ncat >meta-data" in command
    assert "\nMETA\ncloud-localds" in command


def test_deploy_raw_uses_earnapp_qemu_runtime_instead_of_provider_docker_image():
    client = MagicMock()
    client.containers.get.side_effect = orchestrator.NotFound("nope")
    container = MagicMock(short_id="abc123", id="container-id")
    client.containers.run.return_value = container

    with patch.object(orchestrator, "_get_client", return_value=client):
        result = orchestrator.deploy_raw(
            slug="earnapp-proxy",
            provider_slug="earnapp",
            image="legacy/ignored",
            host_runtime="qemu_systemd",
            deploy_credentials={
                "oauth_refresh_token": "refresh",
                "oauth_token": "token",
                "xsrf_token": "xsrf",
                "brd_sess_id": "sess",
                "cg_uuid": "uuid",
            },
            proxy={"host": "1.2.3.4", "port": 1080, "protocol": "socks5"},
        )

    assert result == "container-id"
    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["image"] == "ubuntu:24.04"
    assert kwargs["restart_policy"] == {"Name": "always"}
    assert kwargs["environment"]["OAUTH_TOKEN"] == "token"
    assert kwargs["labels"]["cashpilot.host-runtime"] == "qemu_systemd"
    assert kwargs["command"][:2] == ["/bin/bash", "-lc"]
    assert "qemu-system-x86_64" in kwargs["command"][2]
    assert kwargs["network_mode"] == "container:cashpilot-earnapp-proxy-egress"

@pytest.mark.asyncio
async def test_earnapp_proxy_rotation_releases_vietnam_assignment(monkeypatch):
    calls: list[tuple[str, int | None]] = []
    current = {"proxy_id": 2, "host": "vn.proxy", "port": 1080, "protocol": "socks5", "location": "Vietnam"}

    async def get_assignment(_worker_id: int):
        return current

    async def set_assignment(_worker_id: int, proxy_id: int | None, **_kwargs):
        nonlocal current
        calls.append(("set", proxy_id))
        current = None
        return True

    async def lease(_worker_id: int, **_kwargs):
        nonlocal current
        current = {"proxy_id": 845, "host": "sg.proxy", "port": 1080, "protocol": "socks5", "location": "Singapore"}
        return current

    monkeypatch.setattr(main.database, "get_worker_proxy_assignment", get_assignment)
    monkeypatch.setattr(main.database, "set_worker_proxy_assignment", set_assignment)
    monkeypatch.setattr(main.database, "lease_proxy_for_worker", lease)
    monkeypatch.setattr(main.database, "proxy_masked_for_provider", AsyncMock(return_value=False))
    monkeypatch.setattr(main.database, "mask_proxy_for_provider", AsyncMock())

    proxy = await main._proxy_for_worker_instance(8532, provider_slug="earnapp")

    assert proxy["proxy_id"] == 845
    assert calls == [("set", None)]

@pytest.mark.asyncio
async def test_earnapp_proxy_rotation_can_skip_large_vietnam_prefix(monkeypatch):
    leases = [{"proxy_id": i, "host": "vn.proxy", "port": 1080, "protocol": "socks5", "location": "Vietnam"} for i in range(1, 26)]
    leases.append({"proxy_id": 845, "host": "sg.proxy", "port": 1080, "protocol": "socks5", "location": "Singapore"})

    async def get_assignment(_worker_id: int):
        return None

    async def lease(_worker_id: int, **_kwargs):
        return leases.pop(0)

    monkeypatch.setattr(main.database, "get_worker_proxy_assignment", get_assignment)
    monkeypatch.setattr(main.database, "set_worker_proxy_assignment", AsyncMock(return_value=True))
    monkeypatch.setattr(main.database, "lease_proxy_for_worker", lease)
    monkeypatch.setattr(main.database, "proxy_masked_for_provider", AsyncMock(return_value=False))
    monkeypatch.setattr(main.database, "mask_proxy_for_provider", AsyncMock())

    proxy = await main._proxy_for_worker_instance(8532, provider_slug="earnapp")

    assert proxy["proxy_id"] == 845


@pytest.mark.asyncio
async def test_server_allows_earnapp_host_systemd_by_sending_qemu_runtime(monkeypatch):
    service = {
        "slug": "earnapp",
        "name": "EarnApp",
        "status": "active",
        "category": "bandwidth",
        "docker": {"image": "legacy/ignored", "env": [], "ports": [], "volumes": []},
        "deploy": {
            "deploy_surface": "host_systemd",
            "credentials": [
                {"key": "oauth_refresh_token", "arg": "oauth_refresh_token", "label": "refresh", "required": True},
                {"key": "oauth_token", "arg": "oauth_token", "label": "token", "required": True},
                {"key": "xsrf_token", "arg": "xsrf_token", "label": "xsrf", "required": True},
                {"key": "brd_sess_id", "arg": "brd_sess_id", "label": "session", "required": True},
                {"key": "cg_uuid", "arg": "cg_uuid", "label": "uuid", "required": True},
            ],
        },
    }
    config = {
        "earnapp_oauth_refresh_token": "refresh",
        "earnapp_oauth_token": "token",
        "earnapp_xsrf_token": "xsrf",
        "earnapp_brd_sess_id": "sess",
        "earnapp_cg_uuid": "uuid",
    }

    async def no_record(*_args, **_kwargs):
        return None

    deployed_specs = []

    async def fake_deploy(_worker_id: int, instance_slug: str, spec: dict):
        deployed_specs.append((instance_slug, spec))
        return {"container_id": "remote-id"}

    monkeypatch.setattr(main, "_require_owner", lambda _request: {"uid": 1, "r": "owner"})
    monkeypatch.setattr(main, "_resolve_worker_id", AsyncMock(return_value=7))
    monkeypatch.setattr(main.catalog, "get_service", lambda slug: service if slug == "earnapp" else None)
    monkeypatch.setattr(main.database, "get_config", AsyncMock(return_value=config))
    monkeypatch.setattr(main.database, "get_deployment_spec", no_record)
    monkeypatch.setattr(main.database, "get_worker", AsyncMock(return_value={"id": 7, "name": "vps-test-sing", "system_info": "{}"}))
    monkeypatch.setattr(main.database, "get_worker_proxy_assignment", AsyncMock(return_value=None))
    monkeypatch.setattr(main.database, "lease_proxy_for_worker", AsyncMock(return_value={"proxy_id": 1, "host": "1.2.3.4", "port": 1080, "protocol": "socks5", "location": "Singapore"}))
    monkeypatch.setattr(main.database, "proxy_masked_for_provider", AsyncMock(return_value=False))
    monkeypatch.setattr(main.database, "save_provider_instance", AsyncMock())
    monkeypatch.setattr(main.database, "record_health_event", AsyncMock())
    monkeypatch.setattr(main, "_proxy_worker_deploy", fake_deploy)
    monkeypatch.setattr(main, "_run_collection", AsyncMock())
    monkeypatch.setattr(main, "_run_post_deploy_automation", AsyncMock())
    monkeypatch.setattr(main, "_spawn", lambda coro: coro.close())

    resp = await main.api_deploy(
        main.Request({"type": "http", "method": "POST", "path": "/api/deploy/earnapp", "headers": []}),
        "earnapp",
        main.DeployRequest(env={}, mode="proxy"),
        _auth={"uid": 1, "r": "owner"},
    )

    assert resp["status"] == "deployed"
    assert deployed_specs[0][0] == "earnapp-proxy"
    assert deployed_specs[0][1]["host_runtime"] == "qemu_systemd"
    assert deployed_specs[0][1]["image"] == "ubuntu:24.04"

@pytest.mark.asyncio
async def test_earnapp_deploy_uses_account_pool_when_available(monkeypatch):
    service = {
        "slug": "earnapp",
        "name": "EarnApp",
        "status": "active",
        "category": "bandwidth",
        "docker": {"image": "legacy/ignored", "env": [], "ports": [], "volumes": []},
        "deploy": {
            "deploy_surface": "host_systemd",
            "credentials": [
                {"key": "oauth_refresh_token", "arg": "oauth_refresh_token", "label": "refresh", "required": True},
                {"key": "oauth_token", "arg": "oauth_token", "label": "token", "required": True},
                {"key": "xsrf_token", "arg": "xsrf_token", "label": "xsrf", "required": True},
                {"key": "brd_sess_id", "arg": "brd_sess_id", "label": "session", "required": True},
                {"key": "cg_uuid", "arg": "cg_uuid", "label": "uuid", "required": True},
            ],
        },
    }
    config = {
        "earnapp_oauth_refresh_token": "settings-refresh",
        "earnapp_oauth_token": "settings-token",
        "earnapp_xsrf_token": "settings-xsrf",
        "earnapp_brd_sess_id": "settings-sess",
        "earnapp_cg_uuid": "settings-uuid",
    }
    leased = {
        "account_name": "assetforgeai.gmail.com",
        "cookies": {
            "oauth_refresh_token": "pool-refresh",
            "oauth_token": "pool-token",
            "xsrf_token": "pool-xsrf",
            "brd_sess_id": "pool-sess",
            "cg_uuid": "pool-uuid",
        },
    }
    deployed_specs = []

    async def no_record(*_args, **_kwargs):
        return None

    async def fake_deploy(_worker_id: int, instance_slug: str, spec: dict):
        deployed_specs.append((instance_slug, spec))
        return {"container_id": "remote-id"}

    monkeypatch.setattr(main, "_resolve_worker_id", AsyncMock(return_value=7))
    monkeypatch.setattr(main.catalog, "get_service", lambda slug: service if slug == "earnapp" else None)
    monkeypatch.setattr(main.database, "get_config", AsyncMock(return_value=config))
    monkeypatch.setattr(main.database, "get_deployment_spec", no_record)
    monkeypatch.setattr(main.database, "get_worker_proxy_assignment", AsyncMock(return_value=None))
    monkeypatch.setattr(main.database, "lease_proxy_for_worker", AsyncMock(return_value={"proxy_id": 1, "host": "1.2.3.4", "port": 1080, "protocol": "socks5", "location": "Singapore"}))
    monkeypatch.setattr(main.database, "proxy_masked_for_provider", AsyncMock(return_value=False))
    monkeypatch.setattr(main.database, "lease_earnapp_account", AsyncMock(return_value=leased))
    monkeypatch.setattr(main.database, "save_provider_instance", AsyncMock())
    monkeypatch.setattr(main.database, "record_health_event", AsyncMock())
    monkeypatch.setattr(main, "_proxy_worker_deploy", fake_deploy)
    monkeypatch.setattr(main, "_run_collection", AsyncMock())
    monkeypatch.setattr(main, "_run_post_deploy_automation", AsyncMock())
    monkeypatch.setattr(main, "_spawn", lambda coro: coro.close())

    await main.api_deploy(
        main.Request({"type": "http", "method": "POST", "path": "/api/deploy/earnapp", "headers": []}),
        "earnapp",
        main.DeployRequest(env={}, mode="proxy"),
        _auth={"uid": 1, "r": "owner"},
    )

    creds = deployed_specs[0][1]["deploy_credentials"]
    assert creds["oauth_token"] == "pool-token"
    assert creds["earnapp_account_name"] == "assetforgeai.gmail.com"

@pytest.mark.asyncio
async def test_earnapp_account_pool_allows_empty_settings_credentials(monkeypatch):
    service = {
        "slug": "earnapp",
        "name": "EarnApp",
        "status": "active",
        "category": "bandwidth",
        "docker": {"image": "legacy/ignored", "env": [], "ports": [], "volumes": []},
        "deploy": {
            "deploy_surface": "host_systemd",
            "credentials": [
                {"key": "oauth_refresh_token", "arg": "oauth_refresh_token", "label": "refresh", "required": True},
                {"key": "oauth_token", "arg": "oauth_token", "label": "token", "required": True},
                {"key": "xsrf_token", "arg": "xsrf_token", "label": "xsrf", "required": True},
                {"key": "brd_sess_id", "arg": "brd_sess_id", "label": "session", "required": True},
                {"key": "cg_uuid", "arg": "cg_uuid", "label": "uuid", "required": True},
            ],
        },
    }
    deployed_specs = []

    async def no_record(*_args, **_kwargs):
        return None

    async def fake_deploy(_worker_id: int, instance_slug: str, spec: dict):
        deployed_specs.append((instance_slug, spec))
        return {"container_id": "remote-id"}

    monkeypatch.setattr(main, "_resolve_worker_id", AsyncMock(return_value=7))
    monkeypatch.setattr(main.catalog, "get_service", lambda slug: service if slug == "earnapp" else None)
    monkeypatch.setattr(main.database, "get_config", AsyncMock(return_value={}))
    monkeypatch.setattr(main.database, "get_deployment_spec", no_record)
    monkeypatch.setattr(main.database, "get_worker_proxy_assignment", AsyncMock(return_value=None))
    monkeypatch.setattr(main.database, "lease_proxy_for_worker", AsyncMock(return_value={"proxy_id": 1, "host": "1.2.3.4", "port": 1080, "protocol": "socks5", "location": "Singapore"}))
    monkeypatch.setattr(main.database, "proxy_masked_for_provider", AsyncMock(return_value=False))
    monkeypatch.setattr(main.database, "lease_earnapp_account", AsyncMock(return_value={"account_name": "a@example.com", "cookies": {"oauth_token": "pool-token", "oauth_refresh_token": "r", "xsrf_token": "x", "brd_sess_id": "b", "cg_uuid": "c"}}))
    monkeypatch.setattr(main.database, "save_provider_instance", AsyncMock())
    monkeypatch.setattr(main.database, "record_health_event", AsyncMock())
    monkeypatch.setattr(main, "_proxy_worker_deploy", fake_deploy)
    monkeypatch.setattr(main, "_run_collection", AsyncMock())
    monkeypatch.setattr(main, "_run_post_deploy_automation", AsyncMock())
    monkeypatch.setattr(main, "_spawn", lambda coro: coro.close())

    await main.api_deploy(
        main.Request({"type": "http", "method": "POST", "path": "/api/deploy/earnapp", "headers": []}),
        "earnapp",
        main.DeployRequest(env={}, mode="proxy"),
        _auth={"uid": 1, "r": "owner"},
    )

    assert deployed_specs[0][1]["deploy_credentials"]["oauth_token"] == "pool-token"
