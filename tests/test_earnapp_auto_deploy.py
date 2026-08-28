from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app import database, earnapp_accounts, earnapp_deploy, main


def _account(profile: str) -> dict[str, object]:
    return {
        "profile_key": profile,
        "account_name": f"{profile}@example.com",
        "email": f"{profile}@example.com",
        "auth_method": "google",
        "cookies": {
            "oauth-refresh-token": {"value": f"refresh-{profile}"},
            "xsrf-token": {"value": f"xsrf-{profile}"},
        },
    }


async def _seed_proxy(provider_id: int, suffix: int, country_code: str) -> int:
    (proxy_id,) = await database.upsert_proxy_endpoints_returning_ids(
        provider_id,
        [
            {
                "provider_proxy_id": f"proxy-{suffix}",
                "endpoint": f"10.0.0.{suffix}:{1000 + suffix}",
                "host": f"10.0.0.{suffix}",
                "port": 1000 + suffix,
                "protocol": "socks5",
                "username": f"user-{suffix}",
                "password": f"secret-{suffix}",
                "status": "alive",
                "exit_ip": f"198.51.100.{suffix}",
                "ip_type": "residential",
                "country_code": country_code,
            }
        ],
    )
    await database.update_proxy_endpoint_intelligence(
        proxy_id,
        {
            "ip_type": "residential",
            "ip_type_source": "test",
            "ip_type_confidence": "high",
            "country_code": country_code,
            "country_name": "Vietnam" if country_code == "VN" else "United States",
            "location_source": "test",
            "location_confidence": "high",
        },
    )
    await database.save_proxy_probe_result(
        proxy_id,
        profile="earnapp_wss",
        probe_status="alive",
        verdict="CID_SET",
        eligibility="eligible",
        reason="",
        exit_ip=f"198.51.100.{suffix}",
        latency_ms=20,
        probe_version="test",
    )
    return proxy_id


def test_planner_creates_one_deterministic_node_per_ready_public_ipv4_slot():
    slots = [
        {"slot_id": "ipv4-002", "public_ip": "203.0.113.2", "route_ready": True},
        {"slot_id": "ipv4-001", "public_ip": "203.0.113.1", "route_ready": True},
        {"slot_id": "ipv4-003", "public_ip": "203.0.113.3", "route_ready": False},
    ]

    plans = earnapp_deploy.plan_worker_nodes(7, slots)

    assert [plan.slot_id for plan in plans] == ["ipv4-001", "ipv4-002"]
    assert [plan.logical_node_id for plan in plans] == [
        "earnapp-proxy-w7-ipv4-001",
        "earnapp-proxy-w7-ipv4-002",
    ]


