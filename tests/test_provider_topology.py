from unittest.mock import AsyncMock

import pytest

from app import main
from app.provider_topology import (
    build_capacity_preflight,
    plan_provider_nodes,
    summarize_provider_plan,
    topology_contract,
)


def test_instance_scoping_helpers_are_unique_per_lane_slot():
    from app.main import _mode_scoped_named_volumes, _standard_device_identity

    volumes = _mode_scoped_named_volumes({"provider-data": {"bind": "/data"}}, "proxy", "proxy-001")
    assert list(volumes) == ["provider-data-proxy-proxy-001"]
    worker = {"id": 7, "system_info": '{"egress_ip":"8.8.8.8"}'}
    first = _standard_device_identity(worker, "proxy", "worker", "proxy-001")
    second = _standard_device_identity(worker, "proxy", "worker", "proxy-002")
    assert first != second


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
    plans = plan_provider_nodes(7, "earnfm", slots, proxy_capacity=2)
    assert [(p.mode, p.slot_id) for p in plans] == [
        ("direct", "ipv4-001"),
        ("direct", "ipv4-002"),
        ("proxy", "proxy-001"),
        ("proxy", "proxy-002"),
    ]


def test_proxy_only_can_select_one_mode_and_rejects_invalid_input():
    plans = plan_provider_nodes(7, "iproyal", 2, mode="proxy", proxy_capacity=2)
    assert len(plans) == 2
    assert all(p.mode == "proxy" for p in plans)
    with pytest.raises(ValueError, match="does not support direct"):
        plan_provider_nodes(7, "iproyal", 1, mode="direct")


def test_proxy_only_requires_bootstrap_public_ipv4_cardinality():
    plans = plan_provider_nodes(7, "iproyal", [], mode="proxy", proxy_capacity=3)
    assert plans == []


def test_unknown_proxy_capacity_never_infers_proxy_nodes_from_public_ipv4_slots():
    plans = plan_provider_nodes(7, "iproyal", ["ipv4-001", "ipv4-002"], mode="proxy")
    assert len(plans) == 2
    assert all(not plan.deployable and plan.blocked_reason == "proxy_capacity_unavailable" for plan in plans)


def test_hybrid_unknown_proxy_capacity_plans_only_the_direct_lane():
    plans = plan_provider_nodes(7, "earnfm", ["ipv4-001", "ipv4-002"])
    assert [(plan.mode, plan.slot_id) for plan in plans] == [
        ("direct", "ipv4-001"),
        ("direct", "ipv4-002"),
        ("proxy", "proxy-001"),
        ("proxy", "proxy-002"),
    ]
    assert all(not plan.deployable for plan in plans if plan.mode == "proxy")


def test_hybrid_plans_keep_direct_and_proxy_capacity_independent():
    plans = plan_provider_nodes(
        7,
        "earnfm",
        ["ipv4-001", "ipv4-002", "ipv4-003"],
        proxy_capacity=5,
    )
    assert sum(plan.mode == "direct" for plan in plans) == 3
    assert sum(plan.mode == "proxy" for plan in plans) == 3
    assert [plan.capacity_slot for plan in plans if plan.mode == "proxy"] == [
        "proxy-001",
        "proxy-002",
        "proxy-003",
    ]


def test_hybrid_default_target_is_one_proxy_lane_per_direct_slot():
    plans = plan_provider_nodes(7, "earnfm", ["ipv4-001", "ipv4-002"], proxy_capacity=5)
    assert [(plan.mode, plan.slot_id) for plan in plans] == [
        ("direct", "ipv4-001"),
        ("direct", "ipv4-002"),
        ("proxy", "proxy-001"),
        ("proxy", "proxy-002"),
    ]


def test_proxy_only_default_target_uses_bootstrap_slot_count():
    plans = plan_provider_nodes(7, "iproyal", ["ipv4-001", "ipv4-002"], mode="proxy", proxy_capacity=5)
    assert [plan.slot_id for plan in plans] == ["proxy-001", "proxy-002"]


def test_hybrid_plans_accept_explicit_lane_targets():
    plans = plan_provider_nodes(
        7,
        "earnfm",
        ["ipv4-001", "ipv4-002", "ipv4-003"],
        mode="both",
        proxy_capacity=5,
        direct_desired=2,
        proxy_desired=1,
    )
    assert [(plan.mode, plan.slot_id) for plan in plans] == [
        ("direct", "ipv4-001"),
        ("direct", "ipv4-002"),
        ("proxy", "proxy-001"),
    ]


