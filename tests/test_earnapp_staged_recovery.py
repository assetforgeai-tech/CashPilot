from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.earnapp_staged_recovery import StagedReplacementError, run_staged_replacement


def test_staged_replacement_orders_verify_delete_remove_promote_then_cleanup():
    events: list[str] = []

    async def reserve():
        events.append("reserve")
        return {"proxy_id": 22}

    async def deploy(candidate):
        events.append("deploy")
        return {"runtime_id": "stage-node", "device_id": "sdk-mac-new"}

    async def verify(runtime, candidate):
        events.append("verify")
        return {
            "authenticated": True,
            "device_present": True,
            "online": True,
            "workload_state": "workload_verified",
        }

    async def delete_old():
        events.append("delete_old")
        return True

    async def remove_old():
        events.append("remove_old")
        return True

    async def promote(runtime, candidate):
        events.append("promote")
        return True

    async def cleanup(runtime):
        events.append("cleanup")

    assert asyncio.run(
        run_staged_replacement(
            reserve=reserve,
            deploy=deploy,
            verify=verify,
            delete_old=delete_old,
            remove_old=remove_old,
            promote=promote,
            cleanup=cleanup,
        )
    )
    assert events == ["reserve", "deploy", "verify", "delete_old", "remove_old", "promote"]


def test_staged_replacement_keeps_old_runtime_when_verification_fails():
    events: list[str] = []

    async def reserve():
        return {"proxy_id": 22}

    async def deploy(candidate):
        events.append("deploy")
        return {"runtime_id": "stage-node"}

    async def verify(runtime, candidate):
        events.append("verify")
        return {"online": False}

    async def cleanup(runtime):
        events.append("cleanup")

    async def forbidden():
        events.append("forbidden")
        return True

    try:
        asyncio.run(
            run_staged_replacement(
                reserve=reserve,
                deploy=deploy,
                verify=verify,
                delete_old=forbidden,
                remove_old=forbidden,
                promote=forbidden,
                cleanup=cleanup,
            )
        )
    except StagedReplacementError as exc:
        assert exc.stage == "verify"
    else:
        raise AssertionError("verification failure must abort replacement")
    assert events == ["deploy", "verify", "cleanup"]


def test_staged_replacement_does_not_remove_old_runtime_when_remote_delete_is_unconfirmed():
    events: list[str] = []

    async def reserve():
        return {"proxy_id": 22}

    async def deploy(candidate):
        events.append("deploy")
        return {"runtime_id": "stage-node"}

    async def verify(runtime, candidate):
        return {
            "authenticated": True,
            "device_present": True,
            "online": True,
            "workload_state": "workload_verified",
        }

    async def delete_old():
        events.append("delete_old")
        return False

    async def forbidden():
        events.append("forbidden")
        return True

    async def cleanup(runtime):
        events.append("cleanup")

    try:
        asyncio.run(
            run_staged_replacement(
                reserve=reserve,
                deploy=deploy,
                verify=verify,
                delete_old=delete_old,
                remove_old=forbidden,
                promote=forbidden,
                cleanup=cleanup,
            )
        )
    except StagedReplacementError as exc:
        assert exc.stage == "delete_old"
    else:
        raise AssertionError("unconfirmed remote deletion must abort replacement")
    assert events == ["deploy", "delete_old", "cleanup"]


def test_staged_replacement_persists_promoted_pending_when_promotion_ack_is_lost():
    events: list[str] = []
    state = {"state": "PREPARED"}

    async def reserve():
        events.append("reserve")
        return {"proxy_id": 22}

    async def deploy(candidate):
        events.append("deploy")
        return {"runtime_id": "stage-node", "device_id": "sdk-mac-new"}

    async def verify(runtime, candidate):
        events.append("verify")
        return {
            "authenticated": True,
            "device_present": True,
            "online": True,
            "workload_state": "workload_verified",
        }

    async def delete_old():
        events.append("delete_old")
        return True

    async def remove_old():
        events.append("remove_old")
        return True

    async def promote(runtime, candidate):
        events.append("promote")
        return False

    async def cleanup(runtime):
        events.append("cleanup")

    async def save_state(value):
        state.update(value)

    try:
        asyncio.run(
            run_staged_replacement(
                reserve=reserve,
                deploy=deploy,
                verify=verify,
                delete_old=delete_old,
                remove_old=remove_old,
                promote=promote,
                cleanup=cleanup,
                state=state,
                save_state=save_state,
            )
        )
    except StagedReplacementError as exc:
        assert exc.stage == "promote"
    else:
        raise AssertionError("promotion ACK loss must remain retryable")
    assert state["state"] == "PROMOTED_PENDING"
    assert "cleanup" not in events


def test_staged_replacement_resumes_from_persisted_stage_without_redeploying():
    events: list[str] = []
    state = {
        "state": "VERIFIED",
        "candidate": {"proxy_id": 22},
        "runtime": {"runtime_id": "stage-node", "device_id": "sdk-mac-new"},
    }

    async def forbidden(*args):
        events.append("forbidden")
        raise AssertionError("persisted replacement must not restart earlier stages")

    async def delete_old():
        events.append("delete_old")
        return True

    async def remove_old():
        events.append("remove_old")
        return True

    async def promote(runtime, candidate):
        events.append("promote")
        return True

    async def cleanup(runtime):
        events.append("cleanup")

    assert asyncio.run(
        run_staged_replacement(
            reserve=forbidden,
            deploy=forbidden,
            verify=forbidden,
            delete_old=delete_old,
            remove_old=remove_old,
            promote=promote,
            cleanup=cleanup,
            state=state,
        )
    )
    assert events == ["delete_old", "remove_old", "promote", "cleanup"]


