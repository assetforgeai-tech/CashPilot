from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import threading
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from app import earnapp_identity, main, worker_api


@pytest.fixture(autouse=True)
def _enable_historical_runtime_mechanics(monkeypatch):
    """Test LXD/CAS mechanics independently from the production compliance gate."""
    monkeypatch.setattr(worker_api.provider_runtime, "mutation_block", lambda *_args, **_kwargs: None)


def test_worker_composes_mount_the_restricted_earnapp_helper_socket():
    root = Path(__file__).resolve().parents[1]
    for name in ("docker-compose.yml", "docker-compose.fleet.yml", "docker-compose.build.yml"):
        compose = (root / name).read_text(encoding="utf-8")
        assert "/run/cashpilot-earnapp-agent:/run/cashpilot-earnapp-agent" in compose
        assert "/var/snap/lxd/common/lxd/unix.socket" not in compose


def test_earnapp_lxd_settings_are_server_authoritative_and_validated_on_save():
    assert main._earnapp_lxd_settings({}) == {"cpu": 1, "memory_mib": 1024}
    assert main._earnapp_lxd_settings({"earnapp_lxd_cpu": "2", "earnapp_lxd_memory_mib": "2048"}) == {
        "cpu": 2,
        "memory_mib": 2048,
    }
    main._validate_config_update({"earnapp_lxd_cpu": "2", "earnapp_lxd_memory_mib": "2048"})
    with pytest.raises(ValueError, match="earnapp_lxd_cpu"):
        main._validate_config_update({"earnapp_lxd_cpu": "0"})
    with pytest.raises(ValueError, match="earnapp_lxd_memory_mib"):
        main._validate_config_update({"earnapp_lxd_memory_mib": "one-gib"})


def _runtime():
    assert importlib.util.find_spec("app.earnapp_lxd_runtime") is not None, "EarnApp LXD client is missing"
    return importlib.import_module("app.earnapp_lxd_runtime")


def _request(method: str = "POST") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/api/earnapp/nodes/earnapp-ubuntu-1/deploy",
            "headers": [],
        }
    )


def _identity() -> dict[str, object]:
    return earnapp_identity.generate_identity("earnapp-ubuntu-1", "ubuntu")


def _proxy() -> dict[str, object]:
    return {
        "proxy_id": 12,
        "host": "proxy.example",
        "port": 1080,
        "protocol": "socks5",
        "username": "proxy-user",
        "password": "proxy-secret",
        "exit_ip": "203.0.113.10",
        "country_code": "US",
        "ip_type": "residential",
    }


def test_lxd_request_fails_closed_with_clear_error_when_unix_sockets_are_unavailable(monkeypatch):
    runtime = _runtime()
    monkeypatch.delattr(runtime.socket, "AF_UNIX", raising=False)

    with pytest.raises(RuntimeError, match="Unix sockets are unavailable"):
        runtime._request("GET", "/v1/status", timeout=0.01)


def test_lxd_deploy_sends_identity_proxy_and_default_hard_limits_but_returns_no_secrets():
    runtime = _runtime()
    identity = _identity()
    with patch.object(
        runtime,
        "_request",
        return_value={
            "instance_id": "cashpilot-earnapp-earnapp-ubuntu-1",
            "running": True,
            "password": "must-not-escape",
        },
    ) as request:
        result = runtime.deploy_node(
            "earnapp-ubuntu-1",
            generation=3,
            account_id=7,
            device_id=str(identity["device_id"]),
            identity=identity,
            proxy=_proxy(),
        )

    payload = request.call_args.kwargs["payload"]
    assert payload["lxd_cpu"] == 1
    assert payload["lxd_memory_mib"] == 1024
    assert payload["generation"] == 3
    assert payload["identity"]["machine_id"] == identity["machine_id"]
    assert payload["proxy"]["password"] == "proxy-secret"
    assert result == {"instance_id": "cashpilot-earnapp-earnapp-ubuntu-1", "running": True}
    assert "secret" not in json.dumps(result)


def test_lxd_lifecycle_and_evidence_requests_are_generation_and_device_cas_scoped():
    runtime = _runtime()
    device_id = str(_identity()["device_id"])
    with patch.object(
        runtime,
        "_request",
        return_value={
            "running": True,
            "online": False,
            "device_id": device_id,
            "runtime_backend": "lxd",
            "proxy_password": "secret",
        },
    ) as request:
        runtime.suspend_node("earnapp-ubuntu-1", generation=3, device_id=device_id)
        runtime.resume_node("earnapp-ubuntu-1", generation=3, device_id=device_id)
        evidence = runtime.node_evidence("earnapp-ubuntu-1", generation=3, device_id=device_id)
        runtime.remove_node("earnapp-ubuntu-1", generation=3, device_id=device_id)

    assert [call.args[:2] for call in request.call_args_list] == [
        ("POST", "/v1/nodes/earnapp-ubuntu-1/suspend"),
        ("POST", "/v1/nodes/earnapp-ubuntu-1/resume"),
        ("POST", "/v1/nodes/earnapp-ubuntu-1/evidence"),
        ("DELETE", "/v1/nodes/earnapp-ubuntu-1"),
    ]
    assert evidence["device_id"] == device_id
    assert "secret" not in json.dumps(evidence)


def test_lxd_presence_request_is_authoritative_for_runtime_existence():
    runtime = _runtime()
    device_id = str(_identity()["device_id"])
    with patch.object(
        runtime,
        "_request",
        return_value={
            "present": True,
            "instance_id": "cashpilot-earnapp-earnapp-ubuntu-1",
            "runtime_backend": "lxd",
            "device_id": device_id,
        },
    ) as request:
        result = runtime.node_presence("earnapp-ubuntu-1", generation=3, device_id=device_id)

    assert request.call_args.args[:2] == ("POST", "/v1/nodes/earnapp-ubuntu-1/presence")
    assert request.call_args.kwargs["payload"] == {
        "logical_node_id": "earnapp-ubuntu-1",
        "generation": 3,
        "device_id": device_id,
    }
    assert result["present"] is True


def test_worker_lxd_presence_does_not_depend_on_the_worker_state_file(tmp_path, monkeypatch):
    runtime = _runtime()
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = str(_identity()["device_id"])
    spec = worker_api.EarnAppNodeCasSpec(generation=3, device_id=device_id)
    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(
            runtime,
            "node_presence",
            return_value={
                "present": True,
                "instance_id": "cashpilot-earnapp-earnapp-ubuntu-1",
                "runtime_backend": "lxd",
                "device_id": device_id,
            },
        ),
    ):
        result = __import__("asyncio").run(
            worker_api.api_earnapp_lxd_node_presence(_request(), "earnapp-ubuntu-1", spec)
        )

    assert result["present"] is True
    assert not Path(tmp_path, "earnapp-nodes", "earnapp-ubuntu-1.json").exists()


