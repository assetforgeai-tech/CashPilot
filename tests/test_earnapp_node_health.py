from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
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


def test_earnapp_runtime_authority_reports_exact_identity_proxy_and_components(monkeypatch):
    main_container = MagicMock(
        id="main-id",
        status="running",
        labels={
            "cashpilot.managed": "true",
            "cashpilot.service": "earnapp-runtime-authority",
            "cashpilot.provider": "earnapp",
            "cashpilot.earnapp.logical_node_id": "earnapp-runtime-authority",
            "cashpilot.earnapp.device_id": "sdk-mac-" + "1" * 32,
            "cashpilot.earnapp.platform": "darwin",
            "cashpilot.earnapp.generation": "3",
        },
    )
    sidecar_container = MagicMock(
        id="sidecar-id",
        status="running",
        labels={
            "cashpilot.managed": "true",
            "cashpilot.service": "earnapp-runtime-authority",
            "cashpilot.provider": "earnapp",
            "cashpilot.role": "egress-sidecar",
        },
    )
    main_container.attrs = {"HostConfig": {"NetworkMode": "container:sidecar-id"}}
    sidecar_container.attrs = {
        "Mounts": [{"Destination": "/etc/sing-box", "RW": True}],
    }
    client = MagicMock()
    monkeypatch.setattr(
        orchestrator,
        "_find_earnapp_runtime_container",
        lambda _client, _slug, *, sidecar: sidecar_container if sidecar else main_container,
    )
    monkeypatch.setattr(orchestrator, "_get_client", lambda: client)
    monkeypatch.setattr(
        orchestrator,
        "probe_service_egress",
        lambda _slug: {"running": True, "probe_ok": True, "observed_egress_ip": "198.51.100.61"},
    )

    assert orchestrator.earnapp_runtime_authority("earnapp-runtime-authority") == {
        "logical_node_id": "earnapp-runtime-authority",
        "generation": 3,
        "platform": "macos",
        "device_id": "sdk-mac-" + "1" * 32,
        "main_container_id": "main-id",
        "sidecar_container_id": "sidecar-id",
        "main_running": True,
        "sidecar_running": True,
        "observed_egress_ip": "198.51.100.61",
        "probe_ok": True,
    }


def test_worker_runtime_authority_is_cas_scoped_and_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    node_id = "earnapp-runtime-authority"
    device_id = "sdk-mac-" + "1" * 32
    worker_api._save_earnapp_state(
        node_id,
        {
            "logical_node_id": node_id,
            "generation": 3,
            "device_id": device_id,
            "platform": "macos",
            "runtime_backend": "docker",
            "proxy_id": 61,
            "expected_egress_ip": "198.51.100.61",
        },
    )
    authority = {
        "logical_node_id": node_id,
        "generation": 3,
        "platform": "macos",
        "device_id": device_id,
        "main_container_id": "main-id",
        "sidecar_container_id": "sidecar-id",
        "main_running": True,
        "sidecar_running": True,
        "observed_egress_ip": "198.51.100.61",
        "probe_ok": True,
    }
    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(orchestrator, "earnapp_runtime_authority", return_value=authority),
    ):
        result = asyncio.run(
            worker_api.api_earnapp_node_runtime_authority(
                MagicMock(),
                node_id,
                generation=3,
                device_id=device_id,
                expected_proxy_id=61,
            )
        )
        with pytest.raises(worker_api.HTTPException) as exc:
            asyncio.run(
                worker_api.api_earnapp_node_runtime_authority(
                    MagicMock(),
                    node_id,
                    generation=3,
                    device_id=device_id,
                    expected_proxy_id=60,
                )
            )

    assert result["proxy_id"] == 61
    assert result["expected_egress_ip"] == "198.51.100.61"
    assert result["observed_egress_ip"] == "198.51.100.61"
    assert exc.value.status_code == 409
    saved = json.loads(Path(tmp_path, "earnapp-nodes", f"{node_id}.json").read_text(encoding="utf-8"))
    assert saved["proxy_id"] == 61


def test_worker_runtime_authority_normalizes_matching_linux_platform(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    node_id = "earnapp-runtime-platform"
    device_id = "sdk-node-" + "a" * 32
    worker_api._save_earnapp_state(
        node_id,
        {
            "logical_node_id": node_id,
            "generation": 4,
            "device_id": device_id,
            "platform": "linux",
            "runtime_backend": "docker",
            "proxy_id": 71,
            "expected_egress_ip": "198.51.100.71",
        },
    )
    authority = {
        "logical_node_id": node_id,
        "generation": 4,
        "platform": "ubuntu",
        "device_id": device_id,
        "main_container_id": "main-id",
        "sidecar_container_id": "sidecar-id",
        "main_running": True,
        "sidecar_running": True,
        "observed_egress_ip": "198.51.100.71",
        "probe_ok": True,
    }
    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(orchestrator, "earnapp_runtime_authority", return_value=authority),
    ):
        result = asyncio.run(
            worker_api.api_earnapp_node_runtime_authority(
                MagicMock(),
                node_id,
                generation=4,
                device_id=device_id,
                expected_proxy_id=71,
            )
        )

    assert result["platform"] == "ubuntu"


def test_worker_runtime_authority_rejects_normalized_platform_mismatch(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    node_id = "earnapp-runtime-platform-mismatch"
    device_id = "sdk-node-" + "b" * 32
    worker_api._save_earnapp_state(
        node_id,
        {
            "logical_node_id": node_id,
            "generation": 4,
            "device_id": device_id,
            "platform": "linux",
            "runtime_backend": "docker",
            "proxy_id": 72,
            "expected_egress_ip": "198.51.100.72",
        },
    )
    authority = {
        "logical_node_id": node_id,
        "generation": 4,
        "platform": "macos",
        "device_id": device_id,
        "main_container_id": "main-id",
        "sidecar_container_id": "sidecar-id",
        "main_running": True,
        "sidecar_running": True,
        "observed_egress_ip": "198.51.100.72",
        "probe_ok": True,
    }
    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(orchestrator, "earnapp_runtime_authority", return_value=authority),
        pytest.raises(worker_api.HTTPException) as exc,
    ):
        asyncio.run(
            worker_api.api_earnapp_node_runtime_authority(
                MagicMock(),
                node_id,
                generation=4,
                device_id=device_id,
                expected_proxy_id=72,
            )
        )

    assert exc.value.status_code == 409


def test_worker_runtime_authority_serializes_concurrent_reads_with_node_mutations(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    node_id = "earnapp-runtime-serialized"
    device_id = "sdk-mac-" + "c" * 32
    worker_api._save_earnapp_state(
        node_id,
        {
            "logical_node_id": node_id,
            "generation": 4,
            "device_id": device_id,
            "platform": "macos",
            "runtime_backend": "docker",
            "proxy_id": 73,
            "expected_egress_ip": "198.51.100.73",
        },
    )
    authority = {
        "logical_node_id": node_id,
        "generation": 4,
        "platform": "macos",
        "device_id": device_id,
        "main_container_id": "main-id",
        "sidecar_container_id": "sidecar-id",
        "main_running": True,
        "sidecar_running": True,
        "observed_egress_ip": "198.51.100.73",
        "probe_ok": True,
    }
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def blocking_authority(_slug):
        nonlocal calls
        calls += 1
        started.set()
        if not release.wait(2):
            raise AssertionError("authority probe did not get released")
        return authority

    async def run():
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(orchestrator, "earnapp_runtime_authority", side_effect=blocking_authority),
        ):
            first = asyncio.create_task(
                worker_api.api_earnapp_node_runtime_authority(
                    MagicMock(), node_id, generation=4, device_id=device_id, expected_proxy_id=73
                )
            )
            assert await asyncio.to_thread(started.wait, 1)
            second = asyncio.create_task(
                worker_api.api_earnapp_node_runtime_authority(
                    MagicMock(), node_id, generation=4, device_id=device_id, expected_proxy_id=73
                )
            )
            await asyncio.sleep(0.05)
            assert calls == 1
            release.set()
            await asyncio.gather(first, second)

    asyncio.run(run())
    assert calls == 2


