from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "cashpilot-nkn-agent.py"


def _module():
    spec = importlib.util.spec_from_file_location("cashpilot_nkn_agent", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload() -> dict[str, object]:
    return {
        "slot_id": "ipv4-001",
        "public_ip": "8.8.8.8",
        "private_ip": "10.20.0.4",
        "interface": "eth0",
        "subnet": "10.20.0.0/24",
        "gateway": "10.20.0.1",
        "wallet_id": 7,
        "wallet_assignment_version": 3,
        "lease_client_id": "worker-a:nkn:ipv4-001",
        "wallet_json": json.dumps({"Address": "NKNwalletAddress"}),
        "wallet_pswd": "password-value",
        "beneficiary_address": "NKNBeneficiaryAddress",
        "lxd_cpu": 1,
        "lxd_memory_mib": 1024,
    }


def test_helper_names_only_slot_scoped_nkn_instances():
    agent = _module()
    assert agent.instance_name("ipv4-001") == "cashpilot-nkn-ipv4-001"
    with pytest.raises(agent.AgentError):
        agent.instance_name("../../mysterium")


def test_helper_reads_lxd_config_through_the_supported_query_api(monkeypatch):
    agent = _module()
    controller = agent.Controller()
    calls = []

    def fake_json(args):
        calls.append(args)
        return {"config": {"limits.cpu": "1"}}

    monkeypatch.setattr(agent, "_json_command", fake_json)

    assert controller._config("cashpilot-nkn-ipv4-001") == {"config": {"limits.cpu": "1"}}
    assert calls == [["lxc", "query", "/1.0/instances/cashpilot-nkn-ipv4-001"]]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("lxd_cpu", 0),
        ("lxd_cpu", 65),
        ("lxd_memory_mib", 127),
        ("lxd_memory_mib", 65537),
        ("interface", "eth0;rm"),
        ("private_ip", "not-an-ip"),
        ("wallet_id", 0),
    ],
)
def test_helper_rejects_unsafe_or_out_of_range_deploy_values(field, value):
    agent = _module()
    payload = _payload()
    payload[field] = value
    with pytest.raises(agent.AgentError):
        agent.validate_deploy("ipv4-001", payload)


def test_helper_generates_the_exact_tested_nkn_config():
    agent = _module()
    assert agent.nkn_config("NKNBeneficiaryAddress") == {
        "BeneficiaryAddr": "NKNBeneficiaryAddress",
        "beneficiaryAddr": "NKNBeneficiaryAddress",
        "SyncMode": "light",
        "PasswordFile": "wallet.pswd",
    }


def test_helper_inner_runtime_is_official_docker_with_outer_lxd_limits():
    agent = _module()
    command = agent.inner_docker_run_command("cashpilot-nkn")
    assert command == [
        "docker",
        "run",
        "-d",
        "--name",
        "cashpilot-nkn",
        "--restart",
        "always",
        "--network",
        "host",
        "-v",
        "/opt/nkn:/nkn/data",
        "nknorg/nkn:latest",
    ]


@pytest.mark.parametrize(
    "reference",
    [
        "nknorg/nkn:latest",
        "nknorg/nkn@sha256:" + "a" * 64,
    ],
)
def test_helper_accepts_official_nkn_tag_or_digest_for_canary_adoption(reference):
    agent = _module()
    assert agent.is_official_nkn_image(reference) is True


@pytest.mark.parametrize(
    "reference",
    [
        "nknorg/nkn:v2.2.4",
        "other/nkn:latest",
        "sha256:" + "a" * 64,
    ],
)
def test_helper_rejects_non_authoritative_image_references_for_canary_adoption(reference):
    agent = _module()
    assert agent.is_official_nkn_image(reference) is False