def test_legacy_canary_counts_against_worker_slot_capacity(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            await earnapp_accounts.import_account(_account("profile-a"))
            worker_id = await database.upsert_worker("worker-a", "worker-a", "http://worker-a")
            await database.assign_earnapp_account("earnapp-canary-test-sing-1", platform="macos")
            db = await database._get_db()
            await db.execute(
                "UPDATE earnapp_logical_nodes SET state='ACTIVE', assigned_worker_id=? WHERE logical_node_id=?",
                (worker_id, "earnapp-canary-test-sing-1"),
            )
            await db.commit()

            plans = await earnapp_deploy.target_worker_plans(
                worker_id,
                [{"slot_id": "ipv4-001", "public_ip": "203.0.113.1", "route_ready": True}],
            )

            assert plans == []

    asyncio.run(run())


def test_existing_deterministic_planned_node_stays_in_retry_queue(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            await earnapp_accounts.import_account(_account("profile-a"))
            worker_id = await database.upsert_worker("worker-a", "worker-a", "http://worker-a")
            node_id = f"earnapp-proxy-w{worker_id}-ipv4-001"
            await database.assign_earnapp_account(node_id)

            plans = await earnapp_deploy.target_worker_plans(
                worker_id,
                [{"slot_id": "ipv4-001", "public_ip": "203.0.113.1", "route_ready": True}],
            )

            assert [plan.logical_node_id for plan in plans] == [node_id]

    asyncio.run(run())


def test_first_node_inherits_its_accounts_existing_control_proxy(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account_id = await earnapp_accounts.import_account(_account("profile-a"))
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            control_proxy = await _seed_proxy(provider_id, 1, "VN")
            await _seed_proxy(provider_id, 2, "US")
            route = await database.lease_earnapp_account_control_proxy(account_id)
            assert route and route["proxy_id"] == control_proxy
            worker_id = await database.upsert_worker("worker-a", "worker-a", "http://worker-a")
            plan = earnapp_deploy.plan_worker_nodes(worker_id, 1)[0]

            prepared = await earnapp_deploy.prepare_node(plan, vn_platform_choice=lambda: "macos")

            assert prepared.proxy["proxy_id"] == control_proxy
            assert prepared.account_id == account_id
            assert (await database.get_earnapp_account_control_route(account_id)) is None

    asyncio.run(run())


def test_failed_assigned_deterministic_node_remains_in_retry_queue(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            await earnapp_accounts.import_account(_account("profile-a"))
            worker_id = await database.upsert_worker("worker-a", "worker-a", "http://worker-a")
            node_id = f"earnapp-proxy-w{worker_id}-ipv4-001"
            await database.assign_earnapp_account(node_id)
            db = await database._get_db()
            await db.execute(
                "UPDATE earnapp_logical_nodes SET assigned_worker_id=?, state='ACTIVE' WHERE logical_node_id=?",
                (worker_id, node_id),
            )
            await db.commit()
            await database.save_provider_instance(
                "earnapp",
                node_id,
                worker_id=worker_id,
                mode="proxy",
                status="failed",
                spec={"error": "canary failed"},
            )

            plans = await earnapp_deploy.target_worker_plans(
                worker_id,
                [{"slot_id": "ipv4-001", "public_ip": "203.0.113.1", "route_ready": True}],
            )

            assert [plan.logical_node_id for plan in plans] == [node_id]

    asyncio.run(run())


def test_prepare_node_derives_platform_from_proxy_country_and_persists_unique_identity(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            await earnapp_accounts.import_account(_account("profile-a"))
            await earnapp_accounts.import_account(_account("profile-b"))
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            vn_proxy = await _seed_proxy(provider_id, 1, "VN")
            us_proxy = await _seed_proxy(provider_id, 2, "US")
            worker_id = await database.upsert_worker("worker-a", "worker-a", "http://worker-a")
            plans = earnapp_deploy.plan_worker_nodes(
                worker_id,
                [
                    {"slot_id": "ipv4-001", "public_ip": "203.0.113.1", "route_ready": True},
                    {"slot_id": "ipv4-002", "public_ip": "203.0.113.2", "route_ready": True},
                ],
            )

            first = await earnapp_deploy.prepare_node(plans[0], vn_platform_choice=lambda: "ios")
            second = await earnapp_deploy.prepare_node(plans[1], vn_platform_choice=lambda: "macos")

            assert first.platform == "ios"
            assert first.proxy["proxy_id"] == vn_proxy
            assert second.platform == "ubuntu"
            assert second.proxy["proxy_id"] == us_proxy
            assert first.account_id != second.account_id
            assert first.device_id != second.device_id
            assert (await database.get_earnapp_logical_node(first.logical_node_id))["platform"] == "ios"
            assert (await database.get_earnapp_logical_node(second.logical_node_id))["platform"] == "ubuntu"

    asyncio.run(run())


def test_prepare_node_skips_proxy_without_canonical_country_metadata(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            await earnapp_accounts.import_account(_account("profile-a"))
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            unknown_proxy = await _seed_proxy(provider_id, 1, "")
            us_proxy = await _seed_proxy(provider_id, 2, "US")
            worker_id = await database.upsert_worker("worker-a", "worker-a", "http://worker-a")
            plan = earnapp_deploy.plan_worker_nodes(worker_id, 1)[0]

            prepared = await earnapp_deploy.prepare_node(plan)

            assert prepared.platform == "ubuntu"
            assert prepared.proxy["proxy_id"] == us_proxy
            assert prepared.proxy["proxy_id"] != unknown_proxy
            active = await database.get_active_provider_proxy_lease("earnapp", worker_id, plan.logical_node_id)
            assert active and active["proxy_id"] == us_proxy

    asyncio.run(run())


def test_verification_requires_observed_device_id_to_match_expected_identity():
    evidence = {
        "authenticated": True,
        "device_present": True,
        "online": True,
        "banned": False,
    }

    assert not earnapp_deploy._verification_ok(evidence, device_id="sdk-mac-00000000000000000000000000000001")


def test_verification_rejects_a_different_observed_device_id():
    evidence = {
        "authenticated": True,
        "device_present": True,
        "online": True,
        "banned": False,
        "device_id": "sdk-mac-00000000000000000000000000000002",
    }

    assert not earnapp_deploy._verification_ok(evidence, device_id="sdk-mac-00000000000000000000000000000001")


def test_verification_keeps_online_node_pending_until_usage_delta_is_observed():
    evidence = {
        "authenticated": True,
        "device_present": True,
        "online": True,
        "banned": False,
        "device_id": "sdk-mac-00000000000000000000000000000001",
        "workload_state": "online_pending_usage",
        "total_uptime": 18142,
        "earned_total": 0.0,
    }

    assert not earnapp_deploy._verification_ok(
        evidence,
        device_id="sdk-mac-00000000000000000000000000000001",
    )


def test_verification_accepts_exact_node_only_after_workload_delta_is_observed():
    evidence = {
        "authenticated": True,
        "device_present": True,
        "online": True,
        "banned": False,
        "device_id": "sdk-mac-00000000000000000000000000000001",
        "workload_state": "workload_verified",
        "workload_delta": {"bandwidth": 60000.0, "total_bandwidth": 60000.0, "earned_total": 0.0},
    }

    assert earnapp_deploy._verification_ok(
        evidence,
        device_id="sdk-mac-00000000000000000000000000000001",
    )


@pytest.mark.asyncio
async def test_sequential_deploy_continues_after_one_node_fails(monkeypatch):
    plans = [
        earnapp_deploy.EarnAppNodePlan(3, "ipv4-001", "earnapp-proxy-w3-ipv4-001"),
        earnapp_deploy.EarnAppNodePlan(3, "ipv4-002", "earnapp-proxy-w3-ipv4-002"),
        earnapp_deploy.EarnAppNodePlan(3, "ipv4-003", "earnapp-proxy-w3-ipv4-003"),
    ]
    prepared = [
        earnapp_deploy.PreparedEarnAppNode.from_plan(
            plan,
            platform="macos",
            account_id=1,
            device_id="sdk-mac-" + (f"{index:032x}"),
            proxy={"proxy_id": index, "country_code": "VN"},
        )
        for index, plan in enumerate(plans, start=1)
    ]
    order: list[str] = []

    async def deploy(_worker_id, node_id, _spec):
        order.append(node_id)
        if node_id.endswith("002"):
            raise RuntimeError("isolated failure")
        return {"container_id": f"container-{node_id}"}

    async def verify(node_id):
        return {
            "status": "workload_verified",
            "device_id": next(node.device_id for node in prepared if node.logical_node_id == node_id),
            "authenticated": True,
            "device_present": True,
            "online": True,
            "banned": False,
            "workload_state": "workload_verified",
            "workload_delta": {"bandwidth": 1.0, "total_bandwidth": 1.0, "earned_total": 0.0},
        }

    monkeypatch.setattr(earnapp_deploy, "target_worker_plans", AsyncMock(return_value=plans))
    monkeypatch.setattr(earnapp_deploy, "prepare_node", AsyncMock(side_effect=prepared))
    monkeypatch.setattr(database, "get_provider_instance", AsyncMock(return_value=None))
    monkeypatch.setattr(database, "save_provider_instance", AsyncMock())

    result = await earnapp_deploy.deploy_worker_nodes_sequentially(
        3,
        [],
        docker_deploy=deploy,
        lxd_deploy=deploy,
        verify_node=verify,
    )

    assert order == [plan.logical_node_id for plan in plans]
    assert result["deployed"] == [plans[0].logical_node_id, plans[2].logical_node_id]
    assert result["failed"] == [plans[1].logical_node_id]


@pytest.mark.asyncio
async def test_failed_deploy_keeps_identity_and_proxy_lease_for_retry(monkeypatch):
    plan = earnapp_deploy.EarnAppNodePlan(3, "ipv4-001", "earnapp-proxy-w3-ipv4-001")
    prepared = earnapp_deploy.PreparedEarnAppNode.from_plan(
        plan,
        platform="macos",
        account_id=1,
        device_id="sdk-mac-" + "9" * 32,
        proxy={"proxy_id": 11, "country_code": "VN"},
    )
    save = AsyncMock()
    monkeypatch.setattr(earnapp_deploy, "target_worker_plans", AsyncMock(return_value=[plan]))
    monkeypatch.setattr(earnapp_deploy, "prepare_node", AsyncMock(return_value=prepared))
    monkeypatch.setattr(database, "get_provider_instance", AsyncMock(return_value=None))
    monkeypatch.setattr(database, "save_provider_instance", save)

    result = await earnapp_deploy.deploy_worker_nodes_sequentially(
        3,
        [],
        docker_deploy=AsyncMock(side_effect=RuntimeError("isolated failure")),
        lxd_deploy=AsyncMock(),
    )

    assert result["failed"] == [plan.logical_node_id]
    assert save.await_args.kwargs["status"] == "failed"
    assert save.await_args.kwargs["proxy_id"] == 11
    assert save.await_args.kwargs["spec"]["device_id"] == prepared.device_id
    assert save.await_args.kwargs["spec"]["generation"] == 1


@pytest.mark.asyncio
async def test_verified_running_provider_instance_is_idempotently_skipped(monkeypatch):
    plan = earnapp_deploy.EarnAppNodePlan(3, "ipv4-001", "earnapp-proxy-w3-ipv4-001")
    deploy = AsyncMock()
    verify = AsyncMock()
    monkeypatch.setattr(earnapp_deploy, "target_worker_plans", AsyncMock(return_value=[plan]))
    monkeypatch.setattr(
        database,
        "get_provider_instance",
        AsyncMock(return_value={"worker_id": 3, "status": "running", "instance_id": plan.logical_node_id}),
    )
    monkeypatch.setattr(
        database,
        "get_provider_instance_spec",
        AsyncMock(
            return_value={
                "device_id": "sdk-mac-00000000000000000000000000000001",
                "earnapp_device_verification": {
                    "authenticated": True,
                    "device_present": True,
                    "online": True,
                    "banned": False,
                    "device_id": "sdk-mac-00000000000000000000000000000001",
                    "workload_state": "workload_verified",
                    "workload_delta": {"bandwidth": 1.0, "total_bandwidth": 1.0, "earned_total": 0.0},
                },
            }
        ),
    )

    result = await earnapp_deploy.deploy_worker_nodes_sequentially(
        3,
        [],
        docker_deploy=deploy,
        lxd_deploy=deploy,
        verify_node=verify,
    )

    assert result["skipped"] == [plan.logical_node_id]
    deploy.assert_not_awaited()
    verify.assert_not_awaited()


@pytest.mark.asyncio
async def test_running_unverified_instance_is_verified_without_redeploy(monkeypatch):
    plan = earnapp_deploy.EarnAppNodePlan(3, "ipv4-001", "earnapp-proxy-w3-ipv4-001")
    deploy = AsyncMock()
    verify = AsyncMock(
        return_value={
            "status": "workload_verified",
            "device_id": "sdk-mac-00000000000000000000000000000001",
            "authenticated": True,
            "device_present": True,
            "online": True,
            "banned": False,
            "workload_state": "workload_verified",
            "workload_delta": {"bandwidth": 1.0, "total_bandwidth": 1.0, "earned_total": 0.0},
        }
    )
    existing = {
        "worker_id": 3,
        "status": "running",
        "instance_id": plan.logical_node_id,
        "container_id": "existing-container",
        "proxy_id": 11,
        "mode": "proxy",
    }
    monkeypatch.setattr(earnapp_deploy, "target_worker_plans", AsyncMock(return_value=[plan]))
    monkeypatch.setattr(database, "get_provider_instance", AsyncMock(return_value=existing))
    monkeypatch.setattr(
        database,
        "get_provider_instance_spec",
        AsyncMock(return_value={"logical_node_id": plan.logical_node_id}),
    )
    save = AsyncMock()
    monkeypatch.setattr(database, "save_provider_instance", save)

    result = await earnapp_deploy.deploy_worker_nodes_sequentially(
        3,
        [],
        docker_deploy=deploy,
        lxd_deploy=deploy,
        verify_node=verify,
    )

    assert result["verified"] == [plan.logical_node_id]
    assert result["pending"] == []
    deploy.assert_not_awaited()
    verify.assert_awaited_once_with(plan.logical_node_id)
    assert save.await_args.kwargs["status"] == "running"
    assert save.await_args.kwargs["container_id"] == "existing-container"
    assert save.await_args.kwargs["spec"]["earnapp_device_verification"]["online"] is True


@pytest.mark.asyncio
async def test_new_deploy_remains_pending_until_authenticated_device_is_online(monkeypatch):
    plan = earnapp_deploy.EarnAppNodePlan(3, "ipv4-001", "earnapp-proxy-w3-ipv4-001")
    prepared = earnapp_deploy.PreparedEarnAppNode.from_plan(
        plan,
        platform="macos",
        account_id=1,
        device_id="sdk-mac-00000000000000000000000000000001",
        proxy={"proxy_id": 11, "country_code": "VN"},
    )
    deploy = AsyncMock(return_value={"container_id": "new-container"})
    verify = AsyncMock(
        return_value={
            "status": "pending",
            "device_id": prepared.device_id,
            "authenticated": True,
            "device_present": True,
            "online": False,
            "banned": False,
        }
    )
    monkeypatch.setattr(earnapp_deploy, "target_worker_plans", AsyncMock(return_value=[plan]))
    monkeypatch.setattr(earnapp_deploy, "prepare_node", AsyncMock(return_value=prepared))
    monkeypatch.setattr(database, "get_provider_instance", AsyncMock(return_value=None))
    save = AsyncMock()
    monkeypatch.setattr(database, "save_provider_instance", save)

    result = await earnapp_deploy.deploy_worker_nodes_sequentially(
        3,
        [],
        docker_deploy=deploy,
        lxd_deploy=deploy,
        verify_node=verify,
    )

    assert result["deployed"] == []
    assert result["pending"] == [plan.logical_node_id]
    assert result["failed"] == []
    assert save.await_args.kwargs["status"] == "verification_pending"
    assert save.await_args.kwargs["container_id"] == "new-container"
    assert save.await_args.kwargs["spec"]["earnapp_device_verification"]["online"] is False


@pytest.mark.asyncio
async def test_server_earnapp_lane_uses_worker_slots_and_platform_specific_endpoints(monkeypatch):
    slots = [{"slot_id": "ipv4-001", "public_ip": "203.0.113.1", "route_ready": True}]
    deploy = AsyncMock(return_value={"deployed": ["earnapp-proxy-w3-ipv4-001"], "failed": []})
    monkeypatch.setattr(main, "_worker_public_ip_slots", AsyncMock(return_value=slots))
    monkeypatch.setattr(main.earnapp_deploy, "deploy_worker_nodes_sequentially", deploy)

    result = await main._deploy_earnapp_nodes(3, config={"earnapp_lxd_cpu": "2", "earnapp_lxd_memory_mib": "2048"})

    assert result["deployed"] == ["earnapp-proxy-w3-ipv4-001"]
    assert deploy.await_args.args[:2] == (3, slots)
    assert deploy.await_args.kwargs["lxd_settings"] == {"cpu": 2, "memory_mib": 2048}


def test_earnapp_transport_spec_does_not_fall_back_to_nkn_lxd_settings():
    node = earnapp_deploy.PreparedEarnAppNode(
        worker_id=3,
        slot_id="ipv4-001",
        logical_node_id="earnapp-proxy-w3-ipv4-001",
        platform="ubuntu",
        account_id=7,
        device_id="sdk-node-0123456789abcdef0123456789abcdef",
        generation=1,
        proxy={"proxy_id": 9, "exit_ip": "198.51.100.9"},
        identity={"machine_id": "0" * 32},
    )

    spec = earnapp_deploy._transport_spec(
        node,
        lxd_settings={
            "nkn_lxd_cpu": 8,
            "nkn_lxd_memory_mib": 8192,
        },
    )

    assert spec["lxd_cpu"] == 1
    assert spec["lxd_memory_mib"] == 1024


def test_auto_deploy_excludes_earnapp_from_generic_catalog_batch():
    services = [
        {"slug": "earnapp", "status": "active", "docker": {"image": "earnapp-image"}},
        {"slug": "earnfm", "status": "active", "docker": {"image": "earnfm-image"}},
    ]
    assert main._auto_deploy_slugs(services) == ["earnfm"]


def test_earnapp_auto_deploy_retries_after_failed_node_then_marks_done(monkeypatch):
    async def run():
        main._EARNAPP_AUTO_DEPLOY_DONE.discard(7)
        main._WORKER_HEARTBEAT_STREAKS[7] = 2
        spawned = []

        def capture(coro):
            spawned.append(coro)
            return None

        deploy = AsyncMock(
            side_effect=[
                {"deployed": [], "skipped": [], "failed": ["node-a"]},
                {"deployed": ["node-a"], "skipped": [], "failed": []},
            ]
        )
        with (
            patch.object(
                database,
                "get_config",
                AsyncMock(return_value={"cashpilot_auto_deploy_enabled": "true"}),
            ),
            patch.object(
                database,
                "get_worker",
                AsyncMock(return_value={"id": 7, "name": "worker-a", "client_id": "worker-a"}),
            ),
            patch.object(database, "get_deployments", AsyncMock(return_value=[])),
            patch.object(main, "_deploy_earnapp_nodes", deploy),
            patch.object(main, "_spawn", side_effect=capture),
            patch.object(main.catalog, "get_services", return_value=[]),
        ):
            await main._maybe_auto_deploy_after_heartbeat(7)
            await asyncio.gather(*spawned)
            spawned.clear()
            await main._maybe_auto_deploy_after_heartbeat(7)
            await asyncio.gather(*spawned)

        assert deploy.await_count == 2
        assert 7 in main._EARNAPP_AUTO_DEPLOY_DONE

    asyncio.run(run())