@pytest.mark.asyncio
async def test_server_runtime_adoption_requires_matching_worker_authority(monkeypatch):
    node_id = "earnapp-runtime-authority"
    device_id = "sdk-mac-" + "1" * 32
    node = {
        "logical_node_id": node_id,
        "assigned_worker_id": 11,
        "generation": 3,
        "device_id": device_id,
        "platform": "macos",
        "state": "ACTIVE",
        "current_proxy_id": 60,
    }
    authority = {
        "logical_node_id": node_id,
        "generation": 3,
        "platform": "macos",
        "device_id": device_id,
        "proxy_id": 61,
        "expected_egress_ip": "198.51.100.61",
        "observed_egress_ip": "198.51.100.61",
        "main_container_id": "main-id",
        "sidecar_container_id": "sidecar-id",
        "main_running": True,
        "sidecar_running": True,
        "probe_ok": True,
    }
    monkeypatch.setattr(main.provider_runtime, "mutation_block", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "get_earnapp_logical_node", AsyncMock(return_value=node))
    monkeypatch.setattr(main, "_proxy_to_worker", AsyncMock(return_value=authority))
    adopt = AsyncMock(return_value={**node, "current_proxy_id": 61})
    monkeypatch.setattr(database, "adopt_earnapp_runtime_proxy", adopt)
    monkeypatch.setattr(database, "record_health_event", AsyncMock())

    result = await main._adopt_earnapp_runtime_proxy(
        node_id,
        11,
        generation=3,
        device_id=device_id,
        expected_database_proxy_id=60,
        expected_runtime_proxy_id=61,
        expected_runtime_egress_ip="198.51.100.61",
    )

    assert result and result["current_proxy_id"] == 61
    adopt.assert_awaited_once_with(
        node_id,
        11,
        expected_generation=3,
        device_id=device_id,
        expected_database_proxy_id=60,
        runtime_proxy_id=61,
        expected_runtime_egress_ip="198.51.100.61",
        observed_runtime_egress_ip="198.51.100.61",
        container_id="main-id",
        sidecar_id="sidecar-id",
    )


@pytest.mark.asyncio
async def test_server_runtime_adoption_serializes_with_rotation_for_same_node(monkeypatch):
    node_id = "earnapp-runtime-adoption-serialized"
    device_id = "sdk-mac-" + "d" * 32
    node = {
        "logical_node_id": node_id,
        "assigned_worker_id": 11,
        "generation": 3,
        "device_id": device_id,
        "platform": "macos",
        "state": "ACTIVE",
        "current_proxy_id": 60,
    }
    authority = {
        "logical_node_id": node_id,
        "generation": 3,
        "platform": "macos",
        "device_id": device_id,
        "proxy_id": 61,
        "expected_egress_ip": "198.51.100.61",
        "observed_egress_ip": "198.51.100.61",
        "main_container_id": "main-id",
        "sidecar_container_id": "sidecar-id",
        "main_running": True,
        "sidecar_running": True,
        "probe_ok": True,
    }
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking_worker(*_args, **_kwargs):
        started.set()
        await release.wait()
        return authority

    monkeypatch.setattr(main.provider_runtime, "mutation_block", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "get_earnapp_logical_node", AsyncMock(return_value=node))
    worker_call = AsyncMock(side_effect=blocking_worker)
    monkeypatch.setattr(main, "_proxy_to_worker", worker_call)
    monkeypatch.setattr(
        database, "adopt_earnapp_runtime_proxy", AsyncMock(return_value={**node, "current_proxy_id": 61})
    )
    monkeypatch.setattr(database, "record_health_event", AsyncMock())

    first = asyncio.create_task(
        main._adopt_earnapp_runtime_proxy(
            node_id,
            11,
            generation=3,
            device_id=device_id,
            expected_database_proxy_id=60,
            expected_runtime_proxy_id=61,
            expected_runtime_egress_ip="198.51.100.61",
        )
    )
    await started.wait()
    second = asyncio.create_task(
        main._adopt_earnapp_runtime_proxy(
            node_id,
            11,
            generation=3,
            device_id=device_id,
            expected_database_proxy_id=60,
            expected_runtime_proxy_id=61,
            expected_runtime_egress_ip="198.51.100.61",
        )
    )
    await asyncio.sleep(0)
    assert worker_call.await_count == 1
    release.set()
    first_result, second_result = await asyncio.gather(first, second)
    assert first_result and second_result is None


@pytest.mark.asyncio
async def test_server_runtime_adoption_rejects_worker_identity_or_egress_mismatch(monkeypatch):
    node_id = "earnapp-runtime-authority-reject"
    device_id = "sdk-mac-" + "2" * 32
    node = {
        "logical_node_id": node_id,
        "assigned_worker_id": 11,
        "generation": 3,
        "device_id": device_id,
        "platform": "macos",
        "state": "ACTIVE",
        "current_proxy_id": 60,
    }
    monkeypatch.setattr(main.provider_runtime, "mutation_block", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "get_earnapp_logical_node", AsyncMock(return_value=node))
    adopt = AsyncMock()
    monkeypatch.setattr(database, "adopt_earnapp_runtime_proxy", adopt)
    monkeypatch.setattr(
        main,
        "_proxy_to_worker",
        AsyncMock(
            return_value={
                "logical_node_id": node_id,
                "generation": 3,
                "device_id": "sdk-mac-" + "3" * 32,
                "proxy_id": 61,
                "expected_egress_ip": "198.51.100.61",
                "observed_egress_ip": "203.0.113.10",
                "main_container_id": "main-id",
                "sidecar_container_id": "sidecar-id",
                "main_running": True,
                "sidecar_running": True,
                "probe_ok": True,
            }
        ),
    )

    assert not await main._adopt_earnapp_runtime_proxy(
        node_id,
        11,
        generation=3,
        device_id=device_id,
        expected_database_proxy_id=60,
        expected_runtime_proxy_id=61,
        expected_runtime_egress_ip="198.51.100.61",
    )
    adopt.assert_not_awaited()