def test_helper_dispatch_exposes_only_nkn_slot_lifecycle():
    agent = _module()

    class Controller:
        def deploy(self, payload):
            return {"action": "deploy", "slot_id": payload["slot_id"]}

        def suspend(self, slot_id, payload):
            return {"action": "suspend", "slot_id": slot_id}

        def resume(self, slot_id, payload):
            return {"action": "resume", "slot_id": slot_id}

        def remove(self, slot_id, payload):
            return {"action": "remove", "slot_id": slot_id}

        def evidence(self, slot_id, payload):
            return {"action": "evidence", "slot_id": slot_id}

    controller = Controller()
    assert agent.dispatch("POST", "/v1/slots/ipv4-001", _payload(), controller)["action"] == "deploy"
    assert agent.dispatch("POST", "/v1/slots/ipv4-001/suspend", _payload(), controller)["action"] == "suspend"
    assert agent.dispatch("POST", "/v1/slots/ipv4-001/resume", _payload(), controller)["action"] == "resume"
    assert agent.dispatch("POST", "/v1/slots/ipv4-001/evidence", _payload(), controller)["action"] == "evidence"
    assert agent.dispatch("DELETE", "/v1/slots/ipv4-001", _payload(), controller)["action"] == "remove"
    with pytest.raises(agent.AgentError):
        agent.dispatch("POST", "/v1/command", {"command": "lxc delete mysterium"}, controller)


def test_assignment_cas_rejects_a_stale_wallet_before_lifecycle_mutation():
    agent = _module()
    config = {
        "user.cashpilot.nkn.wallet_id": "7",
        "user.cashpilot.nkn.wallet_assignment_version": "3",
        "user.cashpilot.nkn.lease_client_id": "worker-a:nkn:ipv4-001",
    }
    payload = _payload()
    payload["wallet_assignment_version"] = 2
    with pytest.raises(agent.AgentError) as exc:
        agent.require_assignment(config, payload)
    assert exc.value.status == 409


def test_helper_accepts_an_existing_canary_only_when_node_identity_matches(monkeypatch):
    agent = _module()
    controller = agent.Controller()
    payload = _payload()
    payload["adopt_instance"] = "cashpilot-nkn-lxd-canary"
    payload["expected_node_id"] = "a" * 64
    controller._adopt_instance = lambda source, target, expected, validated: {
        "source": source,
        "target": target,
        "expected": expected,
        "cpu": validated["lxd_cpu"],
    }
    controller._exists = lambda _name: False

    result = controller.deploy(payload)

    assert result == {
        "source": "cashpilot-nkn-lxd-canary",
        "target": "cashpilot-nkn-ipv4-001",
        "expected": "a" * 64,
        "cpu": 1,
    }


def test_helper_refuses_arbitrary_adopt_instance_names():
    agent = _module()
    payload = _payload()
    payload["adopt_instance"] = "mysterium-direct"
    payload["expected_node_id"] = "a" * 64
    with pytest.raises(agent.AgentError):
        agent.validate_deploy("ipv4-001", payload)


@pytest.mark.parametrize(
    ("adopt_instance", "expected_node_id"),
    [
        ("cashpilot-nkn-lxd-canary", ""),
        ("", "a" * 64),
        ("cashpilot-nkn-lxd-canary", "not-a-node-id"),
    ],
)
def test_helper_requires_a_complete_exact_canary_adoption_guard(adopt_instance, expected_node_id):
    agent = _module()
    payload = _payload()
    payload["adopt_instance"] = adopt_instance
    payload["expected_node_id"] = expected_node_id
    with pytest.raises(agent.AgentError):
        agent.validate_deploy("ipv4-001", payload)