def test_lxd_proxy_binding_requests_are_generation_device_and_proxy_cas_scoped():
    runtime = _runtime()
    device_id = str(_identity()["device_id"])
    with patch.object(
        runtime,
        "_request",
        side_effect=[
            {
                "binding_version": "rotation_12345678",
                "proxy_id": 13,
                "observed_egress_ip": "203.0.113.13",
                "proxy_password": "secret",
            },
            {
                "binding_version": "rotation_12345678",
                "action": "confirmed",
                "proxy_id": 13,
            },
        ],
    ) as request:
        applied = runtime.apply_proxy_binding(
            "earnapp-ubuntu-1",
            generation=3,
            device_id=device_id,
            expected_proxy_id=12,
            binding_version="rotation_12345678",
            proxy={**_proxy(), "proxy_id": 13, "exit_ip": "203.0.113.13"},
        )
        finalized = runtime.finalize_proxy_binding(
            "earnapp-ubuntu-1",
            generation=3,
            device_id=device_id,
            expected_proxy_id=12,
            new_proxy_id=13,
            binding_version="rotation_12345678",
            commit=True,
        )

    assert [call.args[:2] for call in request.call_args_list] == [
        ("POST", "/v1/nodes/earnapp-ubuntu-1/proxy/apply"),
        ("POST", "/v1/nodes/earnapp-ubuntu-1/proxy/finalize"),
    ]
    assert request.call_args_list[0].kwargs["payload"]["expected_proxy_id"] == 12
    assert applied["observed_egress_ip"] == "203.0.113.13"
    assert finalized["action"] == "confirmed"
    assert "secret" not in json.dumps(applied)


def test_worker_node_scoped_proxy_apply_and_finalize_update_only_matching_state(tmp_path, monkeypatch):
    assert hasattr(worker_api, "EarnAppProxyApplySpec")
    assert hasattr(worker_api, "EarnAppProxyFinalizeSpec")
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = str(_identity()["device_id"])
    worker_api._save_earnapp_state(
        "earnapp-ubuntu-1",
        {
            "logical_node_id": "earnapp-ubuntu-1",
            "generation": 3,
            "device_id": device_id,
            "platform": "ubuntu",
            "runtime_backend": "lxd",
            "proxy_id": 12,
            "expected_egress_ip": "203.0.113.10",
        },
    )
    apply_spec = worker_api.EarnAppProxyApplySpec(
        generation=3,
        device_id=device_id,
        expected_proxy_id=12,
        binding_version="rotation_12345678",
        proxy={**_proxy(), "proxy_id": 13, "exit_ip": "203.0.113.13"},
    )
    finalize_spec = worker_api.EarnAppProxyFinalizeSpec(
        generation=3,
        device_id=device_id,
        expected_proxy_id=12,
        new_proxy_id=13,
        binding_version="rotation_12345678",
        expected_egress_ip="203.0.113.13",
        observed_egress_ip="203.0.113.13",
        commit=True,
    )
    runtime = _runtime()
    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(
            runtime,
            "apply_proxy_binding",
            return_value={
                "binding_version": "rotation_12345678",
                "proxy_id": 13,
                "observed_egress_ip": "203.0.113.13",
                "container_id": "recreated-main-id",
            },
        ),
        patch.object(
            runtime,
            "finalize_proxy_binding",
            return_value={
                "binding_version": "rotation_12345678",
                "action": "confirmed",
                "proxy_id": 13,
            },
        ),
        patch.object(
            worker_api,
            "_earnapp_proxy_runtime_snapshot",
            return_value=(
                {"binding_version": "rotation_12345678", "previous_present": False, "candidate_present": False},
                {"running": True, "observed_egress_ip": "203.0.113.13", "probe_ok": True},
            ),
        ),
    ):
        applied = __import__("asyncio").run(
            worker_api.api_apply_earnapp_node_proxy(_request(), "earnapp-ubuntu-1", apply_spec)
        )
        finalized = __import__("asyncio").run(
            worker_api.api_finalize_earnapp_node_proxy(_request(), "earnapp-ubuntu-1", finalize_spec)
        )

    saved = json.loads(Path(tmp_path, "earnapp-nodes", "earnapp-ubuntu-1.json").read_text(encoding="utf-8"))
    assert applied["observed_egress_ip"] == "203.0.113.13"
    assert applied["container_id"] == "recreated-main-id"
    assert finalized["action"] == "confirmed"
    assert saved["proxy_id"] == 13
    assert saved["proxy_health"] == "healthy"
    assert saved["expected_egress_ip"] == "203.0.113.13"


def test_worker_docker_proxy_apply_persists_recreated_main_container_id(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = str(_identity()["device_id"])
    worker_api._save_earnapp_state(
        "earnapp-macos-1",
        {
            "logical_node_id": "earnapp-macos-1",
            "generation": 1,
            "device_id": device_id,
            "platform": "macos",
            "runtime_backend": "docker",
            "proxy_id": 12,
            "expected_egress_ip": "203.0.113.10",
        },
    )
    spec = worker_api.EarnAppProxyApplySpec(
        generation=1,
        device_id=device_id,
        expected_proxy_id=12,
        binding_version="rotation_12345678",
        proxy={**_proxy(), "proxy_id": 13, "exit_ip": "203.0.113.13"},
    )
    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(
            worker_api.orchestrator,
            "apply_proxy_binding_batch",
            return_value={
                "applied_instances": ["earnapp-macos-1"],
                "recreated_main_ids": {"earnapp-macos-1": "docker-recreated-main-id"},
            },
        ),
        patch.object(
            worker_api,
            "_earnapp_proxy_runtime_snapshot",
            return_value=(
                {"binding_version": "rotation_12345678", "previous_present": False, "candidate_present": False},
                {"running": True, "observed_egress_ip": "203.0.113.13", "probe_ok": True},
            ),
        ),
        patch.object(
            worker_api.orchestrator, "probe_service_egress", return_value={"observed_egress_ip": "203.0.113.13"}
        ),
    ):
        result = __import__("asyncio").run(worker_api.api_apply_earnapp_node_proxy(_request(), "earnapp-macos-1", spec))

    saved = json.loads(Path(tmp_path, "earnapp-nodes", "earnapp-macos-1.json").read_text(encoding="utf-8"))
    assert result["container_id"] == "docker-recreated-main-id"
    assert saved["container_id"] == "docker-recreated-main-id"