def test_fault_injected_proxy_failure_exercises_the_real_replacement_order():
    """A disposable canary may simulate route failure without touching a live node."""
    events: list[str] = []
    fault = {"proxy_failed": True}

    async def reserve():
        events.append("reserve")
        return {"proxy_id": 23, "fault_injected": fault["proxy_failed"]}

    async def deploy(candidate):
        events.append("deploy")
        assert candidate["fault_injected"] is True
        return {"runtime_id": "disposable-stage", "device_id": "sdk-mac-new"}

    async def verify(runtime, candidate):
        events.append("verify")
        return {
            "authenticated": True,
            "device_present": True,
            "online": True,
            "workload_state": "workload_verified",
        }

    async def delete_old():
        events.append("delete_old")
        return True

    async def remove_old():
        events.append("remove_old")
        return True

    async def promote(runtime, candidate):
        events.append("promote")
        return True

    async def cleanup(runtime):
        events.append("cleanup")

    assert asyncio.run(
        run_staged_replacement(
            reserve=reserve,
            deploy=deploy,
            verify=verify,
            delete_old=delete_old,
            remove_old=remove_old,
            promote=promote,
            cleanup=cleanup,
        )
    )
    assert events == ["reserve", "deploy", "verify", "delete_old", "remove_old", "promote"]


def test_fault_injection_is_rejected_for_production_nodes():
    from app.earnapp_fault_injection import (
        FaultInjectionRejected,
        FaultInjectionRequest,
        failed_proxy_evidence,
    )

    request = FaultInjectionRequest(
        logical_node_id="earnapp-proxy-w118904-ipv4-003",
        worker_id=118904,
        nonce="0123456789abcdef",
        proxy_id=23,
    )
    with pytest.raises(FaultInjectionRejected):
        failed_proxy_evidence(request)


def test_fault_injection_emits_normal_fail_closed_health_evidence():
    from app.earnapp_fault_injection import FaultInjectionRequest, failed_proxy_evidence

    request = FaultInjectionRequest(
        logical_node_id="earnapp-disposable-w118904-rotation-01",
        worker_id=118904,
        nonce="0123456789abcdef",
        proxy_id=23,
    )
    evidence = failed_proxy_evidence(request)
    assert evidence["proxy_health"] == "unhealthy"
    assert evidence["reason"] == "fault_injected_proxy_failure"
    assert evidence["direct_fallback_blocked"] is True
    assert evidence["egress_ip"] is None


def test_fault_injection_drives_repeated_health_gate_before_rotation():
    from app.earnapp_fault_injection import (
        FaultInjectionRequest,
        run_repeated_failure_gate,
    )

    request = FaultInjectionRequest(
        logical_node_id="earnapp-disposable-w118904-rotation-01",
        worker_id=118904,
        nonce="0123456789abcdef",
        proxy_id=23,
    )
    samples: list[dict] = []

    async def record(evidence):
        samples.append(evidence)
        return True

    async def rotate(evidence):
        assert len(samples) == 3
        assert evidence["direct_fallback_blocked"] is True
        return True

    result = asyncio.run(run_repeated_failure_gate(request, record_health=record, rotate=rotate))
    assert result["failure_samples"] == 3
    assert result["rotation_requested"] is True


def test_fault_injection_api_rejects_canonical_production_slug():
    from app import main

    body = main.EarnAppFaultInjectionRequest(
        worker_id=118904,
        generation=1,
        device_id="sdk-mac-10fd4755ccd48550307249a49f86d445",
        proxy_id=12970,
        nonce="0123456789abcdef",
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            main.api_inject_disposable_earnapp_proxy_failure(
                None,
                "earnapp-proxy-w118904-ipv4-003",
                body,
                {},
            )
        )
    assert exc.value.status_code == 409


def test_fault_injection_api_uses_three_health_samples_then_real_rotation():
    from app import main

    node_id = "earnapp-disposable-w118904-rotation-01"
    body = main.EarnAppFaultInjectionRequest(
        worker_id=118904,
        generation=2,
        device_id="sdk-mac-0123456789abcdef0123456789abcdef",
        proxy_id=23,
        nonce="0123456789abcdef",
    )
    node = {
        "logical_node_id": node_id,
        "assigned_worker_id": 118904,
        "generation": 2,
        "device_id": body.device_id,
        "current_proxy_id": 23,
        "state": "ACTIVE",
    }
    with (
        patch.object(main.database, "get_earnapp_logical_node", AsyncMock(return_value=node)),
        patch.object(main.database, "record_earnapp_proxy_health", AsyncMock(return_value=True)) as record,
        patch.object(main, "_rotate_unhealthy_earnapp_node", AsyncMock(return_value=True)) as rotate,
    ):
        result = asyncio.run(main.api_inject_disposable_earnapp_proxy_failure(None, node_id, body, {}))
    assert result["failure_samples"] == 3
    assert result["rotation_requested"] is True
    assert record.await_count == 3
    rotate.assert_awaited_once_with(
        node_id,
        118904,
        generation=2,
        expected_proxy_id=23,
    )