@pytest.mark.parametrize(
    ("config", "observed_node_id"),
    [
        (
            {
                "config": {
                    "limits.cpu": "2",
                    "limits.memory": "1GiB",
                    "limits.memory.enforce": "hard",
                    "limits.memory.swap": "false",
                    "security.nesting": "true",
                    "security.syscalls.intercept.sysinfo": "true",
                }
            },
            "a" * 64,
        ),
        (
            {
                "config": {
                    "limits.cpu": "1",
                    "limits.memory": "2GiB",
                    "limits.memory.enforce": "hard",
                    "limits.memory.swap": "false",
                    "security.nesting": "true",
                    "security.syscalls.intercept.sysinfo": "true",
                }
            },
            "a" * 64,
        ),
        (
            {
                "config": {
                    "limits.cpu": "1",
                    "limits.memory": "1GiB",
                    "limits.memory.enforce": "hard",
                    "limits.memory.swap": "false",
                    "security.nesting": "true",
                    "security.syscalls.intercept.sysinfo": "true",
                }
            },
            "b" * 64,
        ),
        (
            {
                "config": {
                    "limits.cpu": "1",
                    "limits.memory": "1GiB",
                    "limits.memory.enforce": "soft",
                    "limits.memory.swap": "false",
                    "security.nesting": "true",
                    "security.syscalls.intercept.sysinfo": "true",
                }
            },
            "a" * 64,
        ),
    ],
)
def test_helper_checks_limits_and_node_id_before_mutating_a_canary(config, observed_node_id, monkeypatch):
    agent = _module()
    controller = agent.Controller()
    payload = agent.validate_deploy(
        "ipv4-001",
        {
            **_payload(),
            "adopt_instance": "cashpilot-nkn-lxd-canary",
            "expected_node_id": "a" * 64,
        },
    )
    controller._exists = lambda name: name == "cashpilot-nkn-lxd-canary"
    controller._status = lambda _name: "running"
    controller._config = lambda _name: config
    controller._node_state = lambda _name: {"id": observed_node_id, "syncState": "PERSIST_FINISHED"}
    commands = []
    monkeypatch.setattr(agent, "_run", lambda *args, **kwargs: commands.append(args))

    with pytest.raises(agent.AgentError):
        controller._adopt_instance(
            "cashpilot-nkn-lxd-canary",
            "cashpilot-nkn-ipv4-001",
            "a" * 64,
            payload,
        )

    assert commands == []


def test_helper_never_resizes_an_existing_slot_when_settings_change(monkeypatch):
    agent = _module()
    controller = agent.Controller()
    payload = agent.validate_deploy("ipv4-001", _payload())
    controller._exists = lambda _name: True
    controller._config = lambda _name: {
        "config": {
            "limits.cpu": "2",
            "limits.memory": "2GiB",
            "limits.memory.enforce": "hard",
            "limits.memory.swap": "false",
            "security.nesting": "true",
            "security.syscalls.intercept.sysinfo": "true",
            "user.cashpilot.nkn.wallet_id": "7",
            "user.cashpilot.nkn.wallet_assignment_version": "3",
            "user.cashpilot.nkn.lease_client_id": "worker-a:nkn:ipv4-001",
        }
    }
    commands = []
    monkeypatch.setattr(agent, "_run", lambda *args, **kwargs: commands.append(args))

    with pytest.raises(agent.AgentError) as exc:
        controller.deploy(payload)

    assert exc.value.status == 409
    assert commands == []


def test_helper_waits_for_the_same_node_identity_after_restart(monkeypatch):
    agent = _module()
    controller = agent.Controller()
    states = iter([{}, {"id": "a" * 64, "syncState": "PERSIST_FINISHED"}])
    controller._node_state = lambda _name: next(states)
    monkeypatch.setattr(agent.time, "sleep", lambda _seconds: None)

    result = controller._wait_node_identity("cashpilot-nkn-ipv4-001", "a" * 64)

    assert result["syncState"] == "PERSIST_FINISHED"


def test_helper_does_not_claim_rpc_reachable_when_node_state_is_unavailable():
    agent = _module()
    controller = agent.Controller()
    controller._assigned = lambda _slot_id, _payload: ("cashpilot-nkn-ipv4-001", {})
    controller._status = lambda _name: "running"
    controller._node_state = lambda _name: {}

    evidence = controller.evidence("ipv4-001", _payload())

    assert evidence == {"running": True, "online": False, "runtime_backend": "lxd"}


