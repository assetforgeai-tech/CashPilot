from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import database, earnapp_accounts, main, orchestrator, worker_api


def test_earnapp_egress_probe_decodes_docker_exec_bytes_before_ip_validation(monkeypatch):
    container = MagicMock(status="running")
    container.exec_run.return_value = MagicMock(exit_code=0, output=b"171.251.97.103")
    monkeypatch.setattr(orchestrator, "_find_container", lambda _slug: container)

    assert orchestrator.probe_service_egress("earnapp-canary-test-sing-1") == {
        "running": True,
        "observed_egress_ip": "171.251.97.103",
        "probe_ok": True,
    }


def _account(profile: str = "profile-a") -> dict[str, object]:
    return {
        "profile_key": profile,
        "account_name": f"{profile}@example.com",
        "email": f"{profile}@example.com",
        "auth_method": "google",
        "cookies": {"oauth-refresh-token": "refresh", "xsrf-token": "xsrf"},
    }


async def _proxy(provider_id: int, suffix: int) -> int:
    (proxy_id,) = await database.upsert_proxy_endpoints_returning_ids(
        provider_id,
        [
            {
                "provider_proxy_id": f"proxy-{suffix}",
                "endpoint": f"proxy{suffix}.example:10{suffix:02d}",
                "host": f"proxy{suffix}.example",
                "port": 1000 + suffix,
                "protocol": "socks5",
                "username": "user",
                "password": "secret",
                "status": "alive",
                "exit_ip": f"198.51.100.{suffix}",
                "ip_type": "residential",
                "country_code": "VN",
            }
        ],
    )
    await database.update_proxy_endpoint_intelligence(
        proxy_id,
        {
            "ip_type": "residential",
            "ip_type_source": "test",
            "ip_type_confidence": "high",
            "country_code": "VN",
            "country_name": "Vietnam",
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
        latency_ms=10,
        probe_version="test",
    )
    return proxy_id


def test_node_scoped_health_evidence_and_atomic_rotation_preserve_preference(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "health.db"):
            await database.init_db()
            await earnapp_accounts.import_account(_account())
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            old_proxy = await _proxy(provider_id, 1)
            new_proxy = await _proxy(provider_id, 2)
            worker_id = await database.upsert_worker("worker-a", "worker-a", "http://worker")
            await database.assign_earnapp_account("earnapp-node-health", platform="macos")
            identity = "sdk-mac-" + "a" * 32
            await database.bind_earnapp_node_runtime(
                "earnapp-node-health", worker_id, device_id=identity, proxy_id=old_proxy
            )
            await database.save_provider_instance(
                "earnapp",
                "earnapp-node-health",
                worker_id=worker_id,
                mode="proxy",
                proxy_id=old_proxy,
                status="running",
            )

            assert await database.record_earnapp_proxy_health(
                "earnapp-node-health",
                worker_id,
                generation=1,
                proxy_id=old_proxy,
                health="unhealthy",
                observed_egress_ip="203.0.113.10",
                reason="egress_mismatch",
            )
            node = await database.get_earnapp_logical_node("earnapp-node-health")
            assert node["proxy_health"] == "unhealthy"
            assert node["observed_egress_ip"] == "203.0.113.10"

            rotated = await database.commit_earnapp_proxy_rotation(
                "earnapp-node-health",
                worker_id,
                expected_generation=1,
                expected_proxy_id=old_proxy,
                new_proxy_id=new_proxy,
            )
            assert rotated is not None
            assert rotated["current_proxy_id"] == new_proxy
            assert rotated["preferred_proxy_id"] == old_proxy
            assert (await database.get_provider_instance("earnapp-node-health"))["proxy_id"] == new_proxy
            assert await database.get_active_provider_proxy_lease("earnapp", worker_id, "earnapp-node-health")
            old_lease = await database.list_provider_proxy_leases(provider_slug="earnapp")
            assert any(row["proxy_id"] == old_proxy and row["released_at"] for row in old_lease)

    asyncio.run(run())


def test_lease_for_earnapp_node_reuses_preferred_proxy_when_available(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "preferred.db"):
            await database.init_db()
            await earnapp_accounts.import_account(_account())
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            preferred = await _proxy(provider_id, 3)
            worker_id = await database.upsert_worker("worker-a", "worker-a", "http://worker")
            await database.assign_earnapp_account("earnapp-preferred-node", platform="macos")
            await database.bind_earnapp_node_runtime(
                "earnapp-preferred-node", worker_id, device_id="sdk-mac-" + "b" * 32, proxy_id=preferred
            )
            await database.release_proxy_for_provider_instance("earnapp", worker_id, "earnapp-preferred-node")
            # A released node keeps its preferred route and can reclaim it.
            db = await database._get_db()
            await db.execute(
                "UPDATE earnapp_logical_nodes SET current_proxy_id=NULL, proxy_health='unknown' WHERE logical_node_id=?",
                ("earnapp-preferred-node",),
            )
            await db.commit()
            lease = await database.lease_proxy_for_provider_instance(
                "earnapp", worker_id, "earnapp-preferred-node", country_code="VN"
            )
            assert lease and lease["proxy_id"] == preferred

    asyncio.run(run())


def test_earnapp_heartbeat_state_contains_scoped_proxy_evidence(tmp_path, monkeypatch):
    state_dir = tmp_path / "earnapp-nodes"
    state_dir.mkdir()
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    (state_dir / "earnapp-node-health.json").write_text(
        json.dumps(
            {
                "logical_node_id": "earnapp-node-health",
                "generation": 2,
                "device_id": "sdk-mac-" + "c" * 32,
                "platform": "darwin",
                "runtime_backend": "docker",
                "proxy_id": 77,
                "expected_egress_ip": "198.51.100.77",
                "proxy_health": "healthy",
                "observed_egress_ip": "198.51.100.77",
                "evidence": {"online": True},
            }
        ),
        encoding="utf-8",
    )
    state = worker_api._earnapp_provider_state([])
    assert state and state["instances"][0]["proxy_id"] == 77
    assert state["instances"][0]["proxy_health"] == "healthy"
    assert state["instances"][0]["observed_egress_ip"] == "198.51.100.77"


@pytest.mark.parametrize(
    ("platform", "runtime_backend", "device_id"),
    (
        ("macos", "docker", "sdk-mac-" + "c" * 32),
        ("ios", "docker", "sdk-ios-" + "c" * 32),
        ("ubuntu", "lxd", "sdk-ubuntu-" + "c" * 28),
    ),
)
def test_legacy_state_is_hydrated_from_server_assignment(tmp_path, monkeypatch, platform, runtime_backend, device_id):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    worker_api._save_earnapp_state(
        "earnapp-canary-test-sing-1",
        {
            "logical_node_id": "earnapp-canary-test-sing-1",
            "generation": 1,
            "device_id": device_id,
            "runtime_status": "running",
        },
    )
    assert worker_api._hydrate_earnapp_state_from_assignment(
        {
            "logical_node_id": "earnapp-canary-test-sing-1",
            "generation": 1,
            "device_id": device_id,
            "proxy_id": 12706,
            "platform": platform,
            "runtime_backend": runtime_backend,
            "expected_egress_ip": "171.251.97.103",
            "hydrate_state": True,
            "hydrate_expected": {
                "proxy_id": 0,
                "platform": "unknown",
                "runtime_backend": "docker",
                "expected_egress_ip": "",
                "pending_binding_version": "",
                "pending_proxy_id": 0,
                "pending_expected_egress_ip": "",
            },
        }
    )

    persisted = json.loads((tmp_path / "earnapp-nodes" / "earnapp-canary-test-sing-1.json").read_text(encoding="utf-8"))
    assert persisted["platform"] == platform
    assert persisted["runtime_backend"] == runtime_backend
    assert persisted["proxy_id"] == 12706
    assert persisted["expected_egress_ip"] == "171.251.97.103"


def test_legacy_docker_state_rejects_assignment_for_different_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    worker_api._save_earnapp_state(
        "earnapp-canary-test-sing-1",
        {
            "logical_node_id": "earnapp-canary-test-sing-1",
            "generation": 1,
            "device_id": "sdk-mac-" + "c" * 32,
        },
    )
    assert not worker_api._hydrate_earnapp_state_from_assignment(
        {
            "logical_node_id": "earnapp-canary-test-sing-1",
            "generation": 1,
            "device_id": "sdk-mac-" + "d" * 32,
            "proxy_id": 12706,
            "platform": "macos",
            "runtime_backend": "docker",
            "expected_egress_ip": "171.251.97.103",
            "hydrate_state": True,
        }
    )

    persisted = json.loads((tmp_path / "earnapp-nodes" / "earnapp-canary-test-sing-1.json").read_text(encoding="utf-8"))
    assert persisted.get("proxy_id", 0) == 0
    assert persisted.get("platform", "unknown") == "unknown"


def test_legacy_state_rejects_delayed_ack_after_local_proxy_change(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    worker_api._save_earnapp_state(
        "earnapp-canary-test-sing-1",
        {
            "logical_node_id": "earnapp-canary-test-sing-1",
            "generation": 1,
            "device_id": "sdk-mac-" + "c" * 32,
            "proxy_id": 12707,
            "platform": "macos",
            "runtime_backend": "docker",
            "expected_egress_ip": "171.251.97.104",
        },
    )
    assert not worker_api._hydrate_earnapp_state_from_assignment(
        {
            "logical_node_id": "earnapp-canary-test-sing-1",
            "generation": 1,
            "device_id": "sdk-mac-" + "c" * 32,
            "proxy_id": 12706,
            "platform": "macos",
            "runtime_backend": "docker",
            "expected_egress_ip": "171.251.97.103",
            "hydrate_state": True,
            "hydrate_expected": {
                "proxy_id": 0,
                "platform": "unknown",
                "runtime_backend": "docker",
                "expected_egress_ip": "",
                "pending_binding_version": "",
                "pending_proxy_id": 0,
                "pending_expected_egress_ip": "",
            },
        }
    )

    persisted = json.loads((tmp_path / "earnapp-nodes" / "earnapp-canary-test-sing-1.json").read_text(encoding="utf-8"))
    assert persisted["proxy_id"] == 12707
    assert persisted["expected_egress_ip"] == "171.251.97.104"


@pytest.mark.parametrize(
    ("field", "value"),
    (("generation", "invalid"), ("proxy_id", "invalid")),
)
def test_legacy_docker_state_rejects_malformed_numeric_assignment(tmp_path, monkeypatch, field, value):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    worker_api._save_earnapp_state(
        "earnapp-canary-test-sing-1",
        {
            "logical_node_id": "earnapp-canary-test-sing-1",
            "generation": 1,
            "device_id": "sdk-mac-" + "c" * 32,
        },
    )
    assignment = {
        "logical_node_id": "earnapp-canary-test-sing-1",
        "generation": 1,
        "device_id": "sdk-mac-" + "c" * 32,
        "proxy_id": 12706,
        "platform": "macos",
        "runtime_backend": "docker",
        "expected_egress_ip": "171.251.97.103",
        "hydrate_state": True,
    }
    assignment[field] = value

    assert not worker_api._hydrate_earnapp_state_from_assignment(assignment)


@pytest.mark.parametrize(
    ("platform", "runtime_backend"),
    (("macos", "lxd"), ("ios", "lxd"), ("ubuntu", "docker")),
)
def test_legacy_state_rejects_platform_backend_mismatch(tmp_path, monkeypatch, platform, runtime_backend):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    worker_api._save_earnapp_state(
        "earnapp-canary-test-sing-1",
        {
            "logical_node_id": "earnapp-canary-test-sing-1",
            "generation": 1,
            "device_id": "sdk-mac-" + "c" * 32,
        },
    )

    assert not worker_api._hydrate_earnapp_state_from_assignment(
        {
            "logical_node_id": "earnapp-canary-test-sing-1",
            "generation": 1,
            "device_id": "sdk-mac-" + "c" * 32,
            "proxy_id": 12706,
            "platform": platform,
            "runtime_backend": runtime_backend,
            "expected_egress_ip": "171.251.97.103",
            "hydrate_state": True,
        }
    )


def test_earnapp_heartbeat_state_exposes_only_nonsecret_pending_binding_journal(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    worker_api._save_earnapp_state(
        "earnapp-node-pending",
        {
            "logical_node_id": "earnapp-node-pending",
            "generation": 5,
            "device_id": "sdk-mac-" + "a" * 32,
            "platform": "macos",
            "runtime_backend": "docker",
            "proxy_id": 11,
            "expected_egress_ip": "198.51.100.11",
            "pending_binding_version": "rotation_pending_123456",
            "pending_proxy_id": 22,
            "pending_expected_egress_ip": "198.51.100.22",
            "pending_observed_egress_ip": "198.51.100.22",
            "proxy_password": "must-not-leak",
        },
    )

    state = worker_api._earnapp_provider_state([])

    assert state is not None
    instance = state["instances"][0]
    assert instance["pending_binding_version"] == "rotation_pending_123456"
    assert instance["pending_proxy_id"] == 22
    assert instance["pending_expected_egress_ip"] == "198.51.100.22"
    assert instance["pending_observed_egress_ip"] == "198.51.100.22"
    assert "must-not-leak" not in json.dumps(state, sort_keys=True)


@pytest.mark.asyncio
async def test_pending_rotation_reconciliation_commits_when_database_already_rotated(monkeypatch):
    node_id = "earnapp-proxy-w11-ipv4-003"
    device_id = "sdk-mac-" + "b" * 32
    instance = {
        "logical_node_id": node_id,
        "generation": 5,
        "device_id": device_id,
        "proxy_id": 11,
        "pending_binding_version": "rotation_pending_123456",
        "pending_proxy_id": 22,
        "pending_expected_egress_ip": "198.51.100.22",
        "pending_observed_egress_ip": "198.51.100.22",
    }
    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(
            return_value={
                "logical_node_id": node_id,
                "assigned_worker_id": 11,
                "generation": 5,
                "device_id": device_id,
                "current_proxy_id": 22,
                "preferred_proxy_id": 11,
                "expected_egress_ip": "198.51.100.22",
                "state": "ACTIVE",
            }
        ),
    )
    finalize = AsyncMock(
        return_value={
            "ok": True,
            "binding_version": "rotation_pending_123456",
            "action": "confirmed",
            "proxy_id": 22,
        }
    )
    monkeypatch.setattr(main, "_proxy_to_worker", finalize)

    assert await main._reconcile_earnapp_pending_proxy_binding(instance, 11)
    payload = finalize.await_args.kwargs["json"]
    assert payload["commit"] is True
    assert payload["expected_proxy_id"] == 11
    assert payload["new_proxy_id"] == 22
    assert payload["expected_egress_ip"] == "198.51.100.22"


@pytest.mark.asyncio
async def test_pending_rotation_reconciliation_rolls_back_when_database_did_not_rotate(monkeypatch):
    node_id = "earnapp-proxy-w11-ipv4-004"
    device_id = "sdk-ios-" + "c" * 32
    instance = {
        "logical_node_id": node_id,
        "generation": 6,
        "device_id": device_id,
        "proxy_id": 31,
        "pending_binding_version": "rotation_pending_654321",
        "pending_proxy_id": 32,
        "pending_expected_egress_ip": "198.51.100.32",
        "pending_observed_egress_ip": "198.51.100.32",
    }
    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(
            return_value={
                "logical_node_id": node_id,
                "assigned_worker_id": 11,
                "generation": 6,
                "device_id": device_id,
                "current_proxy_id": 31,
                "preferred_proxy_id": 31,
                "expected_egress_ip": "198.51.100.31",
                "state": "ACTIVE",
            }
        ),
    )
    finalize = AsyncMock(
        return_value={
            "ok": True,
            "binding_version": "rotation_pending_654321",
            "action": "rolled_back",
            "proxy_id": 31,
        }
    )
    monkeypatch.setattr(main, "_proxy_to_worker", finalize)

    assert await main._reconcile_earnapp_pending_proxy_binding(instance, 11)
    payload = finalize.await_args.kwargs["json"]
    assert payload["commit"] is False
    assert payload["expected_proxy_id"] == 31
    assert payload["new_proxy_id"] == 32


@pytest.mark.asyncio
async def test_pending_rotation_reconciliation_rolls_back_write_ahead_intent_without_apply_evidence(monkeypatch):
    node_id = "earnapp-proxy-w11-ipv4-004b"
    device_id = "sdk-ios-" + "d" * 32
    instance = {
        "logical_node_id": node_id,
        "generation": 6,
        "device_id": device_id,
        "proxy_id": 31,
        "pending_binding_version": "rotation_pending_654322",
        "pending_proxy_id": 32,
        "pending_expected_egress_ip": "198.51.100.32",
        "pending_observed_egress_ip": "",
    }
    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(
            return_value={
                "logical_node_id": node_id,
                "assigned_worker_id": 11,
                "generation": 6,
                "device_id": device_id,
                "current_proxy_id": 31,
                "preferred_proxy_id": 31,
                "expected_egress_ip": "198.51.100.31",
                "state": "ACTIVE",
            }
        ),
    )
    finalize = AsyncMock(
        return_value={
            "ok": True,
            "binding_version": "rotation_pending_654322",
            "action": "rolled_back",
            "proxy_id": 31,
        }
    )
    monkeypatch.setattr(main, "_proxy_to_worker", finalize)

    assert await main._reconcile_earnapp_pending_proxy_binding(instance, 11)
    assert finalize.await_args.kwargs["json"]["commit"] is False