def test_earnapp_runtime_authority_reads_ubuntu_uuid_from_identity_volume(monkeypatch):
    main_container = MagicMock(id="ubuntu-main", status="running")
    main_container.labels = {
        "cashpilot.earnapp.logical_node_id": "earnapp-ubuntu-authority",
        "cashpilot.earnapp.generation": "4",
        "cashpilot.earnapp.platform": "linux",
    }
    main_container.attrs = {"HostConfig": {"NetworkMode": "container:ubuntu-sidecar"}}
    main_container.exec_run.return_value = MagicMock(exit_code=0, output=b"sdk-node-" + b"a" * 32)
    sidecar_container = MagicMock(id="ubuntu-sidecar", status="running")
    sidecar_container.labels = {
        "cashpilot.managed": "true",
        "cashpilot.service": "earnapp-ubuntu-authority",
        "cashpilot.provider": "earnapp",
        "cashpilot.role": "egress-sidecar",
    }
    sidecar_container.attrs = {"Mounts": [{"Destination": "/etc/sing-box", "RW": True}]}
    client = MagicMock()
    monkeypatch.setattr(
        orchestrator,
        "_find_earnapp_runtime_container",
        lambda _client, _slug, *, sidecar: sidecar_container if sidecar else main_container,
    )
    monkeypatch.setattr(orchestrator, "_get_client", lambda: client)
    monkeypatch.setattr(
        orchestrator,
        "probe_service_egress",
        lambda _slug: {"running": True, "probe_ok": True, "observed_egress_ip": "198.51.100.80"},
    )

    result = orchestrator.earnapp_runtime_authority("earnapp-ubuntu-authority")

    assert result["device_id"] == "sdk-node-" + "a" * 32
    assert result["platform"] == "ubuntu"


def test_earnapp_runtime_authority_rejects_unrelated_network_namespace(monkeypatch):
    main_container = MagicMock(
        id="main-id",
        status="running",
        labels={
            "cashpilot.earnapp.logical_node_id": "earnapp-runtime-authority",
            "cashpilot.earnapp.generation": "3",
            "cashpilot.earnapp.platform": "darwin",
            "cashpilot.earnapp.device_id": "sdk-mac-" + "1" * 32,
        },
        attrs={"HostConfig": {"NetworkMode": "bridge"}},
    )
    sidecar_container = MagicMock(
        id="sidecar-id",
        status="running",
        labels={"cashpilot.provider": "earnapp", "cashpilot.role": "egress-sidecar"},
        attrs={"Mounts": [{"Destination": "/etc/sing-box", "RW": True}]},
    )
    monkeypatch.setattr(
        orchestrator,
        "_find_earnapp_runtime_container",
        lambda _client, _slug, *, sidecar: sidecar_container if sidecar else main_container,
    )
    monkeypatch.setattr(orchestrator, "_get_client", lambda: MagicMock())

    with pytest.raises(RuntimeError, match="network namespace"):
        orchestrator.earnapp_runtime_authority("earnapp-runtime-authority")


@pytest.mark.asyncio
async def test_owner_runtime_adoption_endpoint_forwards_explicit_preconditions(monkeypatch):
    node_id = "earnapp-runtime-authority-endpoint"
    device_id = "sdk-mac-" + "4" * 32
    adopt = AsyncMock(return_value={"logical_node_id": node_id, "current_proxy_id": 61})
    monkeypatch.setattr(main, "_adopt_earnapp_runtime_proxy", adopt)

    result = await main.api_adopt_earnapp_runtime_proxy(
        MagicMock(),
        node_id,
        main.EarnAppRuntimeProxyAdoptRequest(
            worker_id=11,
            generation=3,
            device_id=device_id,
            expected_database_proxy_id=60,
            expected_runtime_proxy_id=61,
            expected_runtime_egress_ip="198.51.100.61",
        ),
        {"r": "owner"},
    )

    assert result["current_proxy_id"] == 61
    adopt.assert_awaited_once_with(
        node_id,
        11,
        generation=3,
        device_id=device_id,
        expected_database_proxy_id=60,
        expected_runtime_proxy_id=61,
        expected_runtime_egress_ip="198.51.100.61",
    )


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


def test_adopt_earnapp_runtime_proxy_repairs_only_matching_split_brain_assignment(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "adopt.db"):
            await database.init_db()
            await earnapp_accounts.import_account(_account())
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            database_proxy = await _proxy(provider_id, 60)
            runtime_proxy = await _proxy(provider_id, 61)
            worker_id = await database.upsert_worker("worker-adopt", "worker-adopt", "http://worker")
            node_id = "earnapp-runtime-adopt"
            identity = "sdk-mac-" + "6" * 32
            await database.assign_earnapp_account(node_id, platform="macos")
            await database.bind_earnapp_node_runtime(node_id, worker_id, device_id=identity, proxy_id=database_proxy)
            await database.save_provider_instance(
                "earnapp",
                node_id,
                worker_id=worker_id,
                mode="proxy",
                container_id="stale-container",
                sidecar_id="",
                proxy_id=database_proxy,
                status="verification_pending",
            )

            adopted = await database.adopt_earnapp_runtime_proxy(
                node_id,
                worker_id,
                expected_generation=1,
                device_id=identity,
                expected_database_proxy_id=database_proxy,
                runtime_proxy_id=runtime_proxy,
                expected_runtime_egress_ip="198.51.100.61",
                observed_runtime_egress_ip="198.51.100.61",
                container_id="live-container",
                sidecar_id="live-sidecar",
            )

            assert adopted and adopted["current_proxy_id"] == runtime_proxy
            assert adopted["preferred_proxy_id"] == database_proxy
            node = await database.get_earnapp_logical_node(node_id)
            assert node["proxy_health"] == "healthy"
            assert node["expected_egress_ip"] == "198.51.100.61"
            assert node["observed_egress_ip"] == "198.51.100.61"
            instance = await database.get_provider_instance(node_id)
            assert instance["proxy_id"] == runtime_proxy
            assert instance["container_id"] == "live-container"
            assert instance["sidecar_id"] == "live-sidecar"
            leases = await database.list_provider_proxy_leases(provider_slug="earnapp")
            assert len([row for row in leases if row["instance_id"] == node_id and not row["released_at"]]) == 1
            assert any(
                row["instance_id"] == node_id
                and row["proxy_id"] == database_proxy
                and row["release_reason"] == "EARNAPP_RUNTIME_PROXY_ADOPTED"
                for row in leases
            )

            # Exact replay is idempotent and cannot create a duplicate lease.
            replay = await database.adopt_earnapp_runtime_proxy(
                node_id,
                worker_id,
                expected_generation=1,
                device_id=identity,
                expected_database_proxy_id=runtime_proxy,
                runtime_proxy_id=runtime_proxy,
                expected_runtime_egress_ip="198.51.100.61",
                observed_runtime_egress_ip="198.51.100.61",
                container_id="live-container",
                sidecar_id="live-sidecar",
            )
            assert replay and replay["current_proxy_id"] == runtime_proxy
            leases = await database.list_provider_proxy_leases(provider_slug="earnapp")
            assert len([row for row in leases if row["instance_id"] == node_id and not row["released_at"]]) == 1

    asyncio.run(run())