def test_helper_adopts_the_canary_by_rename_without_copying_identity_data(monkeypatch):
    agent = _module()
    controller = agent.Controller()
    source = "cashpilot-nkn-lxd-canary"
    target = "cashpilot-nkn-ipv4-001"
    node_id = "a" * 64
    payload = agent.validate_deploy(
        "ipv4-001",
        {**_payload(), "adopt_instance": source, "expected_node_id": node_id},
    )
    config = {
        "config": {
            "limits.cpu": "1",
            "limits.memory": "1GiB",
            "limits.memory.enforce": "hard",
            "limits.memory.swap": "false",
            "security.nesting": "true",
            "security.syscalls.intercept.mknod": "true",
            "security.syscalls.intercept.setxattr": "true",
            "security.syscalls.intercept.sysinfo": "true",
        }
    }
    controller._exists = lambda name: name == source
    controller._status = lambda _name: "running"
    controller._config = lambda _name: config
    controller._node_state = lambda _name: {"id": node_id, "syncState": "PERSIST_FINISHED"}
    controller._inner_container_names = lambda _name: {"nkn-lxd-canary"}
    controller._verify_adoptable_inner = lambda _name, _inner: None
    controller._wait_ready = lambda _name: None
    controller._wait_node_identity = lambda _name, _expected: {"id": node_id, "syncState": "PERSIST_FINISHED"}
    network_calls = []
    metadata_calls = []
    controller._ensure_network = lambda name, value: network_calls.append((name, value["slot_id"]))
    controller._set_metadata = lambda name, value: metadata_calls.append((name, value["wallet_id"]))
    commands = []

    def fake_run(args, **_kwargs):
        commands.append(args)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(agent, "_run", fake_run)

    result = controller._adopt_instance(source, target, node_id, payload)

    assert result["node_id"] == node_id
    assert result["adopted_from"] == source
    assert ["lxc", "exec", source, "--", "docker", "rename", "nkn-lxd-canary", "cashpilot-nkn"] in commands
    assert ["lxc", "move", source, target] in commands
    assert network_calls == [(target, "ipv4-001")]
    assert metadata_calls == [(target, 7)]
    assert all("wallet.json" not in " ".join(command) for command in commands)


def test_helper_rolls_the_canary_name_back_when_identity_does_not_return(monkeypatch):
    agent = _module()
    controller = agent.Controller()
    source = "cashpilot-nkn-lxd-canary"
    target = "cashpilot-nkn-ipv4-001"
    node_id = "a" * 64
    payload = agent.validate_deploy(
        "ipv4-001",
        {**_payload(), "adopt_instance": source, "expected_node_id": node_id},
    )
    config = {
        "config": {
            "limits.cpu": "1",
            "limits.memory": "1GiB",
            "limits.memory.enforce": "hard",
            "limits.memory.swap": "false",
            "security.nesting": "true",
            "security.syscalls.intercept.mknod": "true",
            "security.syscalls.intercept.setxattr": "true",
            "security.syscalls.intercept.sysinfo": "true",
        }
    }
    exists = {source: True, target: False}
    status = {source: "running", target: "missing"}
    controller._exists = lambda name: exists.get(name, False)
    controller._status = lambda name: status.get(name, "missing")
    controller._config = lambda _name: config
    controller._node_state = lambda _name: {"id": node_id, "syncState": "PERSIST_FINISHED"}
    controller._inner_container_names = lambda _name: {"nkn-lxd-canary"}
    controller._verify_adoptable_inner = lambda _name, _inner: None
    controller._wait_ready = lambda _name: None
    controller._wait_node_identity = lambda _name, _expected: (_ for _ in ()).throw(
        agent.AgentError("identity missing")
    )
    commands = []

    def fake_run(args, **_kwargs):
        commands.append(args)
        if args[:3] == ["lxc", "move", source]:
            exists[source], exists[target] = False, True
            status[source], status[target] = "missing", "stopped"
        elif args[:3] == ["lxc", "move", target]:
            exists[target], exists[source] = False, True
            status[target], status[source] = "missing", "stopped"
        elif args[:2] == ["lxc", "start"]:
            status[args[2]] = "running"
        elif args[:2] == ["lxc", "stop"]:
            status[args[2]] = "stopped"
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(agent, "_run", fake_run)

    with pytest.raises(agent.AgentError, match="identity missing"):
        controller._adopt_instance(source, target, node_id, payload)

    assert exists == {source: True, target: False}
    assert ["lxc", "move", target, source] in commands
    assert ["lxc", "exec", source, "--", "docker", "rename", "cashpilot-nkn", "nkn-lxd-canary"] in commands
