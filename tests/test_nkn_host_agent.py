from __future__ import annotations

import importlib.util
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import nkn_chaindb

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


def _snapshot() -> dict[str, object]:
    created_at = datetime.now(UTC).replace(microsecond=0)
    digest = "a" * 64
    return {
        "manifest": nkn_chaindb.build_manifest(
            prefix="nkn/chaindb",
            sha256=digest,
            size_bytes=123,
            block_height=1,
            created_at=created_at,
            image="nknorg/nkn:latest",
        ),
        "archive_url": "https://example.invalid/snapshot?X-Amz-Signature=signed-secret",
        "prefix": "nkn/chaindb",
        "max_age_seconds": 48 * 60 * 60,
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
        "--dns",
        "1.1.1.1",
        "--dns",
        "8.8.8.8",
        "-v",
        "/opt/nkn:/nkn/data",
        "nknorg/nkn:latest",
    ]


def test_helper_inner_runtime_does_not_inherit_the_lxd_stub_resolver():
    agent = _module()

    command = agent.inner_docker_run_command()

    dns_values = [command[index + 1] for index, value in enumerate(command) if value == "--dns"]
    assert dns_values == ["1.1.1.1", "8.8.8.8"]


def test_helper_launches_lxd_from_the_canonical_ubuntu_remote(monkeypatch):
    agent = _module()
    controller = agent.Controller()
    payload = agent.validate_deploy("ipv4-001", _payload())
    commands = []

    controller._exists = lambda _name: False
    controller._set_metadata = lambda *_args: None
    controller._wait_ready = lambda *_args: None
    controller._ensure_network = lambda *_args: None
    controller._provision_inner = lambda *_args: "skipped"
    controller.evidence = lambda *_args: {"running": True, "online": False, "runtime_backend": "lxd"}
    monkeypatch.setattr(
        agent,
        "_run",
        lambda args, **kwargs: commands.append(args) or subprocess.CompletedProcess(args, 0, b"", b""),
    )

    controller.deploy(payload)

    launch = next(command for command in commands if command[:2] == ["lxc", "launch"])
    assert launch[2] == "ubuntu:24.04"


def test_helper_allows_only_the_assigned_lxd_instance_through_a_default_drop_forward_chain(monkeypatch):
    agent = _module()
    controller = agent.Controller()
    payload = agent.validate_deploy("ipv4-001", _payload())
    commands = []

    def fake_run(args, **kwargs):
        commands.append((args, kwargs))
        stdout = (
            b"2: eth0    inet 10.20.0.4/24 scope global eth0\n"
            if args[:5] == ["ip", "-4", "address", "show", "dev"]
            else b""
        )
        return subprocess.CompletedProcess(args, 1 if args[:3] == ["iptables", "-C", "FORWARD"] else 0, stdout, b"")

    monkeypatch.setattr(agent, "_run", fake_run)

    controller._ensure_host_routing("cashpilot-nkn-ipv4-001", payload, "10.216.14.252")

    forward_rules = [args for args, _kwargs in commands if args[:3] == ["iptables", "-I", "FORWARD"]]
    assert forward_rules == [
        [
            "iptables",
            "-I",
            "FORWARD",
            "1",
            "-s",
            "10.216.14.252/32",
            "-o",
            "eth0",
            "-m",
            "comment",
            "--comment",
            "cashpilot-nkn-ipv4-001-egress",
            "-j",
            "ACCEPT",
        ],
        [
            "iptables",
            "-I",
            "FORWARD",
            "1",
            "-d",
            "10.216.14.252/32",
            "-i",
            "eth0",
            "-m",
            "conntrack",
            "--ctstate",
            "RELATED,ESTABLISHED",
            "-m",
            "comment",
            "--comment",
            "cashpilot-nkn-ipv4-001-return",
            "-j",
            "ACCEPT",
        ],
    ]


def test_helper_write_inner_file_creates_the_requested_parent_directory(monkeypatch):
    agent = _module()
    controller = agent.Controller()
    commands = []
    monkeypatch.setattr(
        agent,
        "_run",
        lambda args, **kwargs: commands.append((args, kwargs)) or subprocess.CompletedProcess(args, 0, b"", b""),
    )

    controller._write_inner_file(
        "cashpilot-nkn-ipv4-001",
        "/usr/local/sbin/cashpilot-nkn-chaindb-restore",
        b"restore",
        "0755",
    )

    command = commands[0][0]
    assert command[:6] == [
        "lxc",
        "exec",
        "cashpilot-nkn-ipv4-001",
        "--",
        "sh",
        "-lc",
    ]
    assert "install -d -m 0700 /usr/local/sbin" in command[6]