def test_adopt_earnapp_runtime_proxy_rejects_stale_or_conflicting_preconditions(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "reject.db"):
            await database.init_db()
            await earnapp_accounts.import_account(_account())
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            database_proxy = await _proxy(provider_id, 62)
            runtime_proxy = await _proxy(provider_id, 63)
            conflicting_proxy = await _proxy(provider_id, 64)
            worker_id = await database.upsert_worker("worker-adopt", "worker-adopt", "http://worker")
            other_worker = await database.upsert_worker("worker-other", "worker-other", "http://other")
            node_id = "earnapp-runtime-adopt-reject"
            identity = "sdk-mac-" + "7" * 32
            await database.assign_earnapp_account(node_id, platform="macos")
            await database.bind_earnapp_node_runtime(node_id, worker_id, device_id=identity, proxy_id=database_proxy)
            db = await database._get_db()
            await db.execute(
                """
                INSERT INTO provider_proxy_leases
                    (provider_slug, worker_id, instance_id, proxy_id, exit_ip)
                VALUES ('other-provider', ?, 'other-node', ?, '198.51.100.64')
                """,
                (other_worker, conflicting_proxy),
            )
            await db.commit()

            common = {
                "logical_node_id": node_id,
                "worker_id": worker_id,
                "expected_generation": 1,
                "device_id": identity,
                "expected_database_proxy_id": database_proxy,
                "runtime_proxy_id": runtime_proxy,
                "expected_runtime_egress_ip": "198.51.100.63",
                "observed_runtime_egress_ip": "198.51.100.63",
                "container_id": "live-container",
                "sidecar_id": "live-sidecar",
            }
            assert await database.adopt_earnapp_runtime_proxy(**{**common, "expected_generation": 2}) is None
            assert await database.adopt_earnapp_runtime_proxy(**{**common, "device_id": "sdk-mac-" + "8" * 32}) is None
            assert (
                await database.adopt_earnapp_runtime_proxy(
                    **{
                        **common,
                        "runtime_proxy_id": conflicting_proxy,
                        "expected_runtime_egress_ip": "198.51.100.64",
                        "observed_runtime_egress_ip": "198.51.100.64",
                    }
                )
                is None
            )
            assert (
                await database.adopt_earnapp_runtime_proxy(**{**common, "observed_runtime_egress_ip": "203.0.113.10"})
                is None
            )
            node = await database.get_earnapp_logical_node(node_id)
            assert node["current_proxy_id"] == database_proxy

    asyncio.run(run())