@pytest.mark.asyncio
async def test_pending_rotation_reconciliation_refuses_database_egress_mismatch(monkeypatch):
    node_id = "earnapp-proxy-w11-ipv4-005"
    device_id = "sdk-mac-" + "e" * 32
    instance = {
        "logical_node_id": node_id,
        "generation": 7,
        "device_id": device_id,
        "proxy_id": 41,
        "pending_binding_version": "rotation_pending_777777",
        "pending_proxy_id": 42,
        "pending_expected_egress_ip": "198.51.100.42",
        "pending_observed_egress_ip": "198.51.100.42",
    }
    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(
            return_value={
                "logical_node_id": node_id,
                "assigned_worker_id": 11,
                "generation": 7,
                "device_id": device_id,
                "current_proxy_id": 42,
                "preferred_proxy_id": 41,
                "expected_egress_ip": "203.0.113.42",
                "state": "ACTIVE",
            }
        ),
    )
    finalize = AsyncMock()
    monkeypatch.setattr(main, "_proxy_to_worker", finalize)

    assert not await main._reconcile_earnapp_pending_proxy_binding(instance, 11)
    finalize.assert_not_awaited()


def test_server_heartbeat_reconciles_pending_binding_without_starting_another_rotation():
    async def run():
        body = main.WorkerHeartbeat(
            name="worker-a",
            client_id="worker-a",
            provider_states={
                "earnapp": {
                    "instances": [
                        {
                            "logical_node_id": "earnapp-node-pending",
                            "generation": 8,
                            "device_id": "sdk-mac-" + "d" * 32,
                            "proxy_id": 41,
                            "proxy_health": "unhealthy",
                            "pending_binding_version": "rotation_pending_888888",
                            "pending_proxy_id": 42,
                            "pending_expected_egress_ip": "198.51.100.42",
                            "pending_observed_egress_ip": "198.51.100.42",
                        }
                    ]
                }
            },
        )

        spawned = []

        def discard(coro):
            spawned.append(coro)
            coro.close()

        with (
            patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
            patch.object(database, "upsert_worker", AsyncMock(return_value=11)),
            patch.object(main.earnapp_recovery, "heartbeat_node", AsyncMock(return_value=True)),
            patch.object(main, "_reconcile_earnapp_pending_proxy_binding", AsyncMock(return_value=True)) as reconcile,
            patch.object(database, "record_earnapp_proxy_health", AsyncMock()) as record,
            patch.object(main, "_rotate_unhealthy_earnapp_node", AsyncMock()) as rotate,
            patch.object(database, "confirm_worker_key", AsyncMock()),
            patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
            patch.object(main, "_spawn", side_effect=discard),
            patch.object(main.metrics, "record_heartbeat"),
        ):
            await main.api_worker_heartbeat(
                type("Request", (), {"headers": {"authorization": "Bearer key"}})(),
                body,
            )

        reconcile.assert_not_awaited()
        assert len(spawned) == 2
        record.assert_not_awaited()
        rotate.assert_not_awaited()

    asyncio.run(run())