def test_helper_removes_slot_scoped_forward_rules_with_the_lxd_instance(monkeypatch):
    agent = _module()
    controller = agent.Controller()
    commands = []
    monkeypatch.setattr(
        agent,
        "_run",
        lambda args, **kwargs: commands.append((args, kwargs)) or subprocess.CompletedProcess(args, 1, b"", b""),
    )
    config = {
        "config": {
            "user.cashpilot.nkn.slot_id": "ipv4-001",
            "user.cashpilot.nkn.lxd_ip": "10.216.14.252",
            "user.cashpilot.nkn.interface": "eth0",
            "user.cashpilot.nkn.private_ip": "10.20.0.4",
        }
    }

    controller._cleanup_routing(config)

    deleted = [args for args, _kwargs in commands if args[:3] == ["iptables", "-D", "FORWARD"]]
    assert deleted == [
        [
            "iptables",
            "-D",
            "FORWARD",
            "-s",
            "10.216.14.252/32",
            "-o",
            "eth0",
            "-m",
            "comment",
            "--comment",
            "cashpilot-nkn-ipv4-001-egress",
            "-j",
            "ACCEPT",
        ],
        [
            "iptables",
            "-D",
            "FORWARD",
            "-d",
            "10.216.14.252/32",
            "-i",
            "eth0",
            "-m",
            "conntrack",
            "--ctstate",
            "RELATED,ESTABLISHED",
            "-m",
            "comment",
            "--comment",
            "cashpilot-nkn-ipv4-001-return",
            "-j",
            "ACCEPT",
        ],
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


def test_helper_snapshot_contract_accepts_https_and_rejects_plaintext_urls():
    agent = _module()
    payload = _payload()
    payload["chaindb_snapshot"] = {
        "manifest": {"archive_key": "nkn/chaindb/snapshots/1-20260823T120000Z-" + "a" * 64 + ".tar.zst"},
        "archive_url": "https://example.invalid/snapshot",
        "prefix": "nkn/chaindb",
        "max_age_seconds": 48 * 60 * 60,
    }
    validated = agent.validate_deploy("ipv4-001", payload)
    assert validated["chaindb_snapshot"]["archive_url"].startswith("https://")

    payload["chaindb_snapshot"]["archive_url"] = "http://example.invalid/snapshot"
    with pytest.raises(agent.AgentError):
        agent.validate_deploy("ipv4-001", payload)


def test_helper_snapshot_contract_accepts_configured_safe_prefix():
    agent = _module()
    payload = _payload()
    payload["chaindb_snapshot"] = {
        "manifest": {"archive_key": "cashpilot/nkn-db/snapshots/1-20260823T120000Z-" + "a" * 64 + ".tar.zst"},
        "archive_url": "https://example.invalid/snapshot",
        "prefix": "cashpilot/nkn-db",
        "max_age_seconds": 48 * 60 * 60,
    }
    validated = agent.validate_deploy("ipv4-001", payload)
    assert validated["chaindb_snapshot"]["manifest"]["archive_key"].startswith("cashpilot/nkn-db/")


def test_helper_unix_server_handles_heartbeat_while_snapshot_deploy_runs():
    agent = _module()
    if hasattr(agent.socketserver, "UnixStreamServer"):
        assert issubclass(agent._UnixServer, agent.socketserver.ThreadingMixIn)
        assert agent._UnixServer.daemon_threads is True


def test_helper_snapshot_failure_falls_back_to_normal_sync(monkeypatch):
    agent = _module()
    controller = agent.Controller()
    payload = agent.validate_deploy(
        "ipv4-001",
        {
            **_payload(),
            "chaindb_snapshot": {
                "manifest": {"archive_key": "nkn/chaindb/snapshots/1-20260823T120000Z-" + "a" * 64 + ".tar.zst"},
                "archive_url": "https://example.invalid/snapshot",
                "prefix": "nkn/chaindb",
                "max_age_seconds": 48 * 60 * 60,
            },
        },
    )
    controller._install_snapshot = lambda _name, _snapshot: (_ for _ in ()).throw(agent.AgentError("snapshot failed"))
    controller._install_docker = lambda _name: None
    controller._inner_exists = lambda _name: False
    commands = []
    monkeypatch.setattr(
        agent, "_run", lambda args, **kwargs: commands.append(args) or subprocess.CompletedProcess(args, 0, b"", b"")
    )
    result = controller._provision_inner("cashpilot-nkn-ipv4-001", payload)
    assert result == "fallback"
    assert any(command[:3] == ["lxc", "exec", "cashpilot-nkn-ipv4-001"] for command in commands)


def test_helper_snapshot_restore_allows_six_hour_transfer(tmp_path, monkeypatch):
    agent = _module()
    controller = agent.Controller()
    installed_agent = tmp_path / "cashpilot-nkn-agent.py"
    installed_agent.write_bytes(b"agent")
    installed_agent.with_name("nkn_chaindb.py").write_bytes(b"contract")
    installed_agent.with_name("nkn_chaindb_restore.py").write_bytes(b"restore")
    monkeypatch.setattr(agent, "__file__", str(installed_agent))
    snapshot = _snapshot()
    calls = []
    digest = str(snapshot["manifest"]["sha256"])
    monkeypatch.setattr(
        agent,
        "ensure_cached_archive",
        lambda _url, **_kwargs: SimpleNamespace(
            path=Path("/var/lib/cashpilot/nkn-chaindb-cache") / f"{digest}.tar.zst",
            sha256=digest,
            size_bytes=123,
            cache_hit=False,
        ),
    )
    monkeypatch.setattr(controller, "_ensure_snapshot_cache_device", lambda _name: None)
    monkeypatch.setattr(controller, "_write_inner_file", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        agent,
        "_run",
        lambda args, **kwargs: calls.append((args, kwargs)) or subprocess.CompletedProcess(args, 0, b"", b""),
    )

    controller._install_snapshot("cashpilot-nkn-ipv4-001", snapshot)

    restore_calls = [kwargs for args, kwargs in calls if "nkn-chaindb-restore" in " ".join(args)]
    assert restore_calls
    assert restore_calls[0]["timeout"] == 6 * 60 * 60


def test_helper_mounts_the_host_snapshot_cache_read_only(tmp_path, monkeypatch):
    agent = _module()
    controller = agent.Controller()
    monkeypatch.setattr(agent, "NKN_SNAPSHOT_CACHE_ROOT", tmp_path)
    controller._config = lambda _name: {"devices": {}}
    commands = []
    monkeypatch.setattr(
        agent,
        "_run",
        lambda args, **kwargs: commands.append(args) or subprocess.CompletedProcess(args, 0, b"", b""),
    )

    controller._ensure_snapshot_cache_device("cashpilot-nkn-ipv4-001")

    assert commands == [
        [
            "lxc",
            "config",
            "device",
            "add",
            "cashpilot-nkn-ipv4-001",
            "nkn-chaindb-cache",
            "disk",
            f"source={tmp_path}",
            "path=/var/lib/cashpilot/nkn-chaindb-cache",
            "readonly=true",
        ]
    ]


def test_helper_downloads_snapshot_on_the_host_and_sends_only_a_local_cache_path_to_lxd(tmp_path, monkeypatch):
    agent = _module()
    controller = agent.Controller()
    snapshot = _snapshot()
    digest = str(snapshot["manifest"]["sha256"])
    cache_path = tmp_path / f"{digest}.tar.zst"
    cache_path.write_bytes(b"cached")
    installed_agent = tmp_path / "cashpilot-nkn-agent.py"
    installed_agent.write_bytes(b"agent")
    installed_agent.with_name("nkn_chaindb.py").write_bytes(b"contract")
    installed_agent.with_name("nkn_chaindb_restore.py").write_bytes(b"restore")
    monkeypatch.setattr(agent, "__file__", str(installed_agent))
    monkeypatch.setattr(agent, "NKN_SNAPSHOT_CACHE_ROOT", tmp_path)
    cache_calls = []

    def ensure(url, **kwargs):
        cache_calls.append((url, kwargs))
        return SimpleNamespace(path=cache_path, sha256=digest, size_bytes=123, cache_hit=False)

    monkeypatch.setattr(agent, "ensure_cached_archive", ensure)
    devices = []
    monkeypatch.setattr(controller, "_ensure_snapshot_cache_device", lambda name: devices.append(name))
    written = {}
    monkeypatch.setattr(
        controller,
        "_write_inner_file",
        lambda _name, path, payload, _mode: written.__setitem__(path, payload),
    )
    calls = []
    monkeypatch.setattr(
        agent,
        "_run",
        lambda args, **kwargs: calls.append((args, kwargs)) or subprocess.CompletedProcess(args, 0, b"", b""),
    )

    controller._install_snapshot("cashpilot-nkn-ipv4-001", snapshot)

    assert cache_calls == [
        (
            snapshot["archive_url"],
            {
                "expected_sha256": digest,
                "expected_size": 123,
                "cache_root": tmp_path,
            },
        )
    ]
    assert devices == ["cashpilot-nkn-ipv4-001"]
    request = json.loads(written["/run/cashpilot-nkn-chaindb-request.json"])
    assert "archive_url" not in request
    assert request["archive_path"] == f"/var/lib/cashpilot/nkn-chaindb-cache/{digest}.tar.zst"
    assert "signed-secret" not in json.dumps(request)
    assert "signed-secret" not in str(calls)


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
