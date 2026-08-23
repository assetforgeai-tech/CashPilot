from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app import database, main


def _slot(slot_id: str, public_ip: str) -> dict[str, object]:
    return {
        "slot_id": slot_id,
        "public_ip": public_ip,
        "private_ip": f"10.20.0.{4 + int(slot_id[-1])}",
        "route_ready": True,
    }


def _lease(wallet_id: int, client_id: str, public_ip: str) -> dict[str, object]:
    return {
        "id": wallet_id,
        "wallet_assignment_version": 1,
        "leased_to_client_id": client_id,
        "wallet_json": '{"Address":"NKNwalletAddress"}',
        "wallet_pswd": "password-value",
        "address": "NKNwalletAddress",
        "public_ip": public_ip,
    }


def test_nkn_deploy_runs_slots_sequentially_and_continues_after_failure():
    async def run():
        calls: list[str] = []

        async def lease(client_id, worker_id=None, public_ip=""):
            return _lease(int(client_id[-1]), client_id, public_ip)

        async def deploy(_worker_id, slot_id, _spec):
            calls.append(slot_id)
            if slot_id == "ipv4-001":
                raise RuntimeError("boom")
            return {"status": "deployed", "container_id": f"container-{slot_id}"}

        with (
            patch.object(database, "get_worker", AsyncMock(return_value={"id": 7, "client_id": "worker-a"})),
            patch.object(
                main,
                "_worker_public_ip_slots",
                AsyncMock(return_value=[_slot("ipv4-001", "8.8.8.8"), _slot("ipv4-002", "1.1.1.1")]),
            ),
            patch.object(database, "lease_nkn_wallet", AsyncMock(side_effect=lease)),
            patch.object(database, "get_provider_instance", AsyncMock(return_value=None)),
            patch.object(main, "_proxy_worker_nkn_deploy", AsyncMock(side_effect=deploy)),
            patch.object(database, "save_provider_instance", AsyncMock()) as save,
        ):
            result = await main._deploy_nkn_slots(7, beneficiary_address="NKNBeneficiaryAddress")
        assert calls == ["ipv4-001", "ipv4-002"]
        assert result["deployed"] == ["ipv4-002"]
        assert result["failed"] == ["ipv4-001"]
        assert save.await_count == 2

    asyncio.run(run())


def test_nkn_deploy_requires_beneficiary_before_leasing_wallet():
    async def run():
        with (
            patch.object(database, "lease_nkn_wallet", AsyncMock()) as lease,
            pytest.raises(main.HTTPException) as exc,
        ):
            await main._deploy_nkn_slots(7, beneficiary_address="")
        assert exc.value.status_code == 400
        lease.assert_not_awaited()

    asyncio.run(run())


def test_nkn_retry_reuses_existing_wallet_and_skips_already_running_assignment():
    async def run():
        lease = _lease(7, "worker-a:nkn:ipv4-001", "8.8.8.8")
        with (
            patch.object(database, "get_worker", AsyncMock(return_value={"id": 7, "client_id": "worker-a"})),
            patch.object(main, "_worker_public_ip_slots", AsyncMock(return_value=[_slot("ipv4-001", "8.8.8.8")])),
            patch.object(database, "lease_nkn_wallet", AsyncMock(return_value=lease)),
            patch.object(
                database,
                "get_provider_instance",
                AsyncMock(
                    return_value={
                        "status": "running",
                        "spec": {
                            "wallet_id": 7,
                            "wallet_assignment_version": 1,
                            "slot_id": "ipv4-001",
                            "runtime_backend": "lxd",
                            "lxd_cpu": 1,
                            "lxd_memory_mib": 1024,
                        },
                    }
                ),
            ),
            patch.object(main, "_proxy_worker_nkn_deploy", AsyncMock()) as deploy,
        ):
            result = await main._deploy_nkn_slots(7, beneficiary_address="NKNBeneficiaryAddress")
        assert result["skipped"] == ["ipv4-001"]
        deploy.assert_not_awaited()

    asyncio.run(run())


def test_nkn_legacy_instance_reads_the_legacy_encrypted_spec_before_skipping():
    async def run():
        lease = _lease(7, "worker-a:nkn:ipv4-001", "8.8.8.8")
        legacy_id = "nkn-direct-ipv4-001"
        scoped_id = main._nkn_record_instance_id(7, "ipv4-001")
        legacy = {"instance_id": legacy_id, "worker_id": 7, "status": "running", "spec_encrypted": "enc"}
        with (
            patch.object(database, "get_worker", AsyncMock(return_value={"id": 7, "client_id": "worker-a"})),
            patch.object(main, "_worker_public_ip_slots", AsyncMock(return_value=[_slot("ipv4-001", "8.8.8.8")])),
            patch.object(database, "lease_nkn_wallet", AsyncMock(return_value=lease)),
            patch.object(
                database,
                "get_provider_instance",
                AsyncMock(side_effect=lambda instance_id: None if instance_id == scoped_id else legacy),
            ),
            patch.object(
                database,
                "get_provider_instance_spec",
                AsyncMock(
                    return_value={
                        "wallet_id": 7,
                        "wallet_assignment_version": 1,
                        "slot_id": "ipv4-001",
                        "runtime_backend": "lxd",
                        "lxd_cpu": 1,
                        "lxd_memory_mib": 1024,
                    }
                ),
            ) as read_spec,
            patch.object(main, "_proxy_worker_nkn_deploy", AsyncMock()) as deploy,
        ):
            result = await main._deploy_nkn_slots(7, beneficiary_address="NKNBeneficiaryAddress")
        assert result["skipped"] == ["ipv4-001"]
        read_spec.assert_awaited_once_with(legacy_id)
        deploy.assert_not_awaited()

    asyncio.run(run())