def test_worker_refreshes_each_nodes_proxy_health_in_its_own_runtime_namespace(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    worker_api._save_earnapp_state(
        "earnapp-docker-health",
        {
            "logical_node_id": "earnapp-docker-health",
            "generation": 2,
            "device_id": "sdk-mac-" + "a" * 32,
            "platform": "darwin",
            "runtime_backend": "docker",
            "proxy_id": 71,
            "expected_egress_ip": "198.51.100.71",
        },
    )
    worker_api._save_earnapp_state(
        "earnapp-lxd-health",
        {
            "logical_node_id": "earnapp-lxd-health",
            "generation": 3,
            "device_id": "sdk-node-" + "b" * 32,
            "platform": "ubuntu",
            "runtime_backend": "lxd",
            "proxy_id": 72,
            "expected_egress_ip": "198.51.100.72",
        },
    )
    with (
        patch.object(
            worker_api.orchestrator,
            "probe_service_egress",
            return_value={"running": True, "probe_ok": True, "observed_egress_ip": "198.51.100.71"},
        ),
        patch.object(
            worker_api.earnapp_lxd_runtime,
            "node_evidence",
            return_value={
                "running": True,
                "online": True,
                "probe_ok": True,
                "observed_egress_ip": "203.0.113.72",
            },
        ),
    ):
        asyncio.run(worker_api._refresh_earnapp_runtime_evidence())

    docker_state = json.loads((tmp_path / "earnapp-nodes" / "earnapp-docker-health.json").read_text(encoding="utf-8"))
    lxd_state = json.loads((tmp_path / "earnapp-nodes" / "earnapp-lxd-health.json").read_text(encoding="utf-8"))
    assert docker_state["proxy_health"] == "healthy"
    assert docker_state["observed_egress_ip"] == "198.51.100.71"
    assert docker_state["proxy_health_reason"] == ""
    assert lxd_state["proxy_health"] == "unhealthy"
    assert lxd_state["observed_egress_ip"] == "203.0.113.72"
    assert lxd_state["proxy_health_reason"] == "egress_mismatch"


def test_worker_proxy_probe_failure_is_unhealthy_but_helper_outage_stays_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    worker_api._save_earnapp_state(
        "earnapp-docker-dead",
        {
            "logical_node_id": "earnapp-docker-dead",
            "generation": 2,
            "device_id": "sdk-ios-" + "c" * 32,
            "platform": "ios",
            "runtime_backend": "docker",
            "proxy_id": 73,
            "expected_egress_ip": "198.51.100.73",
        },
    )
    worker_api._save_earnapp_state(
        "earnapp-lxd-unknown",
        {
            "logical_node_id": "earnapp-lxd-unknown",
            "generation": 4,
            "device_id": "sdk-node-" + "d" * 32,
            "platform": "ubuntu",
            "runtime_backend": "lxd",
            "proxy_id": 74,
            "expected_egress_ip": "198.51.100.74",
        },
    )
    with (
        patch.object(
            worker_api.orchestrator,
            "probe_service_egress",
            return_value={"running": True, "probe_ok": False, "observed_egress_ip": ""},
        ),
        patch.object(worker_api.earnapp_lxd_runtime, "node_evidence", side_effect=RuntimeError("helper down")),
    ):
        asyncio.run(worker_api._refresh_earnapp_runtime_evidence())

    docker_state = json.loads((tmp_path / "earnapp-nodes" / "earnapp-docker-dead.json").read_text(encoding="utf-8"))
    lxd_state = json.loads((tmp_path / "earnapp-nodes" / "earnapp-lxd-unknown.json").read_text(encoding="utf-8"))
    assert docker_state["proxy_health"] == "unhealthy"
    assert docker_state["proxy_health_reason"] == "proxy_probe_failed"
    assert lxd_state["proxy_health"] == "unknown"
    assert lxd_state["proxy_health_reason"] == "runtime_probe_unavailable"


def test_server_heartbeat_records_scoped_health_and_rotates_only_explicitly_unhealthy_nodes():
    async def run():
        body = main.WorkerHeartbeat(
            name="worker-a",
            client_id="worker-a",
            provider_states={
                "earnapp": {
                    "instances": [
                        {
                            "logical_node_id": "earnapp-node-unhealthy",
                            "generation": 4,
                            "device_id": "sdk-mac-" + "a" * 32,
                            "proxy_id": 11,
                            "platform": "macos",
                            "runtime_backend": "docker",
                            "expected_egress_ip": "203.0.113.11",
                            "proxy_health": "unhealthy",
                            "observed_egress_ip": "203.0.113.11",
                            "proxy_health_reason": "egress_mismatch",
                        },
                        {
                            "logical_node_id": "earnapp-node-unknown",
                            "generation": 2,
                            "device_id": "sdk-ios-" + "b" * 32,
                            "proxy_id": 12,
                            "platform": "ios",
                            "runtime_backend": "docker",
                            "expected_egress_ip": "203.0.113.12",
                            "proxy_health": "unknown",
                        },
                        {
                            "logical_node_id": "earnapp-canary-test-sing-1",
                            "generation": 1,
                            "device_id": "sdk-mac-" + "c" * 32,
                            "proxy_id": 13,
                            "platform": "macos",
                            "runtime_backend": "docker",
                            "expected_egress_ip": "203.0.113.13",
                            "proxy_health": "unhealthy",
                        },
                    ]
                }
            },
        )
        authoritative = [
            {
                "logical_node_id": "earnapp-node-unhealthy",
                "assigned_worker_id": 11,
                "generation": 4,
                "device_id": "sdk-mac-" + "a" * 32,
                "platform": "macos",
                "current_proxy_id": 11,
                "expected_egress_ip": "203.0.113.11",
                "state": "ACTIVE",
            },
            {
                "logical_node_id": "earnapp-node-unknown",
                "assigned_worker_id": 11,
                "generation": 2,
                "device_id": "sdk-ios-" + "b" * 32,
                "platform": "ios",
                "current_proxy_id": 12,
                "expected_egress_ip": "203.0.113.12",
                "state": "ACTIVE",
            },
            {
                "logical_node_id": "earnapp-canary-test-sing-1",
                "assigned_worker_id": 11,
                "generation": 1,
                "device_id": "sdk-mac-" + "c" * 32,
                "platform": "macos",
                "current_proxy_id": 13,
                "expected_egress_ip": "203.0.113.13",
                "state": "ACTIVE",
            },
        ]
        spawned = []

        def capture(coro):
            spawned.append(coro)
            return None

        with (
            patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
            patch.object(database, "upsert_worker", AsyncMock(return_value=11)),
            patch.object(main.earnapp_recovery, "heartbeat_node", AsyncMock(return_value=True)),
            patch.object(database, "get_earnapp_logical_node", AsyncMock(side_effect=authoritative)),
            patch.object(database, "record_earnapp_proxy_health", AsyncMock(return_value=True)) as record,
            patch.object(main, "_rotate_unhealthy_earnapp_node", AsyncMock(return_value=True)) as rotate,
            patch.object(database, "confirm_worker_key", AsyncMock()),
            patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
            patch.object(main, "_maybe_auto_deploy_after_heartbeat", AsyncMock(return_value=None)),
            patch.object(main, "_spawn", side_effect=capture),
            patch.object(main.metrics, "record_heartbeat"),
        ):
            await main.api_worker_heartbeat(type("Request", (), {"headers": {"authorization": "Bearer key"}})(), body)
            await asyncio.gather(*spawned)

        assert record.await_count == 3
        rotate.assert_awaited_once_with("earnapp-node-unhealthy", 11, generation=4, expected_proxy_id=11)

    asyncio.run(run())


def test_server_heartbeat_returns_authoritative_legacy_assignment():
    async def run():
        body = main.WorkerHeartbeat(
            name="worker-a",
            client_id="worker-a",
            provider_states={
                "earnapp": {
                    "instances": [
                        {
                            "logical_node_id": "earnapp-canary-test-sing-1",
                            "generation": 1,
                            "device_id": "sdk-mac-" + "c" * 32,
                            "proxy_id": 0,
                            "proxy_health": "unhealthy",
                            "observed_egress_ip": "171.251.97.103",
                        }
                    ]
                }
            },
        )
        authoritative = {
            "logical_node_id": "earnapp-canary-test-sing-1",
            "assigned_worker_id": 11,
            "generation": 1,
            "device_id": "sdk-mac-" + "c" * 32,
            "platform": "macos",
            "current_proxy_id": 12706,
            "expected_egress_ip": "171.251.97.103",
            "state": "ACTIVE",
        }

        def discard(coro):
            coro.close()

        with (
            patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
            patch.object(database, "upsert_worker", AsyncMock(return_value=11)),
            patch.object(main.earnapp_recovery, "heartbeat_node", AsyncMock(return_value=True)) as heartbeat,
            patch.object(database, "get_earnapp_logical_node", AsyncMock(return_value=authoritative)),
            patch.object(database, "record_earnapp_proxy_health", AsyncMock(return_value=True)) as record,
            patch.object(main, "_rotate_unhealthy_earnapp_node", AsyncMock()) as rotate,
            patch.object(database, "confirm_worker_key", AsyncMock()),
            patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
            patch.object(main, "_maybe_auto_deploy_after_heartbeat", AsyncMock(return_value=None)),
            patch.object(main, "_spawn", side_effect=discard),
            patch.object(main.metrics, "record_heartbeat"),
        ):
            response = await main.api_worker_heartbeat(
                type("Request", (), {"headers": {"authorization": "Bearer key"}})(), body
            )

        heartbeat.assert_awaited_once_with(
            "earnapp-canary-test-sing-1",
            11,
            generation=1,
            device_id="sdk-mac-" + "c" * 32,
            proxy_id=12706,
        )
        record.assert_not_awaited()
        rotate.assert_not_awaited()
        assert response["earnapp_assignment_acks"] == [
            {
                "logical_node_id": "earnapp-canary-test-sing-1",
                "generation": 1,
                "device_id": "sdk-mac-" + "c" * 32,
                "proxy_id": 12706,
                "platform": "macos",
                "runtime_backend": "docker",
                "expected_egress_ip": "171.251.97.103",
                "hydrate_state": True,
                "hydrate_expected": {
                    "proxy_id": 0,
                    "platform": "unknown",
                    "runtime_backend": "docker",
                    "expected_egress_ip": "",
                    "pending_binding_version": "",
                    "pending_proxy_id": 0,
                    "pending_expected_egress_ip": "",
                },
            }
        ]
        assert "earnapp_assignment_rejections" not in response

    asyncio.run(run())


def test_server_hydration_derives_backend_from_authoritative_ubuntu_platform():
    async def run():
        body = main.WorkerHeartbeat(
            name="worker-a",
            client_id="worker-a",
            provider_states={
                "earnapp": {
                    "instances": [
                        {
                            "logical_node_id": "earnapp-ubuntu-legacy",
                            "generation": 2,
                            "device_id": "sdk-ubuntu-" + "d" * 28,
                            "proxy_id": 12706,
                            "platform": "unknown",
                            "runtime_backend": "docker",
                            "proxy_health": "healthy",
                        }
                    ]
                }
            },
        )
        authoritative = {
            "logical_node_id": "earnapp-ubuntu-legacy",
            "assigned_worker_id": 11,
            "generation": 2,
            "device_id": "sdk-ubuntu-" + "d" * 28,
            "platform": "ubuntu",
            "current_proxy_id": 12706,
            "expected_egress_ip": "198.51.100.206",
            "state": "ACTIVE",
        }

        def discard(coro):
            coro.close()

        with (
            patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
            patch.object(database, "upsert_worker", AsyncMock(return_value=11)),
            patch.object(main.earnapp_recovery, "heartbeat_node", AsyncMock(return_value=True)) as heartbeat,
            patch.object(database, "get_earnapp_logical_node", AsyncMock(return_value=authoritative)),
            patch.object(database, "record_earnapp_proxy_health", AsyncMock()) as record,
            patch.object(database, "confirm_worker_key", AsyncMock()),
            patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
            patch.object(main, "_maybe_auto_deploy_after_heartbeat", AsyncMock(return_value=None)),
            patch.object(main, "_spawn", side_effect=discard),
            patch.object(main.metrics, "record_heartbeat"),
        ):
            response = await main.api_worker_heartbeat(
                type("Request", (), {"headers": {"authorization": "Bearer key"}})(), body
            )

        heartbeat.assert_awaited_once_with(
            "earnapp-ubuntu-legacy",
            11,
            generation=2,
            device_id="sdk-ubuntu-" + "d" * 28,
            proxy_id=12706,
        )
        assert response["earnapp_assignment_acks"][0]["platform"] == "ubuntu"
        assert response["earnapp_assignment_acks"][0]["runtime_backend"] == "lxd"
        record.assert_not_awaited()

    asyncio.run(run())


def test_server_hydrates_state_with_existing_proxy_but_missing_runtime_fields():
    async def run():
        body = main.WorkerHeartbeat(
            name="worker-a",
            client_id="worker-a",
            provider_states={
                "earnapp": {
                    "instances": [
                        {
                            "logical_node_id": "earnapp-macos-partial",
                            "generation": 3,
                            "device_id": "sdk-mac-" + "e" * 32,
                            "proxy_id": 12706,
                            "proxy_health": "unknown",
                        }
                    ]
                }
            },
        )
        authoritative = {
            "logical_node_id": "earnapp-macos-partial",
            "assigned_worker_id": 11,
            "generation": 3,
            "device_id": "sdk-mac-" + "e" * 32,
            "platform": "macos",
            "current_proxy_id": 12706,
            "expected_egress_ip": "198.51.100.207",
            "state": "ACTIVE",
        }

        def discard(coro):
            coro.close()

        with (
            patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
            patch.object(database, "upsert_worker", AsyncMock(return_value=11)),
            patch.object(main.earnapp_recovery, "heartbeat_node", AsyncMock(return_value=True)),
            patch.object(database, "get_earnapp_logical_node", AsyncMock(return_value=authoritative)),
            patch.object(database, "record_earnapp_proxy_health", AsyncMock()) as record,
            patch.object(database, "confirm_worker_key", AsyncMock()),
            patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
            patch.object(main, "_maybe_auto_deploy_after_heartbeat", AsyncMock(return_value=None)),
            patch.object(main, "_spawn", side_effect=discard),
            patch.object(main.metrics, "record_heartbeat"),
        ):
            response = await main.api_worker_heartbeat(
                type("Request", (), {"headers": {"authorization": "Bearer key"}})(), body
            )

        ack = response["earnapp_assignment_acks"][0]
        assert ack["proxy_id"] == 12706
        assert ack["platform"] == "macos"
        assert ack["runtime_backend"] == "docker"
        record.assert_not_awaited()

    asyncio.run(run())


def test_server_hydrates_valid_but_stale_runtime_metadata_from_authority():
    async def run():
        body = main.WorkerHeartbeat(
            name="worker-a",
            client_id="worker-a",
            provider_states={
                "earnapp": {
                    "instances": [
                        {
                            "logical_node_id": "earnapp-ubuntu-legacy",
                            "generation": 2,
                            "device_id": "sdk-ubuntu-" + "d" * 28,
                            "proxy_id": 12706,
                            "platform": "macos",
                            "runtime_backend": "docker",
                            "expected_egress_ip": "198.51.100.stale",
                            "proxy_health": "healthy",
                        }
                    ]
                }
            },
        )
        authoritative = {
            "logical_node_id": "earnapp-ubuntu-legacy",
            "assigned_worker_id": 11,
            "generation": 2,
            "device_id": "sdk-ubuntu-" + "d" * 28,
            "platform": "ubuntu",
            "current_proxy_id": 12706,
            "expected_egress_ip": "198.51.100.206",
            "state": "ACTIVE",
        }

        def discard(coro):
            coro.close()

        with (
            patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
            patch.object(database, "upsert_worker", AsyncMock(return_value=11)),
            patch.object(main.earnapp_recovery, "heartbeat_node", AsyncMock(return_value=True)) as heartbeat,
            patch.object(database, "get_earnapp_logical_node", AsyncMock(return_value=authoritative)),
            patch.object(database, "record_earnapp_proxy_health", AsyncMock()) as record,
            patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
            patch.object(main, "_maybe_auto_deploy_after_heartbeat", AsyncMock(return_value=None)),
            patch.object(main, "_spawn", side_effect=discard),
            patch.object(database, "confirm_worker_key", AsyncMock()),
            patch.object(main.metrics, "record_heartbeat"),
        ):
            response = await main.api_worker_heartbeat(
                type("Request", (), {"headers": {"authorization": "Bearer key"}})(), body
            )

        heartbeat.assert_awaited_once_with(
            "earnapp-ubuntu-legacy",
            11,
            generation=2,
            device_id="sdk-ubuntu-" + "d" * 28,
            proxy_id=12706,
        )
        record.assert_not_awaited()
        ack = response["earnapp_assignment_acks"][0]
        assert ack["platform"] == "ubuntu"
        assert ack["runtime_backend"] == "lxd"
        assert ack["expected_egress_ip"] == "198.51.100.206"

    asyncio.run(run())


def test_server_heartbeat_cas_failure_does_not_ack_legacy_hydration():
    async def run():
        body = main.WorkerHeartbeat(
            name="worker-a",
            client_id="worker-a",
            provider_states={
                "earnapp": {
                    "instances": [
                        {
                            "logical_node_id": "earnapp-canary-test-sing-1",
                            "generation": 1,
                            "device_id": "sdk-mac-" + "c" * 32,
                            "proxy_id": 0,
                            "proxy_health": "healthy",
                            "observed_egress_ip": "171.251.97.103",
                        }
                    ]
                }
            },
        )
        authoritative = {
            "logical_node_id": "earnapp-canary-test-sing-1",
            "assigned_worker_id": 11,
            "generation": 1,
            "device_id": "sdk-mac-" + "c" * 32,
            "platform": "macos",
            "current_proxy_id": 12706,
            "expected_egress_ip": "171.251.97.103",
            "state": "ACTIVE",
        }

        def discard(coro):
            coro.close()

        with (
            patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
            patch.object(database, "upsert_worker", AsyncMock(return_value=11)),
            patch.object(main.earnapp_recovery, "heartbeat_node", AsyncMock(return_value=False)) as heartbeat,
            patch.object(database, "get_earnapp_logical_node", AsyncMock(return_value=authoritative)),
            patch.object(database, "record_earnapp_proxy_health", AsyncMock(return_value=True)) as record,
            patch.object(database, "confirm_worker_key", AsyncMock()),
            patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
            patch.object(main, "_maybe_auto_deploy_after_heartbeat", AsyncMock(return_value=None)),
            patch.object(main, "_spawn", side_effect=discard),
            patch.object(main.metrics, "record_heartbeat"),
        ):
            response = await main.api_worker_heartbeat(
                type("Request", (), {"headers": {"authorization": "Bearer key"}})(), body
            )

        heartbeat.assert_awaited_once_with(
            "earnapp-canary-test-sing-1",
            11,
            generation=1,
            device_id="sdk-mac-" + "c" * 32,
            proxy_id=12706,
        )
        assert "earnapp_assignment_acks" not in response
        assert response["earnapp_assignment_rejections"] == [
            {"logical_node_id": "earnapp-canary-test-sing-1", "generation": 1}
        ]
        record.assert_not_awaited()

    asyncio.run(run())


def test_server_heartbeat_cas_failure_does_not_record_or_rotate_complete_node():
    async def run():
        body = main.WorkerHeartbeat(
            name="worker-a",
            client_id="worker-a",
            provider_states={
                "earnapp": {
                    "instances": [
                        {
                            "logical_node_id": "earnapp-node-cas-failure",
                            "generation": 4,
                            "device_id": "sdk-mac-" + "f" * 32,
                            "proxy_id": 12706,
                            "platform": "macos",
                            "runtime_backend": "docker",
                            "expected_egress_ip": "198.51.100.208",
                            "proxy_health": "unhealthy",
                            "observed_egress_ip": "203.0.113.208",
                            "proxy_health_reason": "egress_mismatch",
                        }
                    ]
                }
            },
        )
        authoritative = {
            "logical_node_id": "earnapp-node-cas-failure",
            "assigned_worker_id": 11,
            "generation": 4,
            "device_id": "sdk-mac-" + "f" * 32,
            "platform": "macos",
            "current_proxy_id": 12706,
            "expected_egress_ip": "198.51.100.208",
            "state": "ACTIVE",
        }

        def discard(coro):
            coro.close()

        with (
            patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
            patch.object(database, "upsert_worker", AsyncMock(return_value=11)),
            patch.object(main.earnapp_recovery, "heartbeat_node", AsyncMock(return_value=False)),
            patch.object(database, "get_earnapp_logical_node", AsyncMock(return_value=authoritative)),
            patch.object(database, "record_earnapp_proxy_health", AsyncMock()) as record,
            patch.object(main, "_rotate_unhealthy_earnapp_node", AsyncMock()) as rotate,
            patch.object(database, "confirm_worker_key", AsyncMock()),
            patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
            patch.object(main, "_maybe_auto_deploy_after_heartbeat", AsyncMock(return_value=None)),
            patch.object(main, "_spawn", side_effect=discard),
            patch.object(main.metrics, "record_heartbeat"),
        ):
            response = await main.api_worker_heartbeat(
                type("Request", (), {"headers": {"authorization": "Bearer key"}})(), body
            )

        record.assert_not_awaited()
        rotate.assert_not_awaited()
        assert response["earnapp_assignment_rejections"] == [
            {"logical_node_id": "earnapp-node-cas-failure", "generation": 4}
        ]

    asyncio.run(run())


def test_server_heartbeat_skips_health_when_authority_lookup_fails():
    async def run():
        body = main.WorkerHeartbeat(
            name="worker-a",
            client_id="worker-a",
            provider_states={
                "earnapp": {
                    "instances": [
                        {
                            "logical_node_id": "earnapp-node-authority-unavailable",
                            "generation": 4,
                            "device_id": "sdk-mac-" + "g" * 32,
                            "proxy_id": 12706,
                            "platform": "macos",
                            "runtime_backend": "docker",
                            "expected_egress_ip": "198.51.100.209",
                            "proxy_health": "unhealthy",
                            "observed_egress_ip": "203.0.113.209",
                            "proxy_health_reason": "egress_mismatch",
                        }
                    ]
                }
            },
        )

        def discard(coro):
            coro.close()

        with (
            patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
            patch.object(database, "upsert_worker", AsyncMock(return_value=11)),
            patch.object(main.earnapp_recovery, "heartbeat_node", AsyncMock(return_value=True)) as heartbeat,
            patch.object(database, "get_earnapp_logical_node", AsyncMock(side_effect=RuntimeError("db unavailable"))),
            patch.object(database, "record_earnapp_proxy_health", AsyncMock()) as record,
            patch.object(main, "_rotate_unhealthy_earnapp_node", AsyncMock()) as rotate,
            patch.object(database, "confirm_worker_key", AsyncMock()),
            patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
            patch.object(main, "_maybe_auto_deploy_after_heartbeat", AsyncMock(return_value=None)),
            patch.object(main, "_spawn", side_effect=discard),
            patch.object(main.metrics, "record_heartbeat"),
        ):
            response = await main.api_worker_heartbeat(
                type("Request", (), {"headers": {"authorization": "Bearer key"}})(), body
            )

        heartbeat.assert_awaited_once_with(
            "earnapp-node-authority-unavailable",
            11,
            generation=4,
            device_id="sdk-mac-" + "g" * 32,
            proxy_id=12706,
        )
        record.assert_not_awaited()
        rotate.assert_not_awaited()
        assert response["earnapp_assignment_acks"] == [
            {"logical_node_id": "earnapp-node-authority-unavailable", "generation": 4}
        ]

    asyncio.run(run())


def test_server_fleet_state_exposes_only_secret_free_earnapp_evidence():
    async def run():
        worker = {"id": 11, "client_id": "worker-a"}
        earnapp_row = {
            "logical_node_id": "earnapp-node-a",
            "assigned_worker_id": 11,
            "platform": "macos",
            "state": "ACTIVE",
            "generation": 3,
            "current_proxy_id": 77,
            "proxy_health": "healthy",
            "observed_egress_ip": "198.51.100.77",
            "expected_egress_ip": "198.51.100.77",
            "proxy_checked_at": "2026-08-27 10:00:00",
            "credentials_enc": "refresh-secret",
            "identity_profile_enc": "device-secret",
            "proxy_password": "proxy-secret",
        }
        with (
            patch.object(database, "get_worker_proxy_assignment", AsyncMock(return_value=None)),
            patch.object(database, "list_myst_wallets", AsyncMock(return_value=[])),
            patch.object(database, "list_nkn_wallets", AsyncMock(return_value=[])),
            patch.object(database, "list_earnapp_logical_nodes", AsyncMock(return_value=[earnapp_row])),
        ):
            states = await main._worker_provider_states(worker)

        assert states["earnapp"] == {
            "instances": [
                {
                    "logical_node_id": "earnapp-node-a",
                    "platform": "macos",
                    "state": "ACTIVE",
                    "generation": 3,
                    "proxy_id": 77,
                    "proxy_health": "healthy",
                    "observed_egress_ip": "198.51.100.77",
                    "expected_egress_ip": "198.51.100.77",
                    "proxy_checked_at": "2026-08-27 10:00:00",
                }
            ],
            "online": 1,
            "offline": 0,
        }
        serialized = json.dumps(states)
        assert "refresh-secret" not in serialized
        assert "device-secret" not in serialized
        assert "proxy-secret" not in serialized

    asyncio.run(run())


@pytest.mark.asyncio
async def test_unhealthy_node_rotation_commits_only_after_matching_worker_ack(monkeypatch):
    node_id = "earnapp-proxy-w11-ipv4-001"
    device_id = "sdk-mac-" + "e" * 32
    candidate = {
        "proxy_id": 22,
        "host": "candidate.example",
        "port": 1080,
        "protocol": "socks5",
        "username": "user",
        "password": "secret",
        "exit_ip": "198.51.100.22",
        "country_code": "VN",
        "ip_type": "residential",
    }
    calls: list[tuple[str, dict[str, object]]] = []

    async def worker_call(_worker_id, _method, path, *, json=None, **_kwargs):
        calls.append((path, dict(json or {})))
        if path.endswith("/proxy/apply"):
            return {
                "ok": True,
                "binding_version": json["binding_version"],
                "proxy_id": 22,
                "observed_egress_ip": "198.51.100.22",
            }
        return {
            "ok": True,
            "binding_version": json["binding_version"],
            "action": "confirmed",
            "proxy_id": 22,
        }

    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(
            return_value={
                "logical_node_id": node_id,
                "assigned_worker_id": 11,
                "generation": 4,
                "current_proxy_id": 11,
                "proxy_health": "unhealthy",
                "state": "ACTIVE",
                "device_id": device_id,
            }
        ),
    )
    monkeypatch.setattr(database, "find_available_earnapp_proxy_for_node", AsyncMock(return_value=candidate))
    monkeypatch.setattr(database, "reserve_earnapp_proxy_candidate", AsyncMock(return_value=candidate))
    monkeypatch.setattr(database, "release_earnapp_proxy_reservation", AsyncMock(return_value=True))
    commit = AsyncMock(return_value={"logical_node_id": node_id, "current_proxy_id": 22})
    monkeypatch.setattr(database, "commit_earnapp_proxy_rotation", commit)
    monkeypatch.setattr(main, "_proxy_to_worker", worker_call)

    assert await main._rotate_unhealthy_earnapp_node(node_id, 11, generation=4, expected_proxy_id=11)
    assert [path for path, _payload in calls] == [
        f"/api/earnapp/nodes/{node_id}/proxy/apply",
        f"/api/earnapp/nodes/{node_id}/proxy/finalize",
    ]
    assert calls[0][1]["expected_proxy_id"] == 11
    assert calls[0][1]["proxy"]["password"] == "secret"
    assert calls[1][1]["commit"] is True
    commit.assert_awaited_once_with(
        node_id,
        11,
        expected_generation=4,
        expected_proxy_id=11,
        new_proxy_id=22,
        binding_version=calls[0][1]["binding_version"],
    )