@pytest.mark.asyncio
async def test_worker_serializes_same_node_proxy_apply_before_runtime_recreate(tmp_path, monkeypatch):
    """Only one request may recreate a logical node's named Docker container at a time."""
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = str(_identity()["device_id"])
    node_id = "earnapp-macos-serialized"
    worker_api._save_earnapp_state(
        node_id,
        {
            "logical_node_id": node_id,
            "generation": 1,
            "device_id": device_id,
            "platform": "macos",
            "runtime_backend": "docker",
            "proxy_id": 12,
            "expected_egress_ip": "203.0.113.10",
        },
    )
    first_apply_started = threading.Event()
    release_first_apply = threading.Event()
    apply_calls = 0

    def apply_binding(*_args, **_kwargs):
        nonlocal apply_calls
        apply_calls += 1
        if apply_calls == 1:
            first_apply_started.set()
            release_first_apply.wait(timeout=5)
        return {
            "applied_instances": [node_id],
            "recreated_main_ids": {node_id: f"docker-recreated-{apply_calls}"},
        }

    def runtime_snapshot(*_args, **_kwargs):
        state = worker_api._earnapp_node_state(node_id)
        return (
            {
                "binding_version": str(state.get("pending_binding_version") or ""),
                "previous_present": False,
                "candidate_present": False,
            },
            {
                "running": True,
                "observed_egress_ip": str(state.get("pending_expected_egress_ip") or "203.0.113.13"),
                "probe_ok": True,
            },
        )

    first_spec = worker_api.EarnAppProxyApplySpec(
        generation=1,
        device_id=device_id,
        expected_proxy_id=12,
        binding_version="rotation_serial_111111",
        proxy={**_proxy(), "proxy_id": 13, "exit_ip": "203.0.113.13"},
    )
    second_spec = worker_api.EarnAppProxyApplySpec(
        generation=1,
        device_id=device_id,
        expected_proxy_id=12,
        binding_version="rotation_serial_222222",
        proxy={**_proxy(), "proxy_id": 14, "exit_ip": "203.0.113.14"},
    )

    worker_api._EARNAPP_NODE_MUTATION_LOCKS.clear()
    try:
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(worker_api.orchestrator, "apply_proxy_binding_batch", side_effect=apply_binding),
            patch.object(
                worker_api.orchestrator, "probe_service_egress", return_value={"observed_egress_ip": "203.0.113.13"}
            ),
            patch.object(worker_api, "_earnapp_proxy_runtime_snapshot", side_effect=runtime_snapshot),
        ):
            first = asyncio.create_task(worker_api.api_apply_earnapp_node_proxy(_request(), node_id, first_spec))
            assert await asyncio.to_thread(first_apply_started.wait, 5)
            second = asyncio.create_task(worker_api.api_apply_earnapp_node_proxy(_request(), node_id, second_spec))
            await asyncio.sleep(0)
            assert apply_calls == 1
            release_first_apply.set()
            assert (await first)["binding_version"] == first_spec.binding_version
            with pytest.raises(HTTPException, match="binding already in progress"):
                await second
    finally:
        worker_api._EARNAPP_NODE_MUTATION_LOCKS.clear()


@pytest.mark.asyncio
async def test_worker_serializes_apply_with_finalize_for_same_node(tmp_path, monkeypatch):
    """A finalize request cannot mutate Docker while its apply is still running."""
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = str(_identity()["device_id"])
    node_id = "earnapp-macos-apply-finalize"
    binding_version = "rotation_serial_333333"
    new_proxy_id = 13
    new_egress_ip = "203.0.113.13"
    worker_api._save_earnapp_state(
        node_id,
        {
            "logical_node_id": node_id,
            "generation": 1,
            "device_id": device_id,
            "platform": "macos",
            "runtime_backend": "docker",
            "proxy_id": 12,
            "expected_egress_ip": "203.0.113.10",
        },
    )
    first_apply_started = threading.Event()
    release_first_apply = threading.Event()
    finalize_calls = 0

    def apply_binding(*_args, **_kwargs):
        first_apply_started.set()
        release_first_apply.wait(timeout=5)
        return {
            "applied_instances": [node_id],
            "recreated_main_ids": {node_id: "docker-recreated-apply-finalize"},
        }

    def finalize_binding(*_args, **_kwargs):
        nonlocal finalize_calls
        finalize_calls += 1
        return {"finalized_instances": [node_id], "action": "confirmed"}

    def runtime_snapshot(*_args, **_kwargs):
        return (
            {
                "binding_version": binding_version,
                "previous_present": False,
                "candidate_present": False,
            },
            {
                "running": True,
                "observed_egress_ip": new_egress_ip,
                "probe_ok": True,
            },
        )

    apply_spec = worker_api.EarnAppProxyApplySpec(
        generation=1,
        device_id=device_id,
        expected_proxy_id=12,
        binding_version=binding_version,
        proxy={**_proxy(), "proxy_id": new_proxy_id, "exit_ip": new_egress_ip},
    )
    finalize_spec = worker_api.EarnAppProxyFinalizeSpec(
        generation=1,
        device_id=device_id,
        expected_proxy_id=12,
        new_proxy_id=new_proxy_id,
        binding_version=binding_version,
        expected_egress_ip=new_egress_ip,
        observed_egress_ip=new_egress_ip,
        commit=True,
    )

    worker_api._EARNAPP_NODE_MUTATION_LOCKS.clear()
    try:
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(worker_api.orchestrator, "apply_proxy_binding_batch", side_effect=apply_binding),
            patch.object(
                worker_api.orchestrator, "probe_service_egress", return_value={"observed_egress_ip": new_egress_ip}
            ),
            patch.object(worker_api.orchestrator, "finalize_proxy_binding_batch", side_effect=finalize_binding),
            patch.object(worker_api, "_earnapp_proxy_runtime_snapshot", side_effect=runtime_snapshot),
        ):
            apply_task = asyncio.create_task(worker_api.api_apply_earnapp_node_proxy(_request(), node_id, apply_spec))
            assert await asyncio.to_thread(first_apply_started.wait, 5)
            finalize_task = asyncio.create_task(
                worker_api.api_finalize_earnapp_node_proxy(_request(), node_id, finalize_spec)
            )
            await asyncio.sleep(0)
            assert finalize_calls == 0
            release_first_apply.set()
            assert (await apply_task)["binding_version"] == binding_version
            assert (await finalize_task)["action"] == "confirmed"
            assert finalize_calls == 1
    finally:
        worker_api._EARNAPP_NODE_MUTATION_LOCKS.clear()


