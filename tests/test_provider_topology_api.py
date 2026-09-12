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
        "capacity_basis": {"direct": "public_ipv4_slot"},
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
