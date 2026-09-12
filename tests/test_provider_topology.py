from unittest.mock import AsyncMock

import pytest

from app import main
from app.provider_topology import build_capacity_preflight, plan_provider_nodes, summarize_provider_plan


def test_dedicated_direct_provider_cannot_use_generic_planner():
    with pytest.raises(ValueError, match="dedicated planner"):
        plan_provider_nodes(7, "mysterium", 2)


def test_plan_carries_bootstrap_network_contract():
    plan = plan_provider_nodes(
        7,
        "earnfm",
        [
            {
                "slot_id": "ipv4-001",
                "public_ip": "198.51.100.1",
                "docker_network": "cashpilot-direct-ipv4-001",
                "route_ready": True,
            }
        ],
        mode="direct",
    )[0]
    assert plan.network == "cashpilot-direct-ipv4-001"
    assert plan.capacity_slot == "ipv4-001"


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


def test_summary_is_read_only_and_identifies_missing_retry_and_stale_rows():
    plans = plan_provider_nodes(7, "earnfm", 2, mode="direct")
    summary = summarize_provider_plan(
        plans,
        [
            {"instance_id": "earnfm-direct-w7-ipv4-001", "status": "running"},
            {"instance_id": "earnfm-direct-w7-ipv4-002", "status": "failed"},
            {"instance_id": "earnfm-direct-w7-ipv4-999", "status": "running"},
        ],
    )
    assert summary["desired"] == 2
    assert summary["running"] == 1
    assert summary["retry"] == ["earnfm-direct-w7-ipv4-002"]
    assert summary["missing"] == []
    assert summary["stale"] == ["earnfm-direct-w7-ipv4-999"]


def test_not_ready_slot_is_reported_without_becoming_silent_capacity():
    plans = plan_provider_nodes(
        7,
        "earnfm",
        [
            {"slot_id": "ipv4-001", "public_ip": "198.51.100.1", "route_ready": True},
            {"slot_id": "ipv4-002", "public_ip": "198.51.100.2", "route_ready": False},
        ],
        mode="direct",
    )
    summary = summarize_provider_plan(plans, [])
    assert summary["desired"] == 2
    assert summary["blocked_slots"] == ["ipv4-002"]
    assert summary["missing"] == ["earnfm-direct-w7-ipv4-001"]


def test_not_ready_direct_route_does_not_block_proxy_capacity():
    plans = plan_provider_nodes(
        7,
        "earnfm",
        [{"slot_id": "ipv4-001", "public_ip": "198.51.100.1", "route_ready": False}],
    )
    assert [(plan.mode, plan.deployable) for plan in plans] == [("direct", False), ("proxy", True)]


def test_summary_reports_deployable_and_lane_capacity():
    plans = plan_provider_nodes(
        7,
        "earnfm",
        [{"slot_id": "ipv4-001", "route_ready": False}],
    )
    summary = summarize_provider_plan(plans, [])
    assert summary["deployable"] == 1
    assert summary["pending_capacity"] == 1
    assert summary["lanes"] == {
        "direct": {"desired": 1, "deployable": 0, "running": 0},
        "proxy": {"desired": 1, "deployable": 1, "running": 0},
    }


def test_proxy_plan_exposes_independent_capacity_slot():
    plan = plan_provider_nodes(7, "iproyal", 1, mode="proxy")[0]
    assert plan.capacity_slot == "proxy-001"


def test_summary_marks_proxy_shortage_as_pending_capacity():
    plans = plan_provider_nodes(7, "iproyal", 3, mode="proxy")
    summary = summarize_provider_plan(plans, [], available_proxy_count=1)
    assert summary["desired"] == 3
    assert summary["deployable"] == 1
    assert summary["pending_proxy"] == 2
    assert summary["pending_capacity"] == 2
    assert summary["proxy_capacity"] == 1
    assert summary["proxy_capacity_shortfall"] == 2
    assert summary["capacity_target"] == 1


def test_capacity_preflight_reports_compute_disk_ports_slots_and_proxy_capacity():
    result = build_capacity_preflight(
        slots=[{"slot_id": "ipv4-001", "route_ready": True}, {"slot_id": "ipv4-002", "route_ready": False}],
        system_info={
            "resources": {"cpu_cores": 8, "memory": {"total_bytes": 16_000}},
            "disk": {"free_bytes": 99_000},
        },
        ports=["30000:30000/tcp", "30001:30001/udp"],
        available_proxy_count=3,
    )
    assert result == {
        "cpu_cores": 8,
        "memory_total_bytes": 16_000,
        "disk_free_bytes": 99_000,
        "ports": ["30000/tcp", "30001/udp"],
        "public_ipv4_slots": 2,
        "ready_public_ipv4_slots": 1,
        "proxy_capacity": 3,
    }


@pytest.mark.asyncio
async def test_slot_proxy_uses_exclusive_provider_instance_lease(monkeypatch):
    lease = {"proxy_id": 9, "exit_ip": "203.0.113.9"}
    scoped = AsyncMock(return_value=lease)
    monkeypatch.setattr(main.database, "lease_proxy_for_provider_instance", scoped)
    result = await main._proxy_for_provider_instance(7, "earnfm", "earnfm-proxy-w7-ipv4-001")
    assert result == lease
    scoped.assert_awaited_once_with("earnfm", 7, "earnfm-proxy-w7-ipv4-001", required_ip_type="residential")


@pytest.mark.asyncio
async def test_worker_slots_can_include_unready_capacity_for_generic_planning(monkeypatch):
    monkeypatch.setattr(
        main,
        "_proxy_to_worker",
        AsyncMock(
            return_value={
                "slots": [
                    {"slot_id": "ipv4-001", "public_ip": "198.51.100.1", "route_ready": True},
                    {"slot_id": "ipv4-002", "public_ip": "198.51.100.2", "route_ready": False},
                ]
            }
        ),
    )
    slots = await main._worker_public_ip_slots(7, include_unready=True)
    assert [slot["slot_id"] for slot in slots] == ["ipv4-001", "ipv4-002"]