def test_hybrid_lane_target_cannot_exceed_capacity():
    plans = plan_provider_nodes(
        7,
        "earnfm",
        ["ipv4-001"],
        mode="both",
        proxy_capacity=0,
        direct_desired=2,
        proxy_desired=1,
    )
    assert len(plans) == 3
    assert sum(plan.deployable for plan in plans if plan.mode == "direct") == 1
    assert sum(plan.deployable for plan in plans if plan.mode == "proxy") == 0


@pytest.mark.parametrize(
    ("provider", "mode", "target"),
    [("iproyal", "proxy", {"direct_desired": 1}), ("earnfm", "direct", {"proxy_desired": 1})],
)
def test_lane_target_for_unsupported_mode_fails_closed(provider, mode, target):
    with pytest.raises(ValueError, match="unsupported lane target"):
        plan_provider_nodes(7, provider, ["ipv4-001"], mode=mode, proxy_capacity=1, **target)


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
        proxy_capacity=1,
    )
    assert [(plan.mode, plan.deployable) for plan in plans] == [("direct", False), ("proxy", True)]


def test_summary_reports_deployable_and_lane_capacity():
    plans = plan_provider_nodes(
        7,
        "earnfm",
        [{"slot_id": "ipv4-001", "route_ready": False}],
        proxy_capacity=1,
    )
    summary = summarize_provider_plan(plans, [])
    assert summary["deployable"] == 1
    assert summary["pending_capacity"] == 1
    assert summary["lanes"] == {
        "direct": {"desired": 1, "deployable": 0, "running": 0},
        "proxy": {"desired": 1, "deployable": 1, "running": 0},
    }


def test_proxy_plan_exposes_independent_capacity_slot():
    plan = plan_provider_nodes(7, "iproyal", 1, mode="proxy", proxy_capacity=1)[0]
    assert plan.capacity_slot == "proxy-001"


def test_summary_marks_proxy_shortage_as_pending_capacity():
    plans = plan_provider_nodes(7, "iproyal", 3, mode="proxy", proxy_capacity=3)
    summary = summarize_provider_plan(plans, [], available_proxy_count=1)
    assert summary["desired"] == 3
    assert summary["deployable"] == 1
    assert summary["pending_proxy"] == 2
    assert summary["pending_capacity"] == 2
    assert summary["proxy_capacity"] == 1
    assert summary["proxy_capacity_shortfall"] == 2
    assert summary["capacity_target"] == 1


def test_summary_counts_existing_proxy_instances_without_calling_them_available():
    plans = plan_provider_nodes(7, "iproyal", [], mode="proxy", proxy_capacity=2, proxy_desired=2)
    summary = summarize_provider_plan(
        plans,
        [{"instance_id": "iproyal-proxy-w7-proxy-001", "status": "running"}],
        available_proxy_count=1,
        existing_proxy_count=1,
    )
    assert summary["capacity_target"] == 2
    assert summary["proxy_capacity"] == 1
    assert summary["lane_capacity"]["proxy"]["running"] == 1


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


def test_topology_contract_distinguishes_direct_proxy_and_hybrid_capacity():
    from app.provider_topology import topology_contract

    contract = topology_contract("nkn")
    assert {
        key: contract[key]
        for key in (
            "topology",
            "lanes",
            "capacity_basis",
            "lane_isolation",
            "direct_required",
            "proxy_required",
            "direct_fallback",
            "proxy_fallback",
        )
    } == {
        "topology": "dedicated",
        "lanes": ["direct"],
        "capacity_basis": {"direct": "dedicated_runtime"},
        "lane_isolation": False,
        "direct_required": True,
        "proxy_required": False,
        "direct_fallback": False,
        "proxy_fallback": False,
    }
    assert topology_contract("earnfm")["topology"] == "slot_both"
    assert topology_contract("earnfm")["direct_required"] is True
    assert topology_contract("earnfm")["proxy_required"] is True
    assert topology_contract("earnfm")["lanes"] == ["direct", "proxy"]
    assert topology_contract("earnfm")["capacity_basis"] == {"direct": "public_ipv4_slot", "proxy": "eligible_proxy"}
    assert topology_contract("earnfm")["lane_isolation"] is True
    earnapp_contract = topology_contract("earnapp")
    assert {
        key: earnapp_contract[key]
        for key in (
            "topology",
            "lanes",
            "capacity_basis",
            "lane_isolation",
            "direct_required",
            "proxy_required",
            "direct_fallback",
            "proxy_fallback",
        )
    } == {
        "topology": "slot_proxy",
        "lanes": ["proxy"],
        "capacity_basis": {"proxy": "eligible_proxy"},
        "lane_isolation": False,
        "direct_required": False,
        "proxy_required": True,
        "direct_fallback": False,
        "proxy_fallback": False,
    }
    assert topology_contract("wipter")["proxy_required"] is True


