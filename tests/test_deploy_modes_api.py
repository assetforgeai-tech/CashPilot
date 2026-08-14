from __future__ import annotations

import pytest
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
        return {}

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