@pytest.mark.asyncio
async def test_unhealthy_node_rotation_rolls_runtime_back_when_database_cas_loses(monkeypatch):
    node_id = "earnapp-proxy-w11-ipv4-002"
    device_id = "sdk-ios-" + "f" * 32
    candidate = {
        "proxy_id": 23,
        "host": "candidate.example",
        "port": 8080,
        "protocol": "http",
        "exit_ip": "198.51.100.23",
        "country_code": "VN",
        "ip_type": "residential",
    }
    calls: list[tuple[str, dict[str, object]]] = []

    async def worker_call(_worker_id, _method, path, *, json=None, **_kwargs):
        calls.append((path, dict(json or {})))
        if path.endswith("/proxy/apply"):
            return {
                "ok": True,
                "binding_version": json["binding_version"],
                "proxy_id": 23,
                "observed_egress_ip": "198.51.100.23",
            }
        return {
            "ok": True,
            "binding_version": json["binding_version"],
            "action": "rolled_back",
            "proxy_id": 11,
        }

    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(
            return_value={
                "logical_node_id": node_id,
                "assigned_worker_id": 11,
                "generation": 7,
                "current_proxy_id": 11,
                "proxy_health": "unhealthy",
                "state": "ACTIVE",
                "device_id": device_id,
            }
        ),
    )
    monkeypatch.setattr(database, "find_available_earnapp_proxy_for_node", AsyncMock(return_value=candidate))
    monkeypatch.setattr(database, "reserve_earnapp_proxy_candidate", AsyncMock(return_value=candidate))
    monkeypatch.setattr(database, "release_earnapp_proxy_reservation", AsyncMock(return_value=True))
    monkeypatch.setattr(database, "commit_earnapp_proxy_rotation", AsyncMock(return_value=None))
    monkeypatch.setattr(main, "_proxy_to_worker", worker_call)

    assert not await main._rotate_unhealthy_earnapp_node(node_id, 11, generation=7, expected_proxy_id=11)
    assert calls[-1][0].endswith("/proxy/finalize")
    assert calls[-1][1]["commit"] is False