def test_nkn_deploy_does_not_skip_a_legacy_docker_backend():
    async def run():
        lease = _lease(7, "worker-a:nkn:ipv4-001", "8.8.8.8")
        existing_spec = {
            "wallet_id": 7,
            "wallet_assignment_version": 1,
            "slot_id": "ipv4-001",
            "runtime_backend": "docker",
            "lxd_cpu": 1,
            "lxd_memory_mib": 1024,
        }
        with (
            patch.object(database, "get_worker", AsyncMock(return_value={"id": 7, "client_id": "worker-a"})),
            patch.object(main, "_worker_public_ip_slots", AsyncMock(return_value=[_slot("ipv4-001", "8.8.8.8")])),
            patch.object(database, "lease_nkn_wallet", AsyncMock(return_value=lease)),
            patch.object(
                database,
                "get_provider_instance",
                AsyncMock(return_value={"status": "running", "spec": existing_spec}),
            ),
            patch.object(
                main,
                "_proxy_worker_nkn_deploy",
                AsyncMock(return_value={"container_id": "cashpilot-nkn-ipv4-001"}),
            ) as deploy,
            patch.object(database, "save_provider_instance", AsyncMock()),
        ):
            result = await main._deploy_nkn_slots(
                7,
                beneficiary_address="NKNBeneficiaryAddress",
                lxd_settings={"cpu": 1, "memory_mib": 1024},
            )
        assert result["deployed"] == ["ipv4-001"]
        deploy.assert_awaited_once()

    asyncio.run(run())


def test_nkn_settings_drift_never_silently_resizes_or_redeploys_a_running_lxd_node():
    async def run():
        lease = _lease(7, "worker-a:nkn:ipv4-001", "8.8.8.8")
        existing_spec = {
            "wallet_id": 7,
            "wallet_assignment_version": 1,
            "slot_id": "ipv4-001",
            "runtime_backend": "lxd",
            "lxd_cpu": 2,
            "lxd_memory_mib": 2048,
        }
        with (
            patch.object(database, "get_worker", AsyncMock(return_value={"id": 7, "client_id": "worker-a"})),
            patch.object(main, "_worker_public_ip_slots", AsyncMock(return_value=[_slot("ipv4-001", "8.8.8.8")])),
            patch.object(database, "lease_nkn_wallet", AsyncMock(return_value=lease)),
            patch.object(
                database,
                "get_provider_instance",
                AsyncMock(return_value={"status": "running", "spec": existing_spec}),
            ),
            patch.object(main, "_proxy_worker_nkn_deploy", AsyncMock()) as deploy,
        ):
            result = await main._deploy_nkn_slots(
                7,
                beneficiary_address="NKNBeneficiaryAddress",
                lxd_settings={"cpu": 1, "memory_mib": 1024},
            )
        assert result["skipped"] == ["ipv4-001"]
        assert result["resource_drift"] == ["ipv4-001"]
        deploy.assert_not_awaited()

    asyncio.run(run())


def test_nkn_deploy_does_not_lease_or_attempt_unready_slots():
    async def run():
        with (
            patch.object(database, "get_worker", AsyncMock(return_value={"id": 7, "client_id": "worker-a"})),
            patch.object(
                main,
                "_worker_public_ip_slots",
                AsyncMock(
                    return_value=[
                        {**_slot("ipv4-001", "8.8.8.8"), "route_ready": False},
                        _slot("ipv4-002", "1.1.1.1"),
                    ]
                ),
            ),
            patch.object(database, "lease_nkn_wallet", AsyncMock(return_value=None)) as lease,
            patch.object(main, "_proxy_worker_nkn_deploy", AsyncMock()) as deploy,
        ):
            result = await main._deploy_nkn_slots(7, beneficiary_address="NKNBeneficiaryAddress")
        assert result["slots"] == 1
        lease.assert_awaited_once()
        assert lease.await_args.args[0].endswith("ipv4-002")
        deploy.assert_not_awaited()

    asyncio.run(run())


def test_auto_deploy_excludes_nkn_from_legacy_catalog_batch():
    services = [
        {"slug": "nkn", "status": "active", "docker": {"image": "nknorg/nkn:latest"}},
        {"slug": "earnfm", "status": "active", "docker": {"image": "img"}},
    ]
    assert main._auto_deploy_slugs(services) == ["earnfm"]


def test_nkn_auto_deploy_retries_after_a_failed_slot_on_the_next_stable_heartbeat():
    async def run():
        main._NKN_AUTO_DEPLOY_DONE.discard(7)
        main._WORKER_HEARTBEAT_STREAKS[7] = 2
        spawned = []

        def capture(coro):
            spawned.append(coro)
            return None

        deploy = AsyncMock(side_effect=[{"failed": ["ipv4-001"]}, {"failed": []}])
        with (
            patch.object(
                database,
                "get_config",
                AsyncMock(
                    return_value={
                        "nkn_beneficiary_address": "NKNBeneficiaryAddress",
                        "cashpilot_auto_deploy_enabled": "true",
                    }
                ),
            ),
            patch.object(
                database, "get_worker", AsyncMock(return_value={"id": 7, "name": "worker-a", "client_id": "worker-a"})
            ),
            patch.object(database, "get_deployments", AsyncMock(return_value=[])),
            patch.object(main, "_deploy_nkn_slots", deploy),
            patch.object(main, "_spawn", side_effect=capture),
            patch.object(main.catalog, "get_services", return_value=[]),
        ):
            await main._maybe_auto_deploy_after_heartbeat(7)
            await spawned.pop(0)
            await main._maybe_auto_deploy_after_heartbeat(7)
            await spawned.pop(0)

        assert deploy.await_count == 2
        assert 7 in main._NKN_AUTO_DEPLOY_DONE

    asyncio.run(run())
