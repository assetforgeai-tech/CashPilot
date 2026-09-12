import pytest
from unittest.mock import AsyncMock

from app.provider_topology import plan_provider_nodes
from app import main


def test_dedicated_direct_provider_cannot_use_generic_planner():
    with pytest.raises(ValueError, match="dedicated planner"):
        plan_provider_nodes(7, "mysterium", 2)


def test_plan_carries_bootstrap_network_contract():
    plan = plan_provider_nodes(7, "earnfm", [{
        "slot_id": "ipv4-001",
        "public_ip": "198.51.100.1",
        "docker_network": "cashpilot-direct-ipv4-001",
        "route_ready": True,
    }], mode="direct")[0]
    assert plan.network == "cashpilot-direct-ipv4-001"


def test_both_plans_direct_then_proxy_for_each_slot():
    slots = ["ipv4-002", "ipv4-001"]
    plans = plan_provider_nodes(7, "earnfm", slots)
    assert [(p.mode, p.slot_id) for p in plans] == [
        ("direct", "ipv4-001"),
        ("proxy", "ipv4-001"),
        ("direct", "ipv4-002"),
        ("proxy", "ipv4-002"),
    ]


def test_proxy_only_can_select_one_mode_and_rejects_invalid_input():
    plans = plan_provider_nodes(7, "iproyal", 2, mode="proxy")
    assert len(plans) == 2
    assert all(p.mode == "proxy" for p in plans)
    with pytest.raises(ValueError, match="does not support direct"):
        plan_provider_nodes(7, "iproyal", 1, mode="direct")


def test_manual_provider_cannot_auto_plan():
    with pytest.raises(ValueError, match="manual-only"):
        plan_provider_nodes(7, "wipter", 1)


def test_unknown_provider_and_bad_slots_fail_closed():
    with pytest.raises(ValueError, match="unknown provider"):
        plan_provider_nodes(7, "missing", 1)
    with pytest.raises(ValueError, match="invalid public IPv4 slot"):
        plan_provider_nodes(7, "earnapp", ["bad-slot"])


@pytest.mark.asyncio
async def test_slot_proxy_uses_exclusive_provider_instance_lease(monkeypatch):
    lease = {"proxy_id": 9, "exit_ip": "203.0.113.9"}
    scoped = AsyncMock(return_value=lease)
    monkeypatch.setattr(main.database, "lease_proxy_for_provider_instance", scoped)
    result = await main._proxy_for_provider_instance(7, "earnfm", "earnfm-proxy-w7-ipv4-001")
    assert result == lease
    scoped.assert_awaited_once_with(
        "earnfm", 7, "earnfm-proxy-w7-ipv4-001", required_ip_type="residential"
    )