def test_find_earnapp_rotation_candidate_respects_platform_country_and_exclusive_egress(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "candidate.db"):
            await database.init_db()
            await earnapp_accounts.import_account(_account())
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            old_proxy = await _proxy(provider_id, 4)
            vn_candidate = await _proxy(provider_id, 5)
            await database.update_proxy_endpoint_intelligence(
                vn_candidate,
                {
                    "country_code": "VN",
                    "country_name": "Vietnam",
                    "location_source": "test",
                    "location_confidence": "high",
                },
            )
            worker_id = await database.upsert_worker("worker-a", "worker-a", "http://worker")
            await database.assign_earnapp_account("earnapp-candidate-node", platform="macos")
            await database.bind_earnapp_node_runtime(
                "earnapp-candidate-node", worker_id, device_id="sdk-mac-" + "d" * 32, proxy_id=old_proxy
            )
            candidate = await database.find_available_earnapp_proxy_for_node(
                "earnapp-candidate-node", worker_id, expected_proxy_id=old_proxy
            )
            assert candidate and candidate["proxy_id"] == vn_candidate

    asyncio.run(run())


def test_earnapp_proxy_rotation_candidate_reservation_is_exclusive_and_released(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "reservation.db"):
            await database.init_db()
            await earnapp_accounts.import_account(_account())
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            old_proxy = await _proxy(provider_id, 30)
            candidate = await _proxy(provider_id, 31)
            worker_id = await database.upsert_worker("worker-reservation", "worker-reservation", "http://worker")
            await database.assign_earnapp_account("earnapp-reservation-node", platform="macos")
            await database.bind_earnapp_node_runtime(
                "earnapp-reservation-node",
                worker_id,
                device_id="sdk-mac-" + "1" * 32,
                proxy_id=old_proxy,
            )
            first = await database.reserve_earnapp_proxy_candidate(
                "earnapp-reservation-node",
                worker_id,
                generation=1,
                expected_proxy_id=old_proxy,
                candidate_proxy_id=candidate,
                binding_version="rotation_reservation_1",
            )
            second = await database.reserve_earnapp_proxy_candidate(
                "earnapp-reservation-node-2",
                worker_id,
                generation=1,
                expected_proxy_id=old_proxy,
                candidate_proxy_id=candidate,
                binding_version="rotation_reservation_2",
            )

            assert first and first["proxy_id"] == candidate
            assert second is None
            active = await database.get_earnapp_proxy_reservation(
                "earnapp-reservation-node", binding_version="rotation_reservation_1"
            )
            assert active and active["state"] == "ACTIVE"
            assert await database.release_earnapp_proxy_reservation(
                "earnapp-reservation-node", binding_version="rotation_reservation_1", reason="test"
            )
            assert (
                await database.get_earnapp_proxy_reservation(
                    "earnapp-reservation-node", binding_version="rotation_reservation_1"
                )
            )["state"] == "RELEASED"

    asyncio.run(run())