@pytest.mark.asyncio
async def test_worker_runtime_refresh_skips_same_node_proxy_apply(tmp_path, monkeypatch):
    """Heartbeat evidence must not delay or overwrite an in-flight proxy mutation."""
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = str(_identity()["device_id"])
    node_id = "earnapp-macos-refresh-serialized"
    new_egress_ip = "203.0.113.13"
    worker_api._save_earnapp_state(
        node_id,
        {
            "logical_node_id": node_id,
            "generation": 1,
            "device_id": device_id,
            "platform": "macos",
            "runtime_backend": "docker",
            "proxy_id": 12,
            "expected_egress_ip": "203.0.113.10",
        },
    )
    first_apply_started = threading.Event()
    release_first_apply = threading.Event()
    probe_calls = 0

    def apply_binding(*_args, **_kwargs):
        first_apply_started.set()
        release_first_apply.wait(timeout=5)
        return {
            "applied_instances": [node_id],
            "recreated_main_ids": {node_id: "docker-recreated-refresh"},
        }

    def probe(*_args, **_kwargs):
        nonlocal probe_calls
        probe_calls += 1
        return {"running": True, "observed_egress_ip": new_egress_ip, "probe_ok": True}

    apply_spec = worker_api.EarnAppProxyApplySpec(
        generation=1,
        device_id=device_id,
        expected_proxy_id=12,
        binding_version="rotation_serial_444444",
        proxy={**_proxy(), "proxy_id": 13, "exit_ip": new_egress_ip},
    )

    worker_api._EARNAPP_NODE_MUTATION_LOCKS.clear()
    try:
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(worker_api.orchestrator, "apply_proxy_binding_batch", side_effect=apply_binding),
            patch.object(worker_api.orchestrator, "probe_service_egress", side_effect=probe),
        ):
            apply_task = asyncio.create_task(worker_api.api_apply_earnapp_node_proxy(_request(), node_id, apply_spec))
            assert await asyncio.to_thread(first_apply_started.wait, 5)
            refresh_task = asyncio.create_task(worker_api._refresh_earnapp_runtime_evidence())
            await asyncio.sleep(0)
            assert probe_calls == 0
            await asyncio.wait_for(refresh_task, timeout=0.5)
            pending = worker_api._earnapp_node_state(node_id)
            assert pending["pending_binding_version"] == apply_spec.binding_version
            assert pending["pending_proxy_id"] == 13
            assert pending["pending_expected_egress_ip"] == new_egress_ip
            release_first_apply.set()
            assert (await apply_task)["binding_version"] == apply_spec.binding_version

        saved = worker_api._earnapp_node_state(node_id)
        assert saved["pending_binding_version"] == apply_spec.binding_version
        assert saved["pending_proxy_id"] == 13
        assert saved["pending_expected_egress_ip"] == new_egress_ip
        assert saved["pending_observed_egress_ip"] == new_egress_ip
        assert saved["container_id"] == "docker-recreated-refresh"
    finally:
        worker_api._EARNAPP_NODE_MUTATION_LOCKS.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route_name", "spec"),
    [
        (
            "api_apply_earnapp_node_proxy",
            worker_api.EarnAppProxyApplySpec(
                generation=1,
                device_id=str(_identity()["device_id"]),
                expected_proxy_id=12,
                binding_version="rotation_serial_555555",
                proxy={**_proxy(), "proxy_id": 13, "exit_ip": "203.0.113.13"},
            ),
        ),
        (
            "api_finalize_earnapp_node_proxy",
            worker_api.EarnAppProxyFinalizeSpec(
                generation=1,
                device_id=str(_identity()["device_id"]),
                expected_proxy_id=12,
                new_proxy_id=13,
                binding_version="rotation_serial_555555",
                expected_egress_ip="203.0.113.13",
                observed_egress_ip="203.0.113.13",
                commit=True,
            ),
        ),
    ],
)
async def test_worker_rejects_proxy_mutation_before_allocating_node_lock(monkeypatch, route_name, spec):
    node_id = "earnapp-macos-unauthorized"
    worker_api._EARNAPP_NODE_MUTATION_LOCKS.clear()
    monkeypatch.setattr(
        worker_api,
        "_verify_api_key",
        Mock(side_effect=HTTPException(status_code=401, detail="Unauthorized")),
    )

    with pytest.raises(HTTPException) as exc:
        await getattr(worker_api, route_name)(_request(), node_id, spec)

    assert exc.value.status_code == 401
    assert worker_api._EARNAPP_NODE_MUTATION_LOCKS == {}


