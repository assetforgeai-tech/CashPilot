from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

from app import main


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/api/deploy/earnfm", "headers": []})


def _common(monkeypatch, deploy):
    async def none(*_args, **_kwargs):
        return None

    async def config(*_args, **_kwargs):
        return {
            "earnfm_token": "token",
            "iproyal_collector_email": "a@b.com",
            "iproyal_collector_password": "pw",
        }

    async def slots(_worker_id):
        return [
            {
                "slot_id": "ipv4-001",
                "public_ip": "198.51.100.1",
                "docker_network": "cashpilot-direct-ipv4-001",
                "route_ready": True,
            },
            {
                "slot_id": "ipv4-002",
                "public_ip": "198.51.100.2",
                "docker_network": "cashpilot-direct-ipv4-002",
                "route_ready": True,
            },
        ]

    def close_spawn(coro):
        coro.close()

    monkeypatch.setattr(main.database, "get_deployment_spec", none)
    monkeypatch.setattr(main.database, "get_config", config)
    monkeypatch.setattr(main.database, "save_provider_instance", none)
    monkeypatch.setattr(main.database, "record_health_event", none)
    monkeypatch.setattr(main.database, "list_provider_instances", lambda **_: __import__("asyncio").sleep(0, result=[]))
    monkeypatch.setattr(main, "_worker_public_ip_slots", slots)
    monkeypatch.setattr(main, "_proxy_worker_deploy", deploy)
    monkeypatch.setattr(main, "_spawn", close_spawn)
    monkeypatch.setattr(
        main.database,
        "get_provider_proxy_capacity",
        AsyncMock(return_value=[{"available": 2}]),
    )


@pytest.mark.asyncio
async def test_direct_slot_uses_bootstrap_network_not_host(monkeypatch):
    specs = {}

    async def deploy(_worker_id, instance_id, spec):
        specs[instance_id] = spec
        return {"container_id": instance_id}

    _common(monkeypatch, deploy)
    result = await main.api_deploy(
        _request(), "earnfm", main.DeployRequest(env={}, mode="direct"), worker_id=7, _auth={"r": "owner"}
    )
    assert result["desired"] == 2
    assert result["pending_capacity"] == 0
    assert specs["earnfm-direct-w7-ipv4-001"]["network"] == "cashpilot-direct-ipv4-001"
    assert specs["earnfm-direct-w7-ipv4-002"]["network"] == "cashpilot-direct-ipv4-002"
    assert specs["earnfm-direct-w7-ipv4-001"]["topology"] == "slot_both"
    assert specs["earnfm-direct-w7-ipv4-001"]["lane"] == "direct"
    assert specs["earnfm-direct-w7-ipv4-001"]["expected_egress_ip"] == "198.51.100.1"


@pytest.mark.asyncio
async def test_proxy_slot_records_lane_lease_and_expected_egress(monkeypatch):
    specs = {}

    async def deploy(_worker_id, instance_id, spec):
        specs[instance_id] = spec
        return {"container_id": instance_id}

    _common(monkeypatch, deploy)
    monkeypatch.setattr(
        main,
        "_proxy_for_provider_instance",
        lambda *_args, **_kwargs: __import__("asyncio").sleep(
            0, result={"proxy_id": 41, "exit_ip": "203.0.113.41", "endpoint": "http://proxy.invalid:8080"}
        ),
    )
    result = await main.api_deploy(
        _request(), "earnfm", main.DeployRequest(env={}, mode="proxy"), worker_id=7, _auth={"r": "owner"}
    )
    assert result["running"] == 2
    spec = specs["earnfm-proxy-w7-ipv4-001"]
    assert spec["topology"] == "slot_both"
    assert spec["lane"] == "proxy"
    assert spec["proxy_lease_id"] == "41"
    assert spec["expected_egress_ip"] == "203.0.113.41"


@pytest.mark.asyncio
async def test_failed_slot_does_not_block_later_slot(monkeypatch):
    calls = []

    async def deploy(_worker_id, instance_id, _spec):
        calls.append(instance_id)
        if instance_id.endswith("ipv4-001"):
            raise RuntimeError("boom")
        return {"container_id": instance_id}

    _common(monkeypatch, deploy)
    result = await main.api_deploy(
        _request(), "earnfm", main.DeployRequest(env={}, mode="direct"), worker_id=7, _auth={"r": "owner"}
    )
    assert calls == ["earnfm-direct-w7-ipv4-001", "earnfm-direct-w7-ipv4-002"]
    assert result["desired"] == 2
    assert result["running"] == 1
    assert result["failed"] == 1
    assert result["pending_capacity"] == 0


@pytest.mark.asyncio
async def test_provider_plan_endpoint_is_read_only(monkeypatch):
    async def slots(_worker_id):
        return [{"slot_id": "ipv4-001", "public_ip": "198.51.100.1", "route_ready": True}]

    monkeypatch.setattr(main, "_worker_public_ip_slots", slots)
    monkeypatch.setattr(
        main.database,
        "get_provider_proxy_capacity",
        lambda **_: __import__("asyncio").sleep(0, result=[{"available": 1}]),
    )
    monkeypatch.setattr(main.database, "list_provider_instances", lambda **_: __import__("asyncio").sleep(0, result=[]))
    result = await main.api_plan_provider(
        _request(), "iproyal", main.ProviderPlanRequest(worker_id=7), _auth={"r": "owner"}
    )
    assert result["desired"] == 1
    assert result["plans"][0]["mode"] == "proxy"
    assert result["contract"]["proxy_required"] is True
    assert result["contract"]["proxy_fallback"] is False


@pytest.mark.asyncio
async def test_provider_plan_exposes_capacity_preflight(monkeypatch):
    async def slots(_worker_id, **_kwargs):
        return [{"slot_id": "ipv4-001", "public_ip": "198.51.100.1", "route_ready": True}]

    monkeypatch.setattr(main, "_worker_public_ip_slots", slots)
    monkeypatch.setattr(main.database, "list_provider_instances", lambda **_: __import__("asyncio").sleep(0, result=[]))
    monkeypatch.setattr(
        main.database,
        "get_worker",
        lambda _worker_id: __import__("asyncio").sleep(
            0,
            result={"system_info": '{"resources":{"cpu_cores":4}}'},
        ),
    )
    result = await main.api_plan_provider(
        _request(), "iproyal", main.ProviderPlanRequest(worker_id=7), _auth={"r": "owner"}
    )
    assert result["preflight"]["cpu_cores"] == 4
    assert result["preflight"]["public_ipv4_slots"] == 1


@pytest.mark.asyncio
async def test_slot_deploy_skips_existing_running_instance(monkeypatch):
    calls = []

    async def deploy(_worker_id, instance_id, _spec):
        calls.append(instance_id)
        return {"container_id": instance_id}

    _common(monkeypatch, deploy)
    monkeypatch.setattr(
        main.database,
        "list_provider_instances",
        lambda **_: __import__("asyncio").sleep(
            0,
            result=[
                {
                    "instance_id": "earnfm-direct-w7-ipv4-001",
                    "worker_id": 7,
                    "mode": "direct",
                    "status": "running",
                    "container_id": "cid-1",
                }
            ],
        ),
    )
    result = await main.api_deploy(
        _request(), "earnfm", main.DeployRequest(env={}, mode="direct"), worker_id=7, _auth={"r": "owner"}
    )
    assert calls == ["earnfm-direct-w7-ipv4-002"]
    assert result["skipped"] == 1
    assert result["running"] == 2