def test_active_earnapp_rotation_reservation_blocks_every_proxy_allocator(tmp_path):
    async def run():
        with (
            patch.object(database, "DB_DIR", tmp_path),
            patch.object(database, "DB_PATH", tmp_path / "reservation-allocators.db"),
        ):
            await database.init_db()
            await earnapp_accounts.import_account(_account("profile-node"))
            control_account = await earnapp_accounts.import_account(_account("profile-control"))
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            old_proxy = await _proxy(provider_id, 40)
            reserved_proxy = await _proxy(provider_id, 41)
            backup_proxy = await _proxy(provider_id, 42)
            node_worker = await database.upsert_worker("worker-node", "worker-node", "http://node")
            other_worker = await database.upsert_worker("worker-other", "worker-other", "http://other")
            await database.assign_earnapp_account("earnapp-reserved-node", platform="macos")
            await database.bind_earnapp_node_runtime(
                "earnapp-reserved-node",
                node_worker,
                device_id="sdk-mac-" + "4" * 32,
                proxy_id=old_proxy,
            )
            reserved = await database.reserve_earnapp_proxy_candidate(
                "earnapp-reserved-node",
                node_worker,
                generation=1,
                expected_proxy_id=old_proxy,
                candidate_proxy_id=reserved_proxy,
                binding_version="rotation_all_allocators_1",
            )
            assert reserved and reserved["proxy_id"] == reserved_proxy

            assert not await database.set_worker_proxy_assignment(other_worker, reserved_proxy)
            candidate = await database.find_available_proxy_for_worker(other_worker)
            assert candidate and candidate["proxy_id"] == backup_proxy

            legacy = await database.lease_proxy_for_worker(other_worker)
            assert legacy and legacy["proxy_id"] == backup_proxy
            assert await database.clear_worker_proxy_assignment(other_worker)

            scoped = await database.lease_proxy_for_provider_instance(
                "other-provider", other_worker, "other-provider-node"
            )
            assert scoped and scoped["proxy_id"] == backup_proxy
            assert await database.release_proxy_for_provider_instance(
                "other-provider", other_worker, "other-provider-node"
            )

            control = await database.lease_earnapp_account_control_proxy(control_account)
            assert control and control["proxy_id"] == backup_proxy

    asyncio.run(run())