def test_topology_contract_exposes_single_lane_semantics():
    assert topology_contract("nkn")["lanes"] == ["direct"]
    assert topology_contract("earnapp")["lanes"] == ["proxy"]


def test_topology_contract_declares_capacity_basis_for_each_lane():
    assert topology_contract("nkn")["capacity_basis"] == {"direct": "dedicated_runtime"}
    assert topology_contract("earnapp")["capacity_basis"] == {"proxy": "eligible_proxy"}


def test_topology_contract_exposes_operational_policy():
    contract = topology_contract("earnapp")
    assert contract["auth_scope"] == "account"
    assert contract["account_sharing"] == "exclusive_account"
    assert contract["heartbeat"]["confirmations"] == 2
    assert contract["network_contract"]["proxy"]["fallback"] == "none"


@pytest.mark.parametrize(
    ("provider", "auth_scope", "sharing", "ownership"),
    [
        ("nkn", "wallet", "exclusive_wallet", "runtime_lease"),
        ("mysterium", "wallet", "exclusive_wallet", "runtime_lease"),
        ("earnapp", "account", "exclusive_account", "account_sticky"),
    ],
)
def test_provider_classes_declare_auth_and_ownership_scope(provider, auth_scope, sharing, ownership):
    from app.provider_runtime import catalog_runtime

    data = catalog_runtime(provider)
    assert data["auth_scope"] == auth_scope
    assert data["account_sharing"] == sharing
    assert data["egress_ownership_scope"] == ownership


def test_catalog_runtime_exposes_the_same_lane_contract():
    from app.provider_runtime import catalog_runtime

    data = catalog_runtime("earnfm")
    assert data["lanes"] == ["direct", "proxy"]
    assert data["capacity_basis"] == {"direct": "public_ipv4_slot", "proxy": "eligible_proxy"}
    assert data["lane_isolation"] is True


def test_catalog_runtime_exposes_auth_heartbeat_and_network_contract():
    from app.provider_runtime import catalog_runtime

    data = catalog_runtime("earnfm")
    assert data["auth_scope"] == "provider"
    assert data["account_sharing"] == "provider_scoped"
    assert data["heartbeat"]["interval_seconds"] == 300
    assert data["heartbeat"]["timeout_seconds"] == 900
    assert data["heartbeat"]["confirmations"] == 2
    assert data["network_contract"] == {
        "direct": {
            "fallback": "none",
            "dns": "provider_native",
            "ipv6": "explicit",
            "udp": "explicit",
            "fail_closed": True,
        },
        "proxy": {
            "fallback": "none",
            "dns": "tunneled",
            "ipv6": "disabled_or_tunneled",
            "udp": "explicit",
            "fail_closed": True,
        },
    }


def test_lane_summary_reports_free_capacity_without_collapsing_lanes():
    plans = plan_provider_nodes(7, "earnfm", 2, proxy_capacity=2)
    summary = summarize_provider_plan(plans, [], available_proxy_count=1)
    assert summary["lane_capacity"]["direct"]["free"] == 2
    assert summary["lane_capacity"]["proxy"]["free"] == 1
    assert summary["lane_capacity"]["proxy"]["blocked"] == 1
    assert summary["direct_capacity"] == 2
    assert summary["proxy_capacity"] == 1


def test_hybrid_summary_marks_partial_when_one_lane_is_blocked():
    plans = plan_provider_nodes(7, "earnfm", ["ipv4-001"], proxy_capacity=0)
    summary = summarize_provider_plan(plans, [])
    assert summary["topology_status"] == "partial"


def test_single_lane_summary_is_not_partial_when_capacity_is_ready():
    plans = plan_provider_nodes(7, "iproyal", [], mode="proxy", proxy_capacity=1)
    assert summarize_provider_plan(plans, [])["topology_status"] == "ready"


def test_direct_slot_identity_is_explicit_and_stable():
    plan = plan_provider_nodes(
        7,
        "earnfm",
        [{"slot_id": "ipv4-001", "public_ip": "198.51.100.1", "route_ready": True}],
        mode="direct",
    )[0]
    assert plan.capacity_slot == "ipv4-001"
    assert plan.lane == "direct"


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