@pytest.mark.parametrize("conflict_kind", ["legacy", "control", "reservation"])
def test_adopt_earnapp_runtime_proxy_rejects_other_active_proxy_ownership(tmp_path, conflict_kind):
    async def run():
        with (
            patch.object(database, "DB_DIR", tmp_path),
            patch.object(database, "DB_PATH", tmp_path / f"{conflict_kind}.db"),
        ):
            await database.init_db()
            account_id = await earnapp_accounts.import_account(_account("profile-target"))
            control_account_id = await earnapp_accounts.import_account(_account("profile-control"))
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            database_proxy = await _proxy(provider_id, 74)
            runtime_proxy = await _proxy(provider_id, 75)
            conflict_proxy = await _proxy(provider_id, 76)
            db = await database._get_db()
            await db.execute(
                "UPDATE proxy_endpoints SET exit_ip = ? WHERE id = ?",
                ("198.51.100.75", conflict_proxy),
            )
            worker_id = await database.upsert_worker("worker-adopt-conflict", "worker-adopt-conflict", "http://worker")
            other_worker = await database.upsert_worker("worker-adopt-other", "worker-adopt-other", "http://other")
            node_id = f"earnapp-runtime-adopt-{conflict_kind}"
            identity = "sdk-mac-" + "e" * 32
            assigned = await database.assign_earnapp_account(node_id, platform="macos")
            assert int(assigned["id"]) == account_id
            await database.bind_earnapp_node_runtime(node_id, worker_id, device_id=identity, proxy_id=database_proxy)
            await database.save_provider_instance(
                "earnapp", node_id, worker_id=worker_id, mode="proxy", proxy_id=database_proxy, status="running"
            )
            if conflict_kind == "legacy":
                await db.execute(
                    "INSERT INTO proxy_assignments (worker_id, proxy_id, mode, fallback) VALUES (?, ?, 'proxy', 'hold')",
                    (other_worker, conflict_proxy),
                )
            elif conflict_kind == "control":
                await db.execute(
                    """
                    INSERT INTO earnapp_account_control_routes (account_id, proxy_id, state, assigned_logical_node_id)
                    VALUES (?, ?, 'ACTIVE', '')
                    """,
                    (control_account_id, conflict_proxy),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO earnapp_proxy_reservations
                        (logical_node_id, worker_id, generation, expected_proxy_id, proxy_id,
                         binding_version, expires_at)
                    VALUES (?, ?, 99, ?, ?, ?, datetime('now', '+1 hour'))
                    """,
                    (node_id, other_worker, database_proxy, conflict_proxy, f"conflict_{conflict_kind}"),
                )
            await db.commit()

            adopted = await database.adopt_earnapp_runtime_proxy(
                node_id,
                worker_id,
                expected_generation=1,
                device_id=identity,
                expected_database_proxy_id=database_proxy,
                runtime_proxy_id=runtime_proxy,
                expected_runtime_egress_ip="198.51.100.75",
                observed_runtime_egress_ip="198.51.100.75",
                container_id="live-container",
                sidecar_id="live-sidecar",
            )
            assert adopted is None
            assert (await database.get_earnapp_logical_node(node_id))["current_proxy_id"] == database_proxy

    asyncio.run(run())


def test_adopt_earnapp_runtime_proxy_preserves_dashboard_mask_as_unhealthy(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "masked.db"):
            await database.init_db()
            await earnapp_accounts.import_account(_account())
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            database_proxy = await _proxy(provider_id, 65)
            runtime_proxy = await _proxy(provider_id, 66)
            worker_id = await database.upsert_worker("worker-masked", "worker-masked", "http://worker")
            node_id = "earnapp-runtime-adopt-masked"
            identity = "sdk-mac-" + "9" * 32
            await database.assign_earnapp_account(node_id, platform="macos")
            await database.bind_earnapp_node_runtime(node_id, worker_id, device_id=identity, proxy_id=database_proxy)
            await database.save_provider_instance(
                "earnapp", node_id, worker_id=worker_id, mode="proxy", proxy_id=database_proxy, status="running"
            )
            assert await database.mask_proxy_for_provider(runtime_proxy, "earnapp", "dashboard_ip_block")
            await database.save_proxy_probe_result(
                runtime_proxy,
                profile="earnapp_wss",
                probe_status="alive",
                verdict="BLACKLIST",
                eligibility="blocked",
                reason="earnapp_blacklist",
                exit_ip="198.51.100.66",
                latency_ms=10,
                probe_version="test",
            )

            adopted = await database.adopt_earnapp_runtime_proxy(
                node_id,
                worker_id,
                expected_generation=1,
                device_id=identity,
                expected_database_proxy_id=database_proxy,
                runtime_proxy_id=runtime_proxy,
                expected_runtime_egress_ip="198.51.100.66",
                observed_runtime_egress_ip="198.51.100.66",
                container_id="live-container",
                sidecar_id="live-sidecar",
            )

            assert adopted and adopted["current_proxy_id"] == runtime_proxy
            node = await database.get_earnapp_logical_node(node_id)
            assert node["proxy_health"] == "unhealthy"
            assert node["proxy_health_reason"] == "dashboard_ip_block"

    asyncio.run(run())


@pytest.mark.parametrize(
    ("mask_reason", "probe_status", "verdict", "eligibility", "reason", "probe_exit_ip"),
    [
        (None, "alive", "BLACKLIST", "blocked", "earnapp_blacklist", "198.51.100.68"),
        ("proxy_dead", "alive", "BLACKLIST", "blocked", "earnapp_blacklist", "198.51.100.68"),
        ("dashboard_ip_block", "dead", "BLACKLIST", "blocked", "earnapp_blacklist", "198.51.100.68"),
        ("dashboard_ip_block", "alive", "QUALITY_REJECTED", "blocked", "residential_required", "198.51.100.68"),
        ("dashboard_ip_block", "alive", "BLACKLIST", "blocked", "earnapp_blacklist", "203.0.113.68"),
    ],
)
def test_adopt_earnapp_runtime_proxy_rejects_blacklist_without_exact_dashboard_evidence(
    tmp_path,
    mask_reason,
    probe_status,
    verdict,
    eligibility,
    reason,
    probe_exit_ip,
):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "blocked.db"):
            await database.init_db()
            await earnapp_accounts.import_account(_account())
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            database_proxy = await _proxy(provider_id, 67)
            runtime_proxy = await _proxy(provider_id, 68)
            worker_id = await database.upsert_worker("worker-blocked", "worker-blocked", "http://worker")
            node_id = "earnapp-runtime-adopt-blocked"
            identity = "sdk-mac-" + "a" * 32
            await database.assign_earnapp_account(node_id, platform="macos")
            await database.bind_earnapp_node_runtime(node_id, worker_id, device_id=identity, proxy_id=database_proxy)
            await database.save_provider_instance(
                "earnapp", node_id, worker_id=worker_id, mode="proxy", proxy_id=database_proxy, status="running"
            )
            if mask_reason:
                assert await database.mask_proxy_for_provider(runtime_proxy, "earnapp", mask_reason)
            await database.save_proxy_probe_result(
                runtime_proxy,
                profile="earnapp_wss",
                probe_status=probe_status,
                verdict=verdict,
                eligibility=eligibility,
                reason=reason,
                exit_ip=probe_exit_ip,
                latency_ms=10,
                probe_version="test",
            )

            adopted = await database.adopt_earnapp_runtime_proxy(
                node_id,
                worker_id,
                expected_generation=1,
                device_id=identity,
                expected_database_proxy_id=database_proxy,
                runtime_proxy_id=runtime_proxy,
                expected_runtime_egress_ip="198.51.100.68",
                observed_runtime_egress_ip="198.51.100.68",
                container_id="live-container",
                sidecar_id="live-sidecar",
            )

            assert adopted is None
            assert (await database.get_earnapp_logical_node(node_id))["current_proxy_id"] == database_proxy

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
    # Exercise the transaction mechanics independently of the current
    # compliance policy, which blocks this background mutation in production.
    monkeypatch.setattr(main.provider_runtime, "mutation_block", lambda *_args, **_kwargs: None)
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
    monkeypatch.setattr(main.provider_runtime, "mutation_block", lambda *_args, **_kwargs: None)
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
    monkeypatch.setattr(main.provider_runtime, "mutation_block", lambda *_args, **_kwargs: None)
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


@pytest.mark.asyncio
async def test_pending_rotation_reconciliation_uses_persisted_backend_when_heartbeat_omits_it(monkeypatch):
    node_id = "earnapp-ubuntu-reconcile-backend"
    device_id = "sdk-node-" + "f" * 32
    instance = {
        "logical_node_id": node_id,
        "generation": 8,
        "device_id": device_id,
        "proxy_id": 51,
        "pending_binding_version": "rotation_pending_888888",
        "pending_proxy_id": 52,
        "pending_expected_egress_ip": "198.51.100.52",
        "pending_observed_egress_ip": "198.51.100.52",
        # A legacy/just-restarted worker may omit the backend field.
    }
    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(
            return_value={
                "logical_node_id": node_id,
                "assigned_worker_id": 11,
                "generation": 8,
                "device_id": device_id,
                "current_proxy_id": 52,
                "preferred_proxy_id": 51,
                "expected_egress_ip": "198.51.100.52",
                "state": "ACTIVE",
                "platform": "ubuntu",
            }
        ),
    )
    monkeypatch.setattr(
        database,
        "get_provider_instance",
        AsyncMock(return_value={"instance_id": node_id, "runtime_backend": ""}),
    )
    monkeypatch.setattr(database, "get_provider_instance_spec", AsyncMock(return_value={"runtime_backend": "docker"}))

    def mutation_block(_node_id, spec):
        return object() if spec.get("runtime_backend") == "lxd" else None

    monkeypatch.setattr(main.provider_runtime, "mutation_block", mutation_block)
    finalize = AsyncMock(
        return_value={
            "ok": True,
            "binding_version": "rotation_pending_888888",
            "action": "confirmed",
            "proxy_id": 52,
        }
    )
    monkeypatch.setattr(main, "_proxy_to_worker", finalize)

    assert await main._reconcile_earnapp_pending_proxy_binding(instance, 11)
    assert finalize.await_args.kwargs["json"]["commit"] is True


def test_server_heartbeat_keeps_pending_binding_inspection_only_when_runtime_disabled():
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
        assert len(spawned) == 1
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


def test_server_heartbeat_records_scoped_health_without_rotating_when_runtime_disabled():
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
        rotate.assert_not_awaited()

    asyncio.run(run())


def test_server_heartbeat_protects_every_listed_earnapp_node_from_rotation(monkeypatch):
    protected_nodes = {
        "earnapp-canary-test-sing-1",
        "earnapp-ubuntu-canary-test-sing-4",
        "earnapp-ubuntu-canary-test-sing-5",
    }
    monkeypatch.setattr(main.earnapp_policy, "PROTECTED_LOGICAL_NODE_IDS", frozenset(protected_nodes))

    async def run():
        instances = []
        authoritative = []
        for index, node_id in enumerate(sorted(protected_nodes), start=1):
            device_id = "sdk-node-" + str(index) * 32
            proxy_id = 13700 + index
            instances.append(
                {
                    "logical_node_id": node_id,
                    "generation": 1,
                    "device_id": device_id,
                    "proxy_id": proxy_id,
                    "platform": "ubuntu" if "ubuntu" in node_id else "macos",
                    "runtime_backend": "lxd" if "ubuntu" in node_id else "docker",
                    "expected_egress_ip": f"198.51.100.{index}",
                    "proxy_health": "unhealthy",
                    "proxy_health_reason": "proxy_probe_failed",
                }
            )
            authoritative.append(
                {
                    "logical_node_id": node_id,
                    "assigned_worker_id": 11,
                    "generation": 1,
                    "device_id": device_id,
                    "platform": instances[-1]["platform"],
                    "current_proxy_id": proxy_id,
                    "expected_egress_ip": f"198.51.100.{index}",
                    "state": "ACTIVE",
                }
            )

        body = main.WorkerHeartbeat(
            name="worker-a",
            client_id="worker-a",
            provider_states={"earnapp": {"instances": instances}},
        )

        spawned = []

        def capture(coro):
            # This protected-node test only asserts that no mutation task is
            # scheduled; close the fire-and-forget coroutine to avoid leaking
            # an unawaited AsyncMock coroutine during teardown.
            spawned.append(coro)
            coro.close()

        with (
            patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
            patch.object(database, "upsert_worker", AsyncMock(return_value=11)),
            patch.object(main.earnapp_recovery, "heartbeat_node", AsyncMock(return_value=True)),
            patch.object(database, "get_earnapp_logical_node", AsyncMock(side_effect=authoritative)),
            patch.object(database, "record_earnapp_proxy_health", AsyncMock(return_value=True)) as record,
            patch.object(main, "_rotate_unhealthy_earnapp_node", AsyncMock()) as rotate,
            patch.object(database, "confirm_worker_key", AsyncMock()),
            patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
            patch.object(main, "_maybe_auto_deploy_after_heartbeat", AsyncMock(return_value=None)),
            patch.object(main, "_spawn", side_effect=capture),
            patch.object(main.metrics, "record_heartbeat"),
        ):
            await main.api_worker_heartbeat(type("Request", (), {"headers": {"authorization": "Bearer key"}})(), body)

        assert record.await_count == len(protected_nodes)
        rotate.assert_not_awaited()

    asyncio.run(run())


def test_server_heartbeat_rotates_only_after_consecutive_unhealthy_reports(monkeypatch):
    monkeypatch.setattr(main.earnapp_policy, "PROTECTED_LOGICAL_NODE_IDS", frozenset())
    main._EARNAPP_UNHEALTHY_STREAKS.clear()

    async def run():
        node_id = "earnapp-ubuntu-rotation-debounce"
        device_id = "sdk-node-" + "d" * 32
        proxy_id = 13746
        body = main.WorkerHeartbeat(
            name="worker-a",
            client_id="worker-a",
            provider_states={
                "earnapp": {
                    "instances": [
                        {
                            "logical_node_id": node_id,
                            "generation": 1,
                            "device_id": device_id,
                            "proxy_id": proxy_id,
                            "platform": "ubuntu",
                            "runtime_backend": "docker",
                            "expected_egress_ip": "64.52.28.108",
                            "proxy_health": "unhealthy",
                            "proxy_health_reason": "proxy_probe_failed",
                        }
                    ]
                }
            },
        )
        authoritative = {
            "logical_node_id": node_id,
            "assigned_worker_id": 11,
            "generation": 1,
            "device_id": device_id,
            "platform": "ubuntu",
            "current_proxy_id": proxy_id,
            "expected_egress_ip": "64.52.28.108",
            "state": "ACTIVE",
        }
        spawned = []

        def capture(coro):
            spawned.append(coro)

        with (
            patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
            patch.object(database, "upsert_worker", AsyncMock(return_value=11)),
            patch.object(main.earnapp_recovery, "heartbeat_node", AsyncMock(return_value=True)),
            patch.object(database, "get_earnapp_logical_node", AsyncMock(return_value=authoritative)),
            patch.object(database, "record_earnapp_proxy_health", AsyncMock(return_value=True)),
            patch.object(main, "_rotate_unhealthy_earnapp_node", AsyncMock(return_value=True)) as rotate,
            patch.object(database, "confirm_worker_key", AsyncMock()),
            patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
            patch.object(main, "_maybe_auto_deploy_after_heartbeat", AsyncMock(return_value=None)),
            patch.object(main, "_spawn", side_effect=capture) as spawn,
            patch.object(main.metrics, "record_heartbeat"),
        ):
            request = type("Request", (), {"headers": {"authorization": "Bearer key"}})()
            await main.api_worker_heartbeat(request, body)
            await main.api_worker_heartbeat(request, body)
            assert rotate.await_count == 0

            await main.api_worker_heartbeat(request, body)
            await asyncio.gather(*spawned)

        assert spawn.call_count >= 3
        rotate.assert_awaited_once_with(
            node_id,
            11,
            generation=1,
            expected_proxy_id=proxy_id,
        )

    try:
        asyncio.run(run())
    finally:
        main._EARNAPP_UNHEALTHY_STREAKS.clear()


def test_server_heartbeat_healthy_report_resets_unhealthy_rotation_streak(monkeypatch):
    monkeypatch.setattr(main.earnapp_policy, "PROTECTED_LOGICAL_NODE_IDS", frozenset())
    main._EARNAPP_UNHEALTHY_STREAKS.clear()

    async def run():
        node_id = "earnapp-ubuntu-rotation-reset"
        device_id = "sdk-node-" + "e" * 32
        proxy_id = 13751
        instance = {
            "logical_node_id": node_id,
            "generation": 1,
            "device_id": device_id,
            "proxy_id": proxy_id,
            "platform": "ubuntu",
            "runtime_backend": "docker",
            "expected_egress_ip": "130.180.228.4",
            "proxy_health": "unhealthy",
            "proxy_health_reason": "proxy_probe_failed",
        }
        body = main.WorkerHeartbeat(
            name="worker-a",
            client_id="worker-a",
            provider_states={"earnapp": {"instances": [instance]}},
        )
        authoritative = {
            "logical_node_id": node_id,
            "assigned_worker_id": 11,
            "generation": 1,
            "device_id": device_id,
            "platform": "ubuntu",
            "current_proxy_id": proxy_id,
            "expected_egress_ip": "130.180.228.4",
            "state": "ACTIVE",
        }
        spawned = []

        def capture(coro):
            spawned.append(coro)

        with (
            patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
            patch.object(database, "upsert_worker", AsyncMock(return_value=11)),
            patch.object(main.earnapp_recovery, "heartbeat_node", AsyncMock(return_value=True)),
            patch.object(database, "get_earnapp_logical_node", AsyncMock(return_value=authoritative)),
            patch.object(database, "record_earnapp_proxy_health", AsyncMock(return_value=True)),
            patch.object(main, "_rotate_unhealthy_earnapp_node", AsyncMock(return_value=True)) as rotate,
            patch.object(database, "confirm_worker_key", AsyncMock()),
            patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
            patch.object(main, "_maybe_auto_deploy_after_heartbeat", AsyncMock(return_value=None)),
            patch.object(main, "_spawn", side_effect=capture),
            patch.object(main.metrics, "record_heartbeat"),
        ):
            request = type("Request", (), {"headers": {"authorization": "Bearer key"}})()
            await main.api_worker_heartbeat(request, body)
            await main.api_worker_heartbeat(request, body)

            instance["proxy_health"] = "healthy"
            instance["proxy_health_reason"] = ""
            await main.api_worker_heartbeat(request, body)

            instance["proxy_health"] = "unhealthy"
            instance["proxy_health_reason"] = "proxy_probe_failed"
            await main.api_worker_heartbeat(request, body)
            await main.api_worker_heartbeat(request, body)
            assert rotate.await_count == 0

            await main.api_worker_heartbeat(request, body)
            await asyncio.gather(*spawned)

        rotate.assert_awaited_once()

    try:
        asyncio.run(run())
    finally:
        main._EARNAPP_UNHEALTHY_STREAKS.clear()


def test_server_heartbeat_does_not_count_unpersisted_unhealthy_report(monkeypatch):
    monkeypatch.setattr(main.earnapp_policy, "PROTECTED_LOGICAL_NODE_IDS", frozenset())
    main._EARNAPP_UNHEALTHY_STREAKS.clear()

    async def run():
        node_id = "earnapp-ubuntu-unpersisted-health"
        device_id = "sdk-node-" + "f" * 32
        proxy_id = 13761
        body = main.WorkerHeartbeat(
            name="worker-a",
            client_id="worker-a",
            provider_states={
                "earnapp": {
                    "instances": [
                        {
                            "logical_node_id": node_id,
                            "generation": 1,
                            "device_id": device_id,
                            "proxy_id": proxy_id,
                            "platform": "ubuntu",
                            "runtime_backend": "docker",
                            "expected_egress_ip": "203.0.113.61",
                            "proxy_health": "unhealthy",
                            "proxy_health_reason": "proxy_probe_failed",
                        }
                    ]
                }
            },
        )
        authoritative = {
            "logical_node_id": node_id,
            "assigned_worker_id": 11,
            "generation": 1,
            "device_id": device_id,
            "platform": "ubuntu",
            "current_proxy_id": proxy_id,
            "expected_egress_ip": "203.0.113.61",
            "state": "ACTIVE",
        }

        spawned = []

        def capture(coro):
            spawned.append(coro)

        with (
            patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
            patch.object(database, "upsert_worker", AsyncMock(return_value=11)),
            patch.object(main.earnapp_recovery, "heartbeat_node", AsyncMock(return_value=True)),
            patch.object(database, "get_earnapp_logical_node", AsyncMock(return_value=authoritative)),
            patch.object(
                database,
                "record_earnapp_proxy_health",
                AsyncMock(side_effect=[False, True, True, True]),
            ),
            patch.object(main, "_rotate_unhealthy_earnapp_node", AsyncMock(return_value=True)) as rotate,
            patch.object(database, "confirm_worker_key", AsyncMock()),
            patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
            patch.object(main, "_maybe_auto_deploy_after_heartbeat", AsyncMock(return_value=None)),
            patch.object(main, "_spawn", side_effect=capture),
            patch.object(main.metrics, "record_heartbeat"),
        ):
            request = type("Request", (), {"headers": {"authorization": "Bearer key"}})()
            for _ in range(3):
                await main.api_worker_heartbeat(request, body)
            rotate.assert_not_awaited()

            await main.api_worker_heartbeat(request, body)
            await asyncio.gather(*spawned)

        rotate.assert_awaited_once()

    try:
        asyncio.run(run())
    finally:
        main._EARNAPP_UNHEALTHY_STREAKS.clear()


def test_server_heartbeat_discards_stale_streak_when_assignment_changes(monkeypatch):
    monkeypatch.setattr(main.earnapp_policy, "PROTECTED_LOGICAL_NODE_IDS", frozenset())
    main._EARNAPP_UNHEALTHY_STREAKS.clear()

    async def run():
        node_id = "earnapp-ubuntu-new-assignment"
        main._EARNAPP_UNHEALTHY_STREAKS[(node_id, 1, 13762)] = 2
        device_id = "sdk-node-" + "a" * 32
        body = main.WorkerHeartbeat(
            name="worker-a",
            client_id="worker-a",
            provider_states={
                "earnapp": {
                    "instances": [
                        {
                            "logical_node_id": node_id,
                            "generation": 2,
                            "device_id": device_id,
                            "proxy_id": 13763,
                            "platform": "ubuntu",
                            "runtime_backend": "lxd",
                            "expected_egress_ip": "203.0.113.63",
                            "proxy_health": "unhealthy",
                            "proxy_health_reason": "proxy_probe_failed",
                        }
                    ]
                }
            },
        )
        authoritative = {
            "logical_node_id": node_id,
            "assigned_worker_id": 11,
            "generation": 2,
            "device_id": device_id,
            "platform": "ubuntu",
            "current_proxy_id": 13763,
            "expected_egress_ip": "203.0.113.63",
            "state": "ACTIVE",
        }

        def discard(coro):
            coro.close()

        with (
            patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
            patch.object(database, "upsert_worker", AsyncMock(return_value=11)),
            patch.object(main.earnapp_recovery, "heartbeat_node", AsyncMock(return_value=True)),
            patch.object(database, "get_earnapp_logical_node", AsyncMock(return_value=authoritative)),
            patch.object(database, "record_earnapp_proxy_health", AsyncMock(return_value=True)),
            patch.object(main, "_rotate_unhealthy_earnapp_node", AsyncMock(return_value=True)) as rotate,
            patch.object(database, "confirm_worker_key", AsyncMock()),
            patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
            patch.object(main, "_maybe_auto_deploy_after_heartbeat", AsyncMock(return_value=None)),
            patch.object(main, "_spawn", side_effect=discard),
            patch.object(main.metrics, "record_heartbeat"),
        ):
            request = type("Request", (), {"headers": {"authorization": "Bearer key"}})()
            await main.api_worker_heartbeat(request, body)

        assert (node_id, 1, 13762) not in main._EARNAPP_UNHEALTHY_STREAKS
        assert main._EARNAPP_UNHEALTHY_STREAKS[(node_id, 2, 13763)] == 1
        rotate.assert_not_awaited()

    try:
        asyncio.run(run())
    finally:
        main._EARNAPP_UNHEALTHY_STREAKS.clear()


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
            patch.object(
                database, "get_provider_instance", AsyncMock(return_value={"instance_id": "earnapp-ubuntu-legacy"})
            ),
            patch.object(database, "get_provider_instance_spec", AsyncMock(return_value={"runtime_backend": "docker"})),
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
        assert response["earnapp_assignment_acks"][0]["runtime_backend"] == "docker"
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
        assert ack["runtime_backend"] == "docker"
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
    monkeypatch.setattr(main.provider_runtime, "mutation_block", lambda *_args, **_kwargs: None)
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
async def test_dashboard_blocked_rotation_survives_heartbeat_health_race(monkeypatch):
    """An authenticated dashboard block must not be erased by a healthy local probe."""
    monkeypatch.setattr(main.provider_runtime, "mutation_block", lambda *_args, **_kwargs: None)
    node_id = "earnapp-macos-dashboard-blocked-race"
    device_id = "sdk-mac-" + "r" * 32
    candidate = {
        "proxy_id": 23,
        "host": "candidate.example",
        "port": 1080,
        "protocol": "http",
        "exit_ip": "198.51.100.23",
        "country_code": "VN",
        "ip_type": "residential",
    }

    async def worker_call(_worker_id, _method, path, *, json=None, **_kwargs):
        if path.endswith("/proxy/apply"):
            return {
                "ok": True,
                "binding_version": json["binding_version"],
                "proxy_id": candidate["proxy_id"],
                "observed_egress_ip": candidate["exit_ip"],
            }
        return {
            "ok": True,
            "binding_version": json["binding_version"],
            "action": "confirmed",
            "proxy_id": candidate["proxy_id"],
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
                # The worker heartbeat may have overwritten the dashboard
                # failure before the rotation task acquired its lock.
                "proxy_health": "healthy",
                "state": "ACTIVE",
                "device_id": device_id,
                "platform": "macos",
            }
        ),
    )
    monkeypatch.setattr(database, "get_provider_instance", AsyncMock(return_value=None))
    monkeypatch.setattr(database, "find_available_earnapp_proxy_for_node", AsyncMock(return_value=candidate))
    monkeypatch.setattr(database, "reserve_earnapp_proxy_candidate", AsyncMock(return_value=candidate))
    monkeypatch.setattr(database, "release_earnapp_proxy_reservation", AsyncMock(return_value=True))
    monkeypatch.setattr(
        database,
        "commit_earnapp_proxy_rotation",
        AsyncMock(return_value={"logical_node_id": node_id, "current_proxy_id": candidate["proxy_id"]}),
    )
    monkeypatch.setattr(main, "_proxy_to_worker", worker_call)

    assert not await main._rotate_unhealthy_earnapp_node(
        node_id,
        11,
        generation=4,
        expected_proxy_id=11,
    )
    assert await main._rotate_unhealthy_earnapp_node(
        node_id,
        11,
        generation=4,
        expected_proxy_id=11,
        dashboard_blocked=True,
    )


@pytest.mark.asyncio
async def test_unhealthy_ubuntu_rotation_uses_persisted_docker_backend_for_policy(monkeypatch):
    node_id = "earnapp-ubuntu-reference"
    device_id = "sdk-node-" + "e" * 32
    candidate = {
        "proxy_id": 22,
        "host": "candidate.example",
        "port": 1080,
        "protocol": "socks5",
        "exit_ip": "198.51.100.22",
        "country_code": "US",
        "ip_type": "residential",
    }
    policy_specs: list[dict[str, object]] = []

    def mutation_block(_node_id, spec):
        policy_specs.append(dict(spec))
        return None if spec.get("runtime_backend") == "docker" else object()

    async def worker_call(_worker_id, _method, path, *, json=None, **_kwargs):
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

    monkeypatch.setattr(main.provider_runtime, "mutation_block", mutation_block)
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
                "platform": "ubuntu",
            }
        ),
    )
    monkeypatch.setattr(
        database,
        "get_provider_instance",
        AsyncMock(
            return_value={
                "instance_id": node_id,
                "worker_id": 11,
                "mode": "proxy",
                "container_id": "old-main-id",
                "sidecar_id": "",
                "proxy_id": 11,
                "status": "verification_pending",
            }
        ),
    )
    monkeypatch.setattr(database, "get_provider_instance_spec", AsyncMock(return_value={"runtime_backend": "docker"}))
    monkeypatch.setattr(database, "find_available_earnapp_proxy_for_node", AsyncMock(return_value=candidate))
    monkeypatch.setattr(database, "reserve_earnapp_proxy_candidate", AsyncMock(return_value=candidate))
    monkeypatch.setattr(database, "release_earnapp_proxy_reservation", AsyncMock(return_value=True))
    monkeypatch.setattr(database, "commit_earnapp_proxy_rotation", AsyncMock(return_value={"current_proxy_id": 22}))
    monkeypatch.setattr(database, "save_provider_instance", AsyncMock())
    monkeypatch.setattr(main, "_proxy_to_worker", worker_call)

    assert await main._rotate_unhealthy_earnapp_node(node_id, 11, generation=4, expected_proxy_id=11)
    assert policy_specs == [{"provider_slug": "earnapp", "platform": "ubuntu", "runtime_backend": "docker"}]


@pytest.mark.asyncio
async def test_non_ubuntu_rotation_keeps_existing_instance_metadata_when_ack_omits_container(monkeypatch):
    monkeypatch.setattr(main.provider_runtime, "mutation_block", lambda *_args, **_kwargs: None)
    node_id = "earnapp-proxy-w11-ipv4-metadata"
    device_id = "sdk-mac-" + "a" * 32
    candidate = {
        "proxy_id": 22,
        "host": "candidate.example",
        "port": 1080,
        "protocol": "socks5",
        "exit_ip": "198.51.100.22",
        "country_code": "VN",
        "ip_type": "residential",
    }

    async def worker_call(_worker_id, _method, path, *, json=None, **_kwargs):
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
                "platform": "macos",
            }
        ),
    )
    monkeypatch.setattr(
        database,
        "get_provider_instance",
        AsyncMock(
            return_value={
                "instance_id": node_id,
                "worker_id": 11,
                "mode": "proxy",
                "container_id": "old-main-id",
                "sidecar_id": "old-sidecar-id",
                "proxy_id": 11,
                "status": "verification_pending",
            }
        ),
    )
    monkeypatch.setattr(database, "find_available_earnapp_proxy_for_node", AsyncMock(return_value=candidate))
    monkeypatch.setattr(database, "reserve_earnapp_proxy_candidate", AsyncMock(return_value=candidate))
    monkeypatch.setattr(database, "release_earnapp_proxy_reservation", AsyncMock(return_value=True))
    monkeypatch.setattr(database, "commit_earnapp_proxy_rotation", AsyncMock(return_value={"current_proxy_id": 22}))
    save = AsyncMock()
    monkeypatch.setattr(database, "save_provider_instance", save)
    monkeypatch.setattr(main, "_proxy_to_worker", worker_call)

    assert await main._rotate_unhealthy_earnapp_node(node_id, 11, generation=4, expected_proxy_id=11)
    save.assert_awaited_once_with(
        "earnapp",
        node_id,
        worker_id=11,
        mode="proxy",
        container_id="old-main-id",
        sidecar_id="old-sidecar-id",
        proxy_id=22,
        status="verification_pending",
    )


@pytest.mark.asyncio
async def test_unhealthy_node_rotation_rolls_runtime_back_when_database_cas_loses(monkeypatch):
    monkeypatch.setattr(main.provider_runtime, "mutation_block", lambda *_args, **_kwargs: None)
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


@pytest.mark.asyncio
async def test_unhealthy_node_rotation_persists_recreated_container_id(monkeypatch):
    monkeypatch.setattr(main.provider_runtime, "mutation_block", lambda *_args, **_kwargs: None)
    node_id = "earnapp-proxy-w11-ipv4-003"
    device_id = "sdk-mac-" + "c" * 32
    candidate = {
        "proxy_id": 24,
        "host": "candidate.example",
        "port": 8080,
        "protocol": "http",
        "exit_ip": "198.51.100.24",
        "country_code": "VN",
        "ip_type": "residential",
    }

    async def worker_call(_worker_id, _method, path, *, json=None, **_kwargs):
        if path.endswith("/proxy/apply"):
            return {
                "ok": True,
                "binding_version": json["binding_version"],
                "proxy_id": 24,
                "observed_egress_ip": "198.51.100.24",
                "container_id": "new-main-id",
            }
        return {
            "ok": True,
            "binding_version": json["binding_version"],
            "action": "confirmed",
            "proxy_id": 24,
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
                "platform": "macos",
            }
        ),
    )
    monkeypatch.setattr(database, "find_available_earnapp_proxy_for_node", AsyncMock(return_value=candidate))
    monkeypatch.setattr(database, "reserve_earnapp_proxy_candidate", AsyncMock(return_value=candidate))
    monkeypatch.setattr(database, "release_earnapp_proxy_reservation", AsyncMock(return_value=True))
    monkeypatch.setattr(database, "commit_earnapp_proxy_rotation", AsyncMock(return_value={"current_proxy_id": 24}))
    monkeypatch.setattr(
        database,
        "get_provider_instance",
        AsyncMock(
            return_value={
                "instance_id": node_id,
                "slug": "earnapp",
                "worker_id": 11,
                "mode": "proxy",
                "container_id": "old-main-id",
                "sidecar_id": "",
                "proxy_id": 11,
                "status": "verification_pending",
            }
        ),
    )
    save = AsyncMock()
    monkeypatch.setattr(database, "save_provider_instance", save)
    monkeypatch.setattr(main, "_proxy_to_worker", worker_call)

    assert await main._rotate_unhealthy_earnapp_node(node_id, 11, generation=4, expected_proxy_id=11)
    save.assert_awaited_once_with(
        "earnapp",
        node_id,
        worker_id=11,
        mode="proxy",
        container_id="new-main-id",
        sidecar_id="",
        proxy_id=24,
        status="verification_pending",
    )


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