def test_active_earnapp_rotation_reservation_is_excluded_from_capacity_counters(tmp_path):
    async def run():
        with (
            patch.object(database, "DB_DIR", tmp_path),
            patch.object(database, "DB_PATH", tmp_path / "reservation-capacity.db"),
        ):
            await database.init_db()
            await earnapp_accounts.import_account(_account("profile-capacity"))
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            old_proxy = await _proxy(provider_id, 50)
            reserved_proxy = await _proxy(provider_id, 51)
            backup_proxy = await _proxy(provider_id, 52)
            worker_id = await database.upsert_worker("worker-capacity", "worker-capacity", "http://capacity")
            await database.assign_earnapp_account("earnapp-capacity-node", platform="macos")
            await database.bind_earnapp_node_runtime(
                "earnapp-capacity-node",
                worker_id,
                device_id="sdk-mac-" + "5" * 32,
                proxy_id=old_proxy,
            )
            reservation = await database.reserve_earnapp_proxy_candidate(
                "earnapp-capacity-node",
                worker_id,
                generation=1,
                expected_proxy_id=old_proxy,
                candidate_proxy_id=reserved_proxy,
                binding_version="rotation_capacity_1",
            )
            assert reservation and reservation["proxy_id"] == reserved_proxy

            capacity = await database.get_earnapp_proxy_capacity()
            assert capacity["eligible"] == 3
            assert capacity["leaseable"] == 1

            page = await database.list_proxy_pool_page(page_size=100)
            rows = {int(row["id"]): row for row in page["items"]}
            assert rows[reserved_proxy]["earnapp_eligibility"] == "eligible"
            assert page["counts"]["earnapp_leaseable"] == 1
            assert rows[backup_proxy]["id"] == backup_proxy

    asyncio.run(run())