def test_worker_proxy_finalize_is_idempotent_after_confirm_response_is_lost(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = str(_identity()["device_id"])
    worker_api._save_earnapp_state(
        "earnapp-ubuntu-1",
        {
            "logical_node_id": "earnapp-ubuntu-1",
            "generation": 3,
            "device_id": device_id,
            "platform": "ubuntu",
            "runtime_backend": "lxd",
            "proxy_id": 13,
            "expected_egress_ip": "203.0.113.13",
            "observed_egress_ip": "203.0.113.13",
            "proxy_health": "healthy",
            "last_binding_version": "rotation_12345678",
            "last_binding_generation": 3,
            "last_binding_device_id": device_id,
            "last_binding_expected_proxy_id": 12,
            "last_binding_proxy_id": 13,
        },
    )
    spec = worker_api.EarnAppProxyFinalizeSpec(
        generation=3,
        device_id=device_id,
        expected_proxy_id=12,
        new_proxy_id=13,
        binding_version="rotation_12345678",
        expected_egress_ip="203.0.113.13",
        observed_egress_ip="203.0.113.13",
        commit=True,
    )
    with patch.object(worker_api, "_verify_api_key"):
        result = __import__("asyncio").run(
            worker_api.api_finalize_earnapp_node_proxy(_request(), "earnapp-ubuntu-1", spec)
        )

    assert result["action"] == "confirmed"
    assert result["proxy_id"] == 13
    assert result["idempotent"] is True


def test_worker_proxy_finalize_replay_rejects_arbitrary_binding_version(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = str(_identity()["device_id"])
    worker_api._save_earnapp_state(
        "earnapp-ubuntu-1",
        {
            "logical_node_id": "earnapp-ubuntu-1",
            "generation": 3,
            "device_id": device_id,
            "platform": "ubuntu",
            "runtime_backend": "lxd",
            "proxy_id": 13,
            "expected_egress_ip": "203.0.113.13",
            "observed_egress_ip": "203.0.113.13",
            "last_binding_version": "rotation_12345678",
            "last_binding_generation": 3,
            "last_binding_device_id": device_id,
            "last_binding_expected_proxy_id": 12,
            "last_binding_proxy_id": 13,
        },
    )
    spec = worker_api.EarnAppProxyFinalizeSpec(
        generation=3,
        device_id=device_id,
        expected_proxy_id=12,
        new_proxy_id=13,
        binding_version="attacker_123456",
        expected_egress_ip="203.0.113.13",
        observed_egress_ip="203.0.113.13",
        commit=True,
    )
    with patch.object(worker_api, "_verify_api_key"), pytest.raises(HTTPException) as exc_info:
        __import__("asyncio").run(worker_api.api_finalize_earnapp_node_proxy(_request(), "earnapp-ubuntu-1", spec))
    assert exc_info.value.status_code == 409


def test_worker_proxy_apply_retry_revalidates_runtime_binding_before_idempotent_ack(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = str(_identity()["device_id"])
    worker_api._save_earnapp_state(
        "earnapp-ubuntu-1",
        {
            "logical_node_id": "earnapp-ubuntu-1",
            "generation": 3,
            "device_id": device_id,
            "platform": "ubuntu",
            "runtime_backend": "lxd",
            "proxy_id": 12,
            "expected_egress_ip": "203.0.113.10",
            "pending_binding_version": "rotation_12345678",
            "pending_proxy_id": 13,
            "pending_expected_egress_ip": "203.0.113.13",
            "pending_observed_egress_ip": "203.0.113.13",
        },
    )
    runtime = _runtime()
    spec = worker_api.EarnAppProxyApplySpec(
        generation=3,
        device_id=device_id,
        expected_proxy_id=12,
        binding_version="rotation_12345678",
        proxy={**_proxy(), "proxy_id": 13, "exit_ip": "203.0.113.13"},
    )
    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(
            worker_api,
            "_earnapp_proxy_runtime_snapshot",
            return_value=(
                {"binding_version": "rotation_12345678", "previous_present": True, "candidate_present": False},
                {"running": True, "observed_egress_ip": "203.0.113.13", "probe_ok": True},
            ),
        ) as snapshot,
        patch.object(runtime, "apply_proxy_binding") as apply,
    ):
        result = __import__("asyncio").run(
            worker_api.api_apply_earnapp_node_proxy(_request(), "earnapp-ubuntu-1", spec)
        )

    assert result["idempotent"] is True
    snapshot.assert_called_once_with(
        "earnapp-ubuntu-1",
        {
            "logical_node_id": "earnapp-ubuntu-1",
            "generation": 3,
            "device_id": device_id,
            "platform": "ubuntu",
            "runtime_backend": "lxd",
            "proxy_id": 12,
            "expected_egress_ip": "203.0.113.10",
            "pending_binding_version": "rotation_12345678",
            "pending_proxy_id": 13,
            "pending_expected_egress_ip": "203.0.113.13",
            "pending_observed_egress_ip": "203.0.113.13",
        },
        generation=3,
        device_id=device_id,
    )
    apply.assert_not_called()


def test_worker_proxy_apply_retry_rejects_stale_state_when_runtime_binding_drifted(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = str(_identity()["device_id"])
    worker_api._save_earnapp_state(
        "earnapp-ubuntu-1",
        {
            "logical_node_id": "earnapp-ubuntu-1",
            "generation": 3,
            "device_id": device_id,
            "platform": "ubuntu",
            "runtime_backend": "lxd",
            "proxy_id": 12,
            "expected_egress_ip": "203.0.113.10",
            "pending_binding_version": "rotation_12345678",
            "pending_proxy_id": 13,
            "pending_expected_egress_ip": "203.0.113.13",
            "pending_observed_egress_ip": "203.0.113.13",
        },
    )
    spec = worker_api.EarnAppProxyApplySpec(
        generation=3,
        device_id=device_id,
        expected_proxy_id=12,
        binding_version="rotation_12345678",
        proxy={**_proxy(), "proxy_id": 13, "exit_ip": "203.0.113.13"},
    )
    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(
            worker_api,
            "_earnapp_proxy_runtime_snapshot",
            return_value=(
                {"binding_version": "", "previous_present": False, "candidate_present": False},
                {"running": True, "observed_egress_ip": "203.0.113.13", "probe_ok": True},
            ),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        __import__("asyncio").run(worker_api.api_apply_earnapp_node_proxy(_request(), "earnapp-ubuntu-1", spec))

    assert exc_info.value.status_code == 409


def test_worker_proxy_apply_retry_accepts_runtime_binding_already_committed(tmp_path, monkeypatch):
    """A lost finalize ACK may leave only the active marker on the guest."""
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = str(_identity()["device_id"])
    worker_api._save_earnapp_state(
        "earnapp-ubuntu-1",
        {
            "logical_node_id": "earnapp-ubuntu-1",
            "generation": 3,
            "device_id": device_id,
            "platform": "ubuntu",
            "runtime_backend": "lxd",
            "proxy_id": 12,
            "expected_egress_ip": "203.0.113.10",
            "pending_binding_version": "rotation_12345678",
            "pending_proxy_id": 13,
            "pending_expected_egress_ip": "203.0.113.13",
            "pending_observed_egress_ip": "203.0.113.13",
        },
    )
    spec = worker_api.EarnAppProxyApplySpec(
        generation=3,
        device_id=device_id,
        expected_proxy_id=12,
        binding_version="rotation_12345678",
        proxy={**_proxy(), "proxy_id": 13, "exit_ip": "203.0.113.13"},
    )
    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(
            worker_api,
            "_earnapp_proxy_runtime_snapshot",
            return_value=(
                {"binding_version": "rotation_12345678", "previous_present": False, "candidate_present": False},
                {"running": True, "observed_egress_ip": "203.0.113.13", "probe_ok": True},
            ),
        ),
    ):
        result = __import__("asyncio").run(
            worker_api.api_apply_earnapp_node_proxy(
                Request({"type": "http", "method": "POST", "path": "/", "headers": []}), "earnapp-ubuntu-1", spec
            )
        )

    assert result["idempotent"] is True
    assert result["observed_egress_ip"] == "203.0.113.13"


def test_worker_proxy_finalize_commit_keeps_journal_when_postverify_fails(tmp_path, monkeypatch):
    """A confirmed helper response is not enough without live marker/egress proof."""
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = str(_identity()["device_id"])
    worker_api._save_earnapp_state(
        "earnapp-ubuntu-1",
        {
            "logical_node_id": "earnapp-ubuntu-1",
            "generation": 3,
            "device_id": device_id,
            "platform": "ubuntu",
            "runtime_backend": "lxd",
            "proxy_id": 12,
            "expected_egress_ip": "203.0.113.10",
            "pending_binding_version": "rotation_12345678",
            "pending_proxy_id": 13,
            "pending_expected_egress_ip": "203.0.113.13",
            "pending_observed_egress_ip": "203.0.113.13",
        },
    )
    spec = worker_api.EarnAppProxyFinalizeSpec(
        generation=3,
        device_id=device_id,
        expected_proxy_id=12,
        new_proxy_id=13,
        binding_version="rotation_12345678",
        expected_egress_ip="203.0.113.13",
        observed_egress_ip="203.0.113.13",
        commit=True,
    )
    runtime = _runtime()
    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(
            runtime,
            "finalize_proxy_binding",
            return_value={"binding_version": "rotation_12345678", "action": "confirmed", "proxy_id": 13},
        ),
        patch.object(
            worker_api,
            "_earnapp_proxy_runtime_snapshot",
            return_value=(
                {"binding_version": "rotation_12345678", "previous_present": False, "candidate_present": True},
                {"running": True, "observed_egress_ip": "203.0.113.99", "probe_ok": True},
            ),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        __import__("asyncio").run(
            worker_api.api_finalize_earnapp_node_proxy(
                Request({"type": "http", "method": "POST", "path": "/", "headers": []}),
                "earnapp-ubuntu-1",
                spec,
            )
        )

    assert exc_info.value.status_code == 409
    saved = json.loads(Path(tmp_path, "earnapp-nodes", "earnapp-ubuntu-1.json").read_text(encoding="utf-8"))
    assert saved["pending_binding_version"] == "rotation_12345678"


def test_worker_ubuntu_deploy_model_defaults_to_one_cpu_and_1024_mib():
    assert hasattr(worker_api, "EarnAppLxdDeploySpec")
    identity = _identity()
    spec = worker_api.EarnAppLxdDeploySpec(
        account_id=7,
        generation=3,
        device_id=str(identity["device_id"]),
        identity=identity,
        proxy_id=12,
        proxy=_proxy(),
    )
    assert spec.platform == "ubuntu"
    assert spec.lxd_cpu == 1
    assert spec.lxd_memory_mib == 1024

    with pytest.raises(ValidationError):
        worker_api.EarnAppLxdDeploySpec(
            account_id=7,
            generation=3,
            device_id=str(identity["device_id"]),
            identity=identity,
            proxy_id=12,
            proxy=_proxy(),
            platform="macos",
        )


def test_worker_lxd_deploy_is_retired(tmp_path, monkeypatch):
    assert hasattr(worker_api, "api_deploy_earnapp_lxd_node")
    runtime = _runtime()
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    identity = _identity()
    spec = worker_api.EarnAppLxdDeploySpec(
        account_id=7,
        generation=3,
        device_id=str(identity["device_id"]),
        identity=identity,
        proxy_id=12,
        proxy=_proxy(),
    )
    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(
            runtime,
            "deploy_node",
            return_value={
                "instance_id": "cashpilot-earnapp-earnapp-ubuntu-1",
                "running": True,
                "online": False,
                "runtime_backend": "lxd",
            },
        ),
        pytest.raises(HTTPException) as exc,
    ):
        __import__("asyncio").run(worker_api.api_deploy_earnapp_lxd_node(_request(), "earnapp-ubuntu-1", spec))
    assert exc.value.status_code == 409


def test_worker_proxy_apply_writes_ahead_journal_before_runtime_mutation_and_survives_save_crash(tmp_path, monkeypatch):
    """A worker crash after runtime activation must leave a recoverable intent."""
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = str(_identity()["device_id"])
    worker_api._save_earnapp_state(
        "earnapp-ubuntu-1",
        {
            "logical_node_id": "earnapp-ubuntu-1",
            "generation": 3,
            "device_id": device_id,
            "platform": "ubuntu",
            "runtime_backend": "lxd",
            "proxy_id": 12,
            "expected_egress_ip": "203.0.113.10",
        },
    )
    runtime = _runtime()
    original_save = worker_api._save_earnapp_state
    save_calls = 0

    def crash_on_post_apply_save(logical_node_id, state):
        nonlocal save_calls
        save_calls += 1
        if save_calls == 2:
            raise RuntimeError("simulated worker crash after runtime activation")
        original_save(logical_node_id, state)

    def assert_write_ahead_journal(*_args, **_kwargs):
        journal = json.loads(Path(tmp_path, "earnapp-nodes", "earnapp-ubuntu-1.json").read_text(encoding="utf-8"))
        assert journal["pending_binding_version"] == "rotation_12345678"
        assert journal["pending_proxy_id"] == 13
        assert journal["pending_expected_egress_ip"] == "203.0.113.13"
        assert journal["pending_observed_egress_ip"] == ""
        return {
            "binding_version": "rotation_12345678",
            "proxy_id": 13,
            "observed_egress_ip": "203.0.113.13",
        }

    spec = worker_api.EarnAppProxyApplySpec(
        generation=3,
        device_id=device_id,
        expected_proxy_id=12,
        binding_version="rotation_12345678",
        proxy={**_proxy(), "proxy_id": 13, "exit_ip": "203.0.113.13"},
    )
    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(worker_api, "_save_earnapp_state", side_effect=crash_on_post_apply_save),
        patch.object(runtime, "apply_proxy_binding", side_effect=assert_write_ahead_journal),
        pytest.raises(RuntimeError, match="simulated worker crash"),
    ):
        __import__("asyncio").run(worker_api.api_apply_earnapp_node_proxy(_request(), "earnapp-ubuntu-1", spec))

    saved = json.loads(Path(tmp_path, "earnapp-nodes", "earnapp-ubuntu-1.json").read_text(encoding="utf-8"))
    assert saved["pending_binding_version"] == "rotation_12345678"
    assert saved["pending_proxy_id"] == 13
    assert saved["pending_observed_egress_ip"] == ""


def test_worker_proxy_finalize_discards_unapplied_write_ahead_intent_idempotently(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = str(_identity()["device_id"])
    worker_api._save_earnapp_state(
        "earnapp-ubuntu-1",
        {
            "logical_node_id": "earnapp-ubuntu-1",
            "generation": 3,
            "device_id": device_id,
            "platform": "ubuntu",
            "runtime_backend": "lxd",
            "proxy_id": 12,
            "expected_egress_ip": "203.0.113.10",
            "pending_binding_version": "rotation_12345678",
            "pending_proxy_id": 13,
            "pending_expected_egress_ip": "203.0.113.13",
            "pending_observed_egress_ip": "",
        },
    )
    runtime = _runtime()
    spec = worker_api.EarnAppProxyFinalizeSpec(
        generation=3,
        device_id=device_id,
        expected_proxy_id=12,
        new_proxy_id=13,
        binding_version="rotation_12345678",
        commit=False,
    )
    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(
            worker_api,
            "_earnapp_proxy_runtime_snapshot",
            return_value=(
                {"binding_version": "", "previous_present": False, "candidate_present": False},
                {"running": True, "observed_egress_ip": "203.0.113.10", "probe_ok": True},
            ),
        ),
        patch.object(runtime, "finalize_proxy_binding", side_effect=RuntimeError("binding marker absent")),
        patch.object(
            runtime,
            "discard_proxy_binding",
            create=True,
            return_value={
                "binding_version": "rotation_12345678",
                "action": "rolled_back",
                "proxy_id": 12,
                "idempotent": True,
            },
        ) as discard,
        patch.object(
            runtime,
            "node_evidence",
            return_value={
                "running": True,
                "observed_egress_ip": "203.0.113.10",
                "probe_ok": True,
            },
        ),
    ):
        result = __import__("asyncio").run(
            worker_api.api_finalize_earnapp_node_proxy(_request(), "earnapp-ubuntu-1", spec)
        )

    assert result["action"] == "rolled_back"
    assert result["idempotent"] is True
    discard.assert_called_once_with(
        "earnapp-ubuntu-1",
        generation=3,
        device_id=device_id,
        expected_proxy_id=12,
        binding_version="rotation_12345678",
    )
    saved = json.loads(Path(tmp_path, "earnapp-nodes", "earnapp-ubuntu-1.json").read_text(encoding="utf-8"))
    assert "pending_binding_version" not in saved


def test_worker_proxy_finalize_accepts_clean_rollback_when_egress_probe_is_unavailable(tmp_path, monkeypatch):
    """Clean binding artifacts prove rollback even when the old proxy cannot answer ipify."""
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = "sdk-mac-" + "a" * 32
    worker_api._save_earnapp_state(
        "earnapp-macos-1",
        {
            "logical_node_id": "earnapp-macos-1",
            "generation": 3,
            "device_id": device_id,
            "platform": "macos",
            "runtime_backend": "docker",
            "proxy_id": 12,
            "expected_egress_ip": "203.0.113.10",
            "pending_binding_version": "rotation_12345678",
            "pending_proxy_id": 13,
            "pending_expected_egress_ip": "203.0.113.13",
            "pending_observed_egress_ip": "",
        },
    )
    spec = worker_api.EarnAppProxyFinalizeSpec(
        generation=3,
        device_id=device_id,
        expected_proxy_id=12,
        new_proxy_id=13,
        binding_version="rotation_12345678",
        commit=False,
    )
    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(
            worker_api.orchestrator,
            "finalize_proxy_binding_batch",
            side_effect=RuntimeError("binding marker absent"),
        ),
        patch.object(
            worker_api,
            "_earnapp_proxy_runtime_snapshot",
            return_value=(
                {"binding_version": "", "previous_present": False, "candidate_present": False},
                {"running": True, "observed_egress_ip": "", "probe_ok": False},
            ),
        ),
        patch.object(
            worker_api.orchestrator,
            "discard_proxy_binding",
            return_value={
                "binding_version": "rotation_12345678",
                "action": "rolled_back",
                "idempotent": True,
            },
        ) as discard,
    ):
        result = __import__("asyncio").run(
            worker_api.api_finalize_earnapp_node_proxy(_request(), "earnapp-macos-1", spec)
        )

    assert result["action"] == "rolled_back"
    assert result["idempotent"] is True
    discard.assert_called_once_with("earnapp-macos-1", "rotation_12345678")
    saved = json.loads(Path(tmp_path, "earnapp-nodes", "earnapp-macos-1.json").read_text(encoding="utf-8"))
    assert "pending_binding_version" not in saved


def test_worker_proxy_finalize_keeps_journal_when_inactive_candidate_cannot_be_discarded(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = str(_identity()["device_id"])
    worker_api._save_earnapp_state(
        "earnapp-ubuntu-1",
        {
            "logical_node_id": "earnapp-ubuntu-1",
            "generation": 3,
            "device_id": device_id,
            "platform": "ubuntu",
            "runtime_backend": "lxd",
            "proxy_id": 12,
            "expected_egress_ip": "203.0.113.10",
            "pending_binding_version": "rotation_12345678",
            "pending_proxy_id": 13,
            "pending_expected_egress_ip": "203.0.113.13",
            "pending_observed_egress_ip": "",
        },
    )
    runtime = _runtime()
    spec = worker_api.EarnAppProxyFinalizeSpec(
        generation=3,
        device_id=device_id,
        expected_proxy_id=12,
        new_proxy_id=13,
        binding_version="rotation_12345678",
        commit=False,
    )
    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(
            worker_api,
            "_earnapp_proxy_runtime_snapshot",
            return_value=(
                {"binding_version": "", "previous_present": False, "candidate_present": False},
                {"running": True, "observed_egress_ip": "203.0.113.10", "probe_ok": True},
            ),
        ),
        patch.object(runtime, "finalize_proxy_binding", side_effect=RuntimeError("binding marker absent")),
        patch.object(
            runtime,
            "discard_proxy_binding",
            create=True,
            side_effect=RuntimeError("candidate cleanup ambiguous"),
        ),
        patch.object(
            runtime,
            "node_evidence",
            return_value={
                "running": True,
                "observed_egress_ip": "203.0.113.10",
                "probe_ok": True,
            },
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        __import__("asyncio").run(worker_api.api_finalize_earnapp_node_proxy(_request(), "earnapp-ubuntu-1", spec))

    assert exc_info.value.status_code == 409
    saved = json.loads(Path(tmp_path, "earnapp-nodes", "earnapp-ubuntu-1.json").read_text(encoding="utf-8"))
    assert saved["pending_binding_version"] == "rotation_12345678"


def test_worker_proxy_finalize_verifies_old_egress_before_clearing_rollback_journal(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = str(_identity()["device_id"])
    worker_api._save_earnapp_state(
        "earnapp-ubuntu-1",
        {
            "logical_node_id": "earnapp-ubuntu-1",
            "generation": 3,
            "device_id": device_id,
            "platform": "ubuntu",
            "runtime_backend": "lxd",
            "proxy_id": 12,
            "expected_egress_ip": "203.0.113.10",
            "pending_binding_version": "rotation_12345678",
            "pending_proxy_id": 13,
            "pending_expected_egress_ip": "203.0.113.13",
            "pending_observed_egress_ip": "203.0.113.13",
        },
    )
    runtime = _runtime()
    spec = worker_api.EarnAppProxyFinalizeSpec(
        generation=3,
        device_id=device_id,
        expected_proxy_id=12,
        new_proxy_id=13,
        binding_version="rotation_12345678",
        commit=False,
    )
    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(
            worker_api,
            "_earnapp_proxy_runtime_snapshot",
            return_value=(
                {"binding_version": "", "previous_present": False, "candidate_present": False},
                {"running": True, "observed_egress_ip": "203.0.113.13", "probe_ok": True},
            ),
        ),
        patch.object(
            runtime,
            "finalize_proxy_binding",
            return_value={
                "binding_version": "rotation_12345678",
                "action": "rolled_back",
                "proxy_id": 12,
            },
        ),
        patch.object(
            runtime,
            "node_evidence",
            return_value={
                "running": True,
                "observed_egress_ip": "203.0.113.13",
                "probe_ok": True,
            },
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        __import__("asyncio").run(worker_api.api_finalize_earnapp_node_proxy(_request(), "earnapp-ubuntu-1", spec))

    assert exc_info.value.status_code == 409
    saved = json.loads(Path(tmp_path, "earnapp-nodes", "earnapp-ubuntu-1.json").read_text(encoding="utf-8"))
    assert saved["pending_binding_version"] == "rotation_12345678"


def test_worker_runtime_refresh_preserves_write_ahead_journal_while_candidate_is_observed(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = str(_identity()["device_id"])
    worker_api._save_earnapp_state(
        "earnapp-ubuntu-1",
        {
            "logical_node_id": "earnapp-ubuntu-1",
            "generation": 3,
            "device_id": device_id,
            "platform": "ubuntu",
            "runtime_backend": "lxd",
            "proxy_id": 12,
            "expected_egress_ip": "203.0.113.10",
            "pending_binding_version": "rotation_12345678",
            "pending_proxy_id": 13,
            "pending_expected_egress_ip": "203.0.113.13",
            "pending_observed_egress_ip": "",
        },
    )
    runtime = _runtime()
    with patch.object(
        runtime,
        "node_evidence",
        return_value={
            "running": True,
            "observed_egress_ip": "203.0.113.13",
            "probe_ok": True,
        },
    ):
        __import__("asyncio").run(worker_api._refresh_earnapp_runtime_evidence())

    saved = json.loads(Path(tmp_path, "earnapp-nodes", "earnapp-ubuntu-1.json").read_text(encoding="utf-8"))
    assert saved["pending_observed_egress_ip"] == "203.0.113.13"
    assert saved["proxy_health"] == "unknown"
    assert saved["proxy_health_reason"] == "proxy_binding_pending"


def test_worker_lxd_remove_rejects_stale_generation_without_deleting_state(tmp_path, monkeypatch):
    assert hasattr(worker_api, "EarnAppNodeCasSpec")
    assert hasattr(worker_api, "api_remove_earnapp_lxd_node")
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = str(_identity()["device_id"])
    worker_api._save_earnapp_state(
        "earnapp-ubuntu-1",
        {
            "logical_node_id": "earnapp-ubuntu-1",
            "generation": 3,
            "device_id": device_id,
            "runtime_backend": "lxd",
        },
    )
    spec = worker_api.EarnAppNodeCasSpec(generation=2, device_id=device_id)

    with patch.object(worker_api, "_verify_api_key"), pytest.raises(worker_api.HTTPException) as exc:
        __import__("asyncio").run(worker_api.api_remove_earnapp_lxd_node(_request("DELETE"), "earnapp-ubuntu-1", spec))

    assert exc.value.status_code == 409
    assert Path(tmp_path, "earnapp-nodes", "earnapp-ubuntu-1.json").exists()


def test_worker_lxd_remove_uses_host_cas_when_worker_state_file_is_missing(tmp_path, monkeypatch):
    runtime = _runtime()
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = str(_identity()["device_id"])
    spec = worker_api.EarnAppNodeCasSpec(generation=3, device_id=device_id)
    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(
            runtime,
            "remove_node",
            return_value={
                "instance_id": "cashpilot-earnapp-earnapp-ubuntu-1",
                "running": False,
                "runtime_backend": "lxd",
            },
        ) as remove,
    ):
        result = __import__("asyncio").run(
            worker_api.api_remove_earnapp_lxd_node(_request("DELETE"), "earnapp-ubuntu-1", spec)
        )

    assert result["status"] == "removed"
    remove.assert_called_once_with("earnapp-ubuntu-1", generation=3, device_id=device_id)
    assert not Path(tmp_path, "earnapp-nodes", "earnapp-ubuntu-1.json").exists()


def test_worker_lxd_remove_is_idempotent_after_helper_already_removed_the_guest(tmp_path, monkeypatch):
    runtime = _runtime()
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = str(_identity()["device_id"])
    worker_api._save_earnapp_state(
        "earnapp-ubuntu-1",
        {
            "logical_node_id": "earnapp-ubuntu-1",
            "generation": 3,
            "device_id": device_id,
            "runtime_backend": "lxd",
        },
    )
    spec = worker_api.EarnAppNodeCasSpec(generation=3, device_id=device_id)

    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(
            runtime,
            "remove_node",
            side_effect=runtime.EarnAppLxdHelperError("EarnApp LXD node not found", 404),
        ),
    ):
        result = __import__("asyncio").run(
            worker_api.api_remove_earnapp_lxd_node(_request("DELETE"), "earnapp-ubuntu-1", spec)
        )

    assert result == {
        "status": "removed",
        "logical_node_id": "earnapp-ubuntu-1",
        "idempotent": True,
    }


@pytest.mark.asyncio
async def test_worker_rejects_new_earnapp_lxd_deploy_without_calling_host_helper(monkeypatch):
    deploy = Mock(
        return_value={
            "instance_id": "cashpilot-earnapp-earnapp-ubuntu-policy",
            "running": True,
            "online": False,
            "runtime_backend": "lxd",
        }
    )
    monkeypatch.setattr(worker_api.earnapp_lxd_runtime, "deploy_node", deploy)

    with patch.object(worker_api, "_verify_api_key"):
        identity = earnapp_identity.generate_identity("earnapp-ubuntu-policy-block", "ubuntu")
        identity["device_id"] = "sdk-node-" + "1" * 32
        with pytest.raises(HTTPException) as exc:
            await worker_api.api_deploy_earnapp_lxd_node(
                _request(),
                "earnapp-ubuntu-policy-block",
                worker_api.EarnAppLxdDeploySpec(
                    generation=1,
                    account_id=2,
                    device_id="sdk-node-" + "1" * 32,
                    proxy_id=9,
                    identity=identity,
                    proxy={
                        "proxy_id": 9,
                        "host": "proxy.example",
                        "port": 1080,
                        "protocol": "socks5",
                        "exit_ip": "203.0.113.9",
                        "country_code": "US",
                        "ip_type": "residential",
                    },
                ),
            )
    assert exc.value.status_code == 409
    deploy.assert_not_called()


def test_worker_lxd_remove_never_treats_helper_assignment_conflict_as_absence(tmp_path, monkeypatch):
    runtime = _runtime()
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = str(_identity()["device_id"])
    worker_api._save_earnapp_state(
        "earnapp-ubuntu-1",
        {
            "logical_node_id": "earnapp-ubuntu-1",
            "generation": 3,
            "device_id": device_id,
            "runtime_backend": "lxd",
        },
    )
    spec = worker_api.EarnAppNodeCasSpec(generation=3, device_id=device_id)

    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(
            runtime,
            "remove_node",
            side_effect=runtime.EarnAppLxdHelperError("EarnApp node assignment conflict", 409),
        ),
        pytest.raises(worker_api.HTTPException) as exc_info,
    ):
        __import__("asyncio").run(worker_api.api_remove_earnapp_lxd_node(_request("DELETE"), "earnapp-ubuntu-1", spec))

    assert exc_info.value.status_code == 409
    assert Path(tmp_path, "earnapp-nodes", "earnapp-ubuntu-1.json").exists()


def test_heartbeat_provider_state_never_calls_lxd_helper_synchronously(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = str(_identity()["device_id"])
    worker_api._save_earnapp_state(
        "earnapp-ubuntu-1",
        {
            "logical_node_id": "earnapp-ubuntu-1",
            "generation": 3,
            "device_id": device_id,
            "platform": "ubuntu",
            "runtime_backend": "lxd",
            "runtime_status": "running",
            "evidence": {"running": True, "online": False},
        },
    )

    with patch.object(worker_api.earnapp_lxd_runtime, "node_evidence", side_effect=AssertionError("blocking call")):
        state = worker_api._earnapp_provider_state([])

    assert state is not None
    assert state["instances"][0]["runtime_backend"] == "lxd"


def test_async_lxd_evidence_refresh_persists_redacted_result(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = str(_identity()["device_id"])
    worker_api._save_earnapp_state(
        "earnapp-ubuntu-1",
        {
            "logical_node_id": "earnapp-ubuntu-1",
            "generation": 3,
            "device_id": device_id,
            "platform": "ubuntu",
            "runtime_backend": "lxd",
            "runtime_status": "unknown",
            "evidence": {},
        },
    )

    with patch.object(
        worker_api.earnapp_lxd_runtime,
        "node_evidence",
        return_value={"running": True, "online": True, "device_id": device_id, "proxy_password": "secret"},
    ):
        __import__("asyncio").run(worker_api._refresh_earnapp_lxd_evidence())

    saved = json.loads(Path(tmp_path, "earnapp-nodes", "earnapp-ubuntu-1.json").read_text(encoding="utf-8"))
    assert saved["runtime_status"] == "running"
    assert saved["evidence"]["online"] is True
    assert "secret" not in json.dumps(saved)
