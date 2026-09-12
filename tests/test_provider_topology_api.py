from unittest.mock import AsyncMock

import pytest

from app import main


@pytest.mark.asyncio
async def test_dedicated_plan_response_exposes_the_shared_topology_contract():
    result = await main.api_plan_provider(
        None,
        "nkn",
        main.ProviderPlanRequest(worker_id=7),
        {},
    )

    assert result["status"] == "manual"
    assert result["contract"] == {
        "topology": "dedicated",
        "lanes": ["direct"],
        "capacity_basis": {"direct": "dedicated_runtime"},
        "lane_isolation": False,
        "direct_required": True,
        "proxy_required": False,
        "direct_fallback": False,
        "proxy_fallback": False,
    }


@pytest.mark.asyncio
async def test_slots_unavailable_response_keeps_contract(monkeypatch):
    monkeypatch.setattr(main, "_worker_public_ip_slots", AsyncMock(side_effect=RuntimeError("offline")))

    result = await main.api_plan_provider(
        None,
        "earnfm",
        main.ProviderPlanRequest(worker_id=7),
        {},
    )

    assert result["status"] == "slots_unavailable"
    assert result["contract"]["topology"] == "slot_both"
    assert result["contract"]["direct_fallback"] is False


@pytest.mark.asyncio
async def test_proxy_only_plan_does_not_require_public_ipv4_slots(monkeypatch):
    monkeypatch.setattr(main, "_worker_public_ip_slots", AsyncMock(side_effect=RuntimeError("offline")))
    monkeypatch.setattr(
        main.database,
        "get_provider_proxy_capacity",
        AsyncMock(return_value=[{"available": 2}]),
    )
    monkeypatch.setattr(main.database, "list_provider_instances", AsyncMock(return_value=[]))
    result = await main.api_plan_provider(
        None,
        "iproyal",
        main.ProviderPlanRequest(worker_id=7, mode="proxy"),
        {},
    )
    assert result["status"] == "ready"
    assert result["desired"] == 2
    assert all(plan["mode"] == "proxy" for plan in result["plans"])


@pytest.mark.asyncio
async def test_proxy_only_plan_keeps_existing_leases_in_target_capacity(monkeypatch):
    monkeypatch.setattr(main, "_worker_public_ip_slots", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        main.database,
        "get_provider_proxy_capacity",
        AsyncMock(return_value=[{"available": 1}]),
    )
    monkeypatch.setattr(
        main.database,
        "list_provider_instances",
        AsyncMock(return_value=[{"instance_id": "iproyal-proxy-w7-proxy-001", "mode": "proxy", "status": "running"}]),
    )
    result = await main.api_plan_provider(
        None,
        "iproyal",
        main.ProviderPlanRequest(worker_id=7, mode="proxy"),
        {},
    )
    assert result["desired"] == 2
