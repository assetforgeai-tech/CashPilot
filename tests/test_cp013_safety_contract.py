"""CP-013 fatal-safety and slot-reconciliation contracts."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, patch

from app import main
from app.provider_topology import ProviderNodePlan, reconcile_provider_slots
from app.rollout_safety import RolloutSafetyViolation, classify_rollout_exception, classify_rollout_result


def test_explicit_egress_mismatch_halts_the_round():
    assessment = classify_rollout_result(
        {
            "status": "failed",
            "safety": {"egress_mismatch": True},
        }
    )

    assert assessment.stop_round is True
    assert assessment.code == "egress_mismatch"


def test_ordinary_provider_failure_does_not_halt_the_round():
    assessment = classify_rollout_result({"status": "failed", "failed": 1})

    assert assessment.stop_round is False
    assert assessment.code == "ordinary_failure"


def test_typed_safety_exception_is_redacted_to_stable_code():
    error = classify_rollout_exception(RolloutSafetyViolation("direct_fallback"))

    assert error.stop_round is True
    assert error.code == "direct_fallback"


def test_unstructured_provider_message_does_not_guess_safety():
    error = classify_rollout_exception(RuntimeError("token=secret direct_fallback_detected"))

    assert error.stop_round is False
    assert error.code == "ordinary_failure"


def test_unknown_positive_safety_signal_fails_closed():
    error = classify_rollout_result({"safety": {"new_fatal_code": True}})

    assert error.stop_round is True
    assert error.code == "unclassified_safety"


def test_slot_reconciliation_reports_missing_and_unexpected_rows():
    plan = ProviderNodePlan(
        worker_id=7,
        provider_slug="earnfm",
        mode="direct",
        slot_id="ipv4-001",
        public_ip="198.51.100.10",
        public_ipv4_slot="ipv4-001",
    )
    unexpected = replace(plan, slot_id="ipv4-002")

    report = reconcile_provider_slots([plan], [{"instance_id": unexpected.instance_id, "status": "running"}])

    assert report["status"] == "attention"
    assert report["missing"] == [plan.instance_id]
    assert report["unexpected"] == [unexpected.instance_id]


def test_slot_reconciliation_preserves_blocked_capacity_as_pending():
    plan = ProviderNodePlan(
        worker_id=7,
        provider_slug="earnfm",
        mode="proxy",
        slot_id="proxy-001",
        deployable=False,
        blocked_reason="proxy_capacity_unavailable",
    )

    report = reconcile_provider_slots([plan], [])

    assert report["status"] == "pending"
    assert report["blocked"] == [plan.instance_id]


def test_slot_reconciliation_catches_duplicate_or_mismatched_identity():
    plan = ProviderNodePlan(
        worker_id=7,
        provider_slug="earnfm",
        mode="direct",
        slot_id="ipv4-001",
        public_ipv4_slot="ipv4-001",
    )
    row = {"instance_id": plan.instance_id, "status": "running", "slot_id": "ipv4-099"}

    report = reconcile_provider_slots([plan], [row, dict(row)])

    assert report["status"] == "attention"
    assert report["duplicates"] == [plan.instance_id]
    assert report["mismatched"] == [plan.instance_id]


def test_fatal_safety_result_stops_the_round_before_the_next_lane():
    async def run():
        main._AUTO_DEPLOY_ACTIVE.clear()
        main._EARNAPP_AUTO_DEPLOY_DONE.add(7)
        calls = []

        async def deploy(_worker_id, slug):
            calls.append(slug)
            return {"status": "failed", "safety": {"direct_fallback": True}}

        with (
            patch.object(main, "_auto_deploy_one", side_effect=deploy),
            patch.object(main.database, "record_rollout_outcome", AsyncMock()) as record,
            patch.object(main.database, "finish_rollout_round", AsyncMock()) as finish,
        ):
            await main._run_auto_deploy_sequence(7, {}, ["first", "second"], delay_seconds=0, run_id="run-1")

        assert calls == ["first"]
        assert record.await_args_list[-1].args[2:] == ("failed", "direct_fallback")
        finish.assert_not_awaited()

    asyncio.run(run())


def test_deploy_sequence_probes_each_lane_and_pending_does_not_fence():
    async def run():
        main._AUTO_DEPLOY_ACTIVE.clear()
        main._NKN_AUTO_DEPLOY_DONE.add(7)
        main._EARNAPP_AUTO_DEPLOY_DONE.add(7)
        deployed = {
            "first": {"status": "deployed", "instances": [{"instance_id": "first-001", "status": "running"}]},
            "second": {"status": "deployed", "instances": [{"instance_id": "second-001", "status": "running"}]},
        }
        calls = []
        outcomes = []

        async def deploy(_worker_id, slug):
            calls.append(slug)
            return deployed[slug]

        async def probe(_worker_id, method, path, *, json=None, timeout=30):
            assert method == "POST"
            assert path == "/api/providers/egress-probe"
            assert json["instances"]
            if json["instances"] == ["first-001"]:
                return {"results": []}
            return {
                "results": [
                    {
                        "instance_id": "second-001",
                        "running": True,
                        "probe_ok": True,
                        "observed_egress_ip": "198.51.100.2",
                    }
                ]
            }

        async def record(_run_id, slug, status, error_type=""):
            outcomes.append((slug, status, error_type))

        with (
            patch.object(main, "_auto_deploy_one", side_effect=deploy),
            patch.object(main, "_proxy_to_worker", side_effect=probe) as worker_call,
            patch.object(
                main.database,
                "list_provider_instances",
                AsyncMock(
                    side_effect=[
                        [{"instance_id": "first-001", "mode": "proxy"}],
                        [{"instance_id": "second-001", "mode": "proxy"}],
                    ]
                ),
            ),
            patch.object(
                main.database,
                "get_provider_instance_spec",
                AsyncMock(
                    side_effect=[
                        {"proxy_lease_id": "lease-1", "expected_egress_ip": "198.51.100.1"},
                        {"proxy_lease_id": "lease-2", "expected_egress_ip": "198.51.100.2"},
                    ]
                ),
            ),
            patch.object(
                main.database,
                "get_active_provider_proxy_lease",
                AsyncMock(
                    side_effect=[
                        {"id": 101, "exit_ip": "198.51.100.1"},
                        {"id": 102, "exit_ip": "198.51.100.2"},
                    ]
                ),
            ),
            patch.object(main.database, "record_rollout_outcome", side_effect=record),
            patch.object(main.database, "finish_rollout_round", AsyncMock()),
        ):
            await main._run_auto_deploy_sequence(7, {}, ["first", "second"], delay_seconds=0, run_id="run-1")

        assert calls == ["first", "second"]
        assert worker_call.await_count == 2
        assert ("first", "pending", "") in outcomes
        assert ("second", "started", "") in outcomes

    asyncio.run(run())


def test_probe_route_failure_fences_before_next_lane():
    async def run():
        main._AUTO_DEPLOY_ACTIVE.clear()
        main._NKN_AUTO_DEPLOY_DONE.add(7)
        main._EARNAPP_AUTO_DEPLOY_DONE.add(7)
        calls = []

        async def deploy(_worker_id, slug):
            calls.append(slug)
            return {"status": "deployed", "instances": [{"instance_id": "first-001", "status": "running"}]}

        with (
            patch.object(main, "_auto_deploy_one", side_effect=deploy),
            patch.object(
                main,
                "_proxy_to_worker",
                AsyncMock(
                    return_value={
                        "results": [
                            {
                                "instance_id": "first-001",
                                "running": False,
                                "probe_ok": False,
                                "observed_egress_ip": "",
                            }
                        ]
                    }
                ),
            ),
            patch.object(
                main.database,
                "list_provider_instances",
                AsyncMock(return_value=[{"instance_id": "first-001", "mode": "proxy"}]),
            ),
            patch.object(
                main.database,
                "get_provider_instance_spec",
                AsyncMock(return_value={"proxy_lease_id": "lease-1", "expected_egress_ip": "198.51.100.1"}),
            ),
            patch.object(
                main.database,
                "get_active_provider_proxy_lease",
                AsyncMock(return_value={"id": 101, "exit_ip": "198.51.100.1"}),
            ),
            patch.object(main.database, "record_rollout_outcome", AsyncMock()) as record,
            patch.object(main.database, "finish_rollout_round", AsyncMock()) as finish,
        ):
            await main._run_auto_deploy_sequence(7, {}, ["first", "second"], delay_seconds=0, run_id="run-1")

        assert calls == ["first"]
        assert record.await_args_list[-1].args[2:] == ("failed", "route_failure")
        finish.assert_not_awaited()

    asyncio.run(run())


def test_missing_authoritative_instance_stays_pending():
    async def run():
        main._AUTO_DEPLOY_ACTIVE.clear()
        main._NKN_AUTO_DEPLOY_DONE.add(7)
        main._EARNAPP_AUTO_DEPLOY_DONE.add(7)

        with (
            patch.object(
                main,
                "_auto_deploy_one",
                AsyncMock(
                    return_value={
                        "status": "deployed",
                        "instances": [{"instance_id": "first-001", "status": "running"}],
                    }
                ),
            ),
            patch.object(
                main,
                "_proxy_to_worker",
                AsyncMock(
                    return_value={
                        "results": [
                            {
                                "instance_id": "first-001",
                                "running": True,
                                "probe_ok": True,
                                "observed_egress_ip": "198.51.100.2",
                            }
                        ]
                    }
                ),
            ),
            patch.object(main.database, "list_provider_instances", AsyncMock(return_value=[])),
            patch.object(main.database, "record_rollout_outcome", AsyncMock()) as record,
            patch.object(main.database, "finish_rollout_round", AsyncMock()),
        ):
            await main._run_auto_deploy_sequence(7, {}, ["first", "second"], delay_seconds=0, run_id="run-1")

        assert record.await_args_list[-1].args[2:] == ("pending",)

    asyncio.run(run())
