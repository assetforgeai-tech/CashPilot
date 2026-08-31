from __future__ import annotations

import base64
import importlib.util
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "scripts" / "cashpilot-earnapp-agent.py"
INSTALLER = ROOT / "scripts" / "install-earnapp-host-helper.sh"
SERVICE = ROOT / "scripts" / "cashpilot-earnapp-agent.service"
BOOTSTRAP = ROOT / "scripts" / "bootstrap-worker.sh"


def _module():
    assert AGENT.is_file(), "restricted EarnApp host agent is missing"
    spec = importlib.util.spec_from_file_location("cashpilot_earnapp_agent", AGENT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload() -> dict[str, object]:
    return {
        "logical_node_id": "earnapp-ubuntu-1",
        "generation": 3,
        "account_id": 7,
        "device_id": "sdk-node-" + "a" * 32,
        "identity": {
            "platform": "ubuntu",
            "device_id": "sdk-node-" + "a" * 32,
            "machine_id": "b" * 32,
            "hostname": "earnapp-a1b2c3d4e5f6",
            "local_hostname": "earnapp-a1b2c3d4e5f6",
            "os_version": "24.04",
            "arch": "amd64",
        },
        "proxy": {
            "proxy_id": 12,
            "host": "proxy.example",
            "port": 1080,
            "protocol": "socks5",
            "username": "proxy-user",
            "password": "proxy-secret",
            "ip_type": "residential",
        },
        "lxd_cpu": 1,
        "lxd_memory_mib": 1024,
    }


def test_helper_names_only_earnapp_logical_nodes_and_rejects_path_escape():
    agent = _module()
    assert agent.instance_name("earnapp-ubuntu-1") == "cashpilot-earnapp-earnapp-ubuntu-1"
    with pytest.raises(agent.AgentError):
        agent.instance_name("../../mysterium")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("generation", 0),
        ("account_id", 0),
        ("lxd_cpu", 0),
        ("lxd_memory_mib", 127),
        ("device_id", "sdk-mac-wrong"),
    ],
)
def test_helper_rejects_invalid_or_out_of_range_deploy_values(field, value):
    agent = _module()
    payload = _payload()
    payload[field] = value
    with pytest.raises(agent.AgentError):
        agent.validate_deploy("earnapp-ubuntu-1", payload)


def test_helper_requires_a_residential_proxy_and_matching_ubuntu_identity():
    agent = _module()
    payload = _payload()
    payload["proxy"] = {**payload["proxy"], "ip_type": "datacenter"}
    with pytest.raises(agent.AgentError, match="residential"):
        agent.validate_deploy("earnapp-ubuntu-1", payload)

    payload = _payload()
    payload["identity"] = {**payload["identity"], "device_id": "sdk-node-" + "c" * 32}
    with pytest.raises(agent.AgentError, match="identity"):
        agent.validate_deploy("earnapp-ubuntu-1", payload)


def test_helper_launches_ubuntu_with_hard_limits_and_no_nested_docker(monkeypatch):
    agent = _module()
    controller = agent.Controller()
    payload = agent.validate_deploy("earnapp-ubuntu-1", _payload())
    commands = []

    controller._exists = lambda _name: False
    controller._allocate_lxd_ipv4 = lambda _name: "10.252.0.3"
    pinned = []
    controller._pin_instance_ip = lambda name, address: pinned.append((name, address))
    controller._wait_ready = lambda _name: None
    controller._configure_guest = lambda *_args: {
        "installer_sha256": "a" * 64,
        "version": "1.651.510",
    }
    controller._set_metadata = lambda *_args: None
    controller.evidence = lambda *_args: {
        "running": True,
        "online": False,
        "runtime_backend": "lxd",
        "device_id": payload["device_id"],
    }

    def run(args, **kwargs):
        commands.append(args)
        stdout = b"10.252.0.1/24\n" if args[:4] == ["lxc", "network", "get", "lxdbr0"] else b""
        return subprocess.CompletedProcess(args, 0, stdout, b"")

    monkeypatch.setattr(agent, "_run", run)

    controller.deploy(payload)

    init = next(command for command in commands if command[:2] == ["lxc", "init"])
    assert init[2] == "ubuntu:24.04"
    assert init[3] == "cashpilot-earnapp-earnapp-ubuntu-1"
    assert init[4:6] == ["-c", "limits.cpu=1"]
    assert "limits.cpu=1" in init
    assert "limits.memory=1024MiB" in init
    start = ["lxc", "start", "cashpilot-earnapp-earnapp-ubuntu-1"]
    assert start in commands
    network = next(
        command
        for command in commands
        if command[:5] == ["lxc", "config", "set", "cashpilot-earnapp-earnapp-ubuntu-1", "cloud-init.network-config"]
    )
    assert "addresses: [10.252.0.3/24]" in network[-1]
    assert "via: 10.252.0.1" in network[-1]
    assert "addresses: [1.1.1.1, 8.8.8.8]" in network[-1]
    assert commands.index(network) < commands.index(start)
    assert pinned == [("cashpilot-earnapp-earnapp-ubuntu-1", "10.252.0.3")]
    assert not any("docker" in command for command in commands)


def test_helper_holds_the_lxd_allocator_lock_until_the_new_instance_ip_is_pinned(monkeypatch):
    agent = _module()
    controller = agent.Controller()
    payload = agent.validate_deploy("earnapp-ubuntu-1", _payload())

    class AllocationGuard:
        held = False

        def __enter__(self):
            self.held = True

        def __exit__(self, *_args):
            self.held = False

    guard = AllocationGuard()
    controller._exists = lambda _name: False
    controller._allocate_lxd_ipv4 = lambda _name: "10.252.0.3"

    def pin_while_locked(_name, _address):
        assert guard.held is True

    controller._pin_instance_ip = pin_while_locked
    controller._configure_instance_network = pin_while_locked
    controller._wait_ready = lambda _name: None
    controller._configure_guest = lambda *_args: {
        "installer_sha256": "a" * 64,
        "version": "1.651.510",
    }
    controller._set_metadata = lambda *_args: None
    monkeypatch.setattr(agent, "_LXD_ALLOC_LOCK", guard)
    monkeypatch.setattr(
        agent,
        "_run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, b"", b""),
    )

    controller.deploy(payload)


def test_helper_removes_fresh_lxd_instance_when_pinning_the_ip_fails(monkeypatch):
    agent = _module()
    controller = agent.Controller()
    payload = agent.validate_deploy("earnapp-ubuntu-1", _payload())
    commands = []

    controller._exists = lambda _name: False
    controller._allocate_lxd_ipv4 = lambda _name: "10.252.0.3"

    def fail_pin(_name, _address):
        raise agent.AgentError("pin failed", 503)

    controller._pin_instance_ip = fail_pin
    monkeypatch.setattr(
        agent,
        "_run",
        lambda args, **kwargs: commands.append(args) or subprocess.CompletedProcess(args, 0, b"", b""),
    )

    with pytest.raises(agent.AgentError, match="pin failed"):
        controller.deploy(payload)

    cleanup = [args for args in commands if args[:2] == ["lxc", "delete"]]
    assert cleanup == [["lxc", "delete", "cashpilot-earnapp-earnapp-ubuntu-1", "--force"]]


def test_helper_removes_fresh_lxd_instance_when_guest_bootstrap_fails(monkeypatch):
    agent = _module()
    controller = agent.Controller()
    payload = agent.validate_deploy("earnapp-ubuntu-1", _payload())
    commands = []

    controller._exists = lambda _name: False
    controller._allocate_lxd_ipv4 = lambda _name: "10.252.0.3"
    pinned = []
    controller._pin_instance_ip = lambda name, address: pinned.append((name, address))
    controller._configure_instance_network = lambda *_args: None
    controller._wait_ready = lambda _name: None

    def fail_bootstrap(*_args):
        raise agent.AgentError("installer failed", 503)

    controller._configure_guest = fail_bootstrap
    monkeypatch.setattr(
        agent,
        "_run",
        lambda args, **kwargs: commands.append((args, kwargs)) or subprocess.CompletedProcess(args, 0, b"", b""),
    )

    with pytest.raises(agent.AgentError, match="installer failed"):
        controller.deploy(payload)

    cleanup = [args for args, _kwargs in commands if args[:2] == ["lxc", "delete"]]
    assert cleanup == [["lxc", "delete", "cashpilot-earnapp-earnapp-ubuntu-1", "--force"]]


def test_helper_allocates_the_first_free_lxd_ipv4_without_using_gateway_or_existing_leases(monkeypatch):
    agent = _module()
    controller = agent.Controller()

    responses = {
        ("lxc", "network", "get", "lxdbr0", "ipv4.address"): b"10.252.0.1/29\n",
        ("lxc", "network", "list-leases", "lxdbr0", "--format=json"): json.dumps(
            [{"address": "10.252.0.2"}, {"address": "10.252.0.4"}]
        ).encode(),
        ("lxc", "list", "--format=json"): json.dumps(
            [
                {
                    "name": "other-instance",
                    "devices": {"eth0": {"network": "lxdbr0", "ipv4.address": "10.252.0.3"}},
                    "state": {"network": {}},
                }
            ]
        ).encode(),
    }

    def run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, responses[tuple(args)], b"")

    monkeypatch.setattr(agent, "_run", run)

    assert controller._allocate_lxd_ipv4("cashpilot-earnapp-earnapp-ubuntu-1") == "10.252.0.5"


def test_helper_pins_the_inherited_lxd_nic_before_first_boot(monkeypatch):
    agent = _module()
    controller = agent.Controller()
    commands = []

    controller._config = lambda _name: {
        "devices": {},
        "expanded_devices": {"eth0": {"name": "eth0", "network": "lxdbr0", "type": "nic"}},
    }

    def run(args, **kwargs):
        commands.append(args)
        stdout = b"10.252.0.1/24\n" if args[:4] == ["lxc", "network", "get", "lxdbr0"] else b""
        return subprocess.CompletedProcess(args, 0, stdout, b"")

    monkeypatch.setattr(agent, "_run", run)

    controller._pin_instance_ip("cashpilot-earnapp-earnapp-ubuntu-1", "10.252.0.5")

    assert commands == [
        [
            "lxc",
            "config",
            "device",
            "override",
            "cashpilot-earnapp-earnapp-ubuntu-1",
            "eth0",
            "ipv4.address=10.252.0.5",
        ]
    ]


def test_helper_rejects_a_static_guest_address_outside_the_lxd_bridge(monkeypatch):
    agent = _module()
    controller = agent.Controller()
    monkeypatch.setattr(
        agent,
        "_run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, b"10.252.0.1/24\n", b""),
    )

    with pytest.raises(agent.AgentError, match="bridge subnet"):
        controller._configure_instance_network("cashpilot-earnapp-earnapp-ubuntu-1", "10.253.0.3")


def test_helper_proxy_setup_uses_official_installer_and_persists_identity_without_logging_secrets():
    agent = _module()
    script = agent.guest_bootstrap_script(_payload())
    assert "https://brightdata.com/static/earnapp/install.sh" in script
    assert "/etc/machine-id" in script
    assert "/etc/earnapp/uuid" in script
    assert "client.earnapp.com/install_device" in script
    assert 'test "$(cat /etc/earnapp/uuid)" = ' in script
    assert '--data "$(printf \'{"serial":"%s"}\' "$earnapp_serial")"' in script
    assert "cashpilot-earnapp-proxy.service" in script
    assert "redsocks" in script
    assert "proxy-secret" not in script


def test_helper_register_retries_through_guest_relay_until_remote_link_state_is_confirmed():
    agent = _module()
    script = agent.guest_bootstrap_script(_payload())

    assert "register_earnapp_device()" in script
    assert "https://client.earnapp.com/is_linked?uuid=" in script
    assert 'EARNAPP_REGISTER_ATTEMPTS="${EARNAPP_REGISTER_ATTEMPTS:-10}"' in script
    assert 'EARNAPP_REGISTER_RETRY_SECONDS="${EARNAPP_REGISTER_RETRY_SECONDS:-15}"' in script
    assert "&version=${earnapp_version}&appid=node_earnapp.com" in script
    assert 'sleep "$EARNAPP_REGISTER_RETRY_SECONDS"' in script
    assert "systemctl restart earnapp.service" in script
    assert "install_device did not reach linked state" in script
    assert "proxy-secret" not in script


@pytest.mark.parametrize(
    ("install", "linked", "expected_code"),
    [
        ({"ok": 0}, {"linked": True}, 1),
        ({"ok": 1}, {"linked": False}, 1),
        ({"ok": 1}, {"linked": True}, 0),
    ],
)
def test_helper_registration_validator_requires_install_success_and_linked_true(
    tmp_path, install, linked, expected_code
):
    agent = _module()
    script = agent.guest_bootstrap_script(_payload())
    start = script.index("import json\n", script.index("register_earnapp_device()"))
    end = script.index("\nPY\n", start)
    validator = script[start:end]
    install_path = tmp_path / "install.json"
    linked_path = tmp_path / "linked.json"
    install_path.write_text(json.dumps(install), encoding="utf-8")
    linked_path.write_text(json.dumps(linked), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-c", validator, str(install_path), str(linked_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == expected_code
    assert result.stdout == ""
    assert result.stderr == ""


def test_helper_embedded_proxy_script_is_valid_python():
    agent = _module()
    bootstrap = agent.guest_bootstrap_script(_payload())
    start = bootstrap.index("#!/usr/bin/env python3", bootstrap.index("cashpilot-earnapp-proxy <<'PROXY'"))
    end = bootstrap.index("\nPROXY\n", start)

    compile(bootstrap[start:end], "cashpilot-earnapp-proxy", "exec")


def test_helper_reports_the_failing_bootstrap_stage_without_secret_output(monkeypatch):
    agent = _module()
    controller = agent.Controller()
    payload = _payload()
    payload["proxy"] = {**payload["proxy"], "endpoint_ip": "198.51.100.10"}
    controller._write_guest_file = lambda *_args, **_kwargs: None
    commands = []

    def run(args, **kwargs):
        commands.append(args)
        if args[-1] == "/root/cashpilot-earnapp-bootstrap.sh":
            raise agent.AgentError("host command failed: lxc", 503)
        if "bootstrap.stage" in args[-1]:
            return subprocess.CompletedProcess(args, 0, b"proxy_service\n", b"")
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(agent, "_run", run)

    with pytest.raises(agent.AgentError, match="proxy_service"):
        controller._configure_guest("cashpilot-earnapp-earnapp-ubuntu-1", payload)

    assert not any("proxy-secret" in " ".join(command) for command in commands)


def test_helper_bootstrap_installs_transparent_tcp_redirect_and_exempts_proxy_endpoint():
    agent = _module()
    script = agent.guest_bootstrap_script(_payload())
    # redsocks' ``redirector = iptables`` only interprets redirected sockets;
    # the guest must install the OUTPUT redirect itself.
    assert "CASH_PILOT_EARNAPP" in script
    assert "iptables -t nat" in script
    assert "REDIRECT --to-ports 12345" in script
    assert "PROXY_ENDPOINT_IPV4" in script
    assert "-o lo" in script
    assert 'os.path.join(runtime, "redsocks.conf")' in script
    assert "PROXY_USERNAME_B64" in script
    assert "/run/cashpilot-earnapp-redsocks.conf" not in script


def test_helper_disables_the_package_redsocks_service_before_claiming_its_listener():
    agent = _module()
    script = agent.guest_bootstrap_script(_payload())

    package_install = script.index("apt-get install")
    stock_disable = script.index("systemctl disable --now redsocks.service")
    cashpilot_start = script.index("systemctl enable --now cashpilot-earnapp-proxy.service")

    assert package_install < stock_disable < cashpilot_start


def test_helper_waits_for_transparent_proxy_egress_before_downloading_the_installer():
    agent = _module()
    script = agent.guest_bootstrap_script(_payload())

    proxy_start = script.index("systemctl enable --now cashpilot-earnapp-proxy.service")
    ready_stage = script.index("stage proxy_ready")
    egress_probe = script.index("https://api.ipify.org", ready_stage)
    installer_stage = script.index("stage installer_download")

    assert proxy_start < ready_stage < egress_probe < installer_stage
    assert "EarnApp transparent proxy did not become ready" in script


def test_helper_bootstrap_fails_closed_for_udp_ipv6_and_routes_dns_through_proxy():
    agent = _module()
    script = agent.guest_bootstrap_script(_payload())

    assert "CASH_PILOT_EARNAPP_FILTER" in script
    assert "dnstc" in script
    assert "--to-ports 1053" in script
    assert "-p udp -j REJECT" in script
    assert "-p tcp -j REJECT" in script
    assert "ip6tables" in script
    assert "disable_ipv6" in script
    assert "ip6tables -I OUTPUT 1 -j" in script


def test_helper_resolves_proxy_on_host_and_pins_the_guest_endpoint(monkeypatch):
    agent = _module()
    controller = agent.Controller()
    proxy = dict(_payload()["proxy"])
    lookups = []

    def getaddrinfo(host, port, *, family, type):
        lookups.append((host, port, family, type))
        return [
            (family, type, 6, "", ("203.0.113.19", 0)),
            (family, type, 6, "", ("203.0.113.20", 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)

    encoded = controller._proxy_env(proxy).decode("ascii")
    script = agent.guest_bootstrap_script(_payload())

    assert lookups == [("proxy.example", None, socket.AF_INET, socket.SOCK_STREAM)]
    assert "PROXY_ENDPOINT_IPV4=203.0.113.19" in encoded
    assert "PROXY_HOST_B64" not in encoded
    assert "getent" not in script
    assert 'host = quoted(os.environ["PROXY_ENDPOINT_IPV4"])' in script
    assert '-d "$PROXY_ENDPOINT_IPV4" --dport "$PROXY_PORT" -j RETURN' in script


def test_helper_uses_authoritative_endpoint_ip_without_dns(monkeypatch):
    agent = _module()
    proxy = dict(_payload()["proxy"])
    proxy["endpoint_ip"] = "198.51.100.77"
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: pytest.fail("endpoint_ip must bypass host DNS"),
    )

    encoded = agent.Controller._proxy_env(proxy).decode("ascii")

    assert "PROXY_ENDPOINT_IPV4=198.51.100.77" in encoded


def test_proxy_rule_refresh_migrates_legacy_rules_behind_a_temporary_deny_guard():
    agent = _module()
    script = agent.guest_bootstrap_script(_payload())
    marker = "# Install a temporary deny guard"
    assert marker in script
    apply_path = script.split(marker, 1)[1]

    install_temporary = apply_path.index('iptables -I OUTPUT 1 -j "$TEMP_FILTER_CHAIN"')
    detach_legacy = apply_path.index('while iptables -C OUTPUT -j "$FILTER_CHAIN" >/dev/null 2>&1; do')
    flush_legacy = apply_path.index('iptables -F "$FILTER_CHAIN"')
    install_current = apply_path.index('iptables -I OUTPUT 1 -j "$FILTER_CHAIN"')
    remove_temporary = apply_path.index(
        'while iptables -C OUTPUT -j "$TEMP_FILTER_CHAIN" >/dev/null 2>&1; do',
        install_current,
    )

    assert install_temporary < detach_legacy < flush_legacy < install_current < remove_temporary


def test_temporary_firewall_guard_is_not_flushed_after_it_can_be_live():
    agent = _module()
    script = agent.guest_bootstrap_script(_payload())
    apply_path = script.split("# Install a temporary deny guard", 1)[1]
    detach = apply_path.index(
        'while iptables -C OUTPUT -j "$TEMP_FILTER_CHAIN" >/dev/null 2>&1; do',
        apply_path.index('iptables -I OUTPUT 1 -j "$FILTER_CHAIN"'),
    )

    assert 'iptables -I "$TEMP_FILTER_CHAIN" 1 -j DROP' in apply_path
    assert 'iptables -F "$TEMP_FILTER_CHAIN"' not in apply_path[:detach]


def test_proxy_service_keeps_fail_closed_firewall_when_redsocks_stops():
    agent = _module()
    script = agent.guest_bootstrap_script(_payload())

    assert "ExecStopPost=+/usr/local/sbin/cashpilot-earnapp-proxy-rules remove" not in script
    assert "ALLOW_CHAIN=CASH_PILOT_EARNAPP_ALLOW" in script
    assert 'iptables -F "$ALLOW_CHAIN"' in script
    assert 'iptables -F "$FILTER_CHAIN"' in script  # explicit uninstall only
    apply_path = script.split("# Install a temporary deny guard", 1)[1]
    assert 'iptables -I OUTPUT 1 -j "$TEMP_FILTER_CHAIN"' in apply_path
    assert 'iptables -t nat -F "$CHAIN"' in apply_path


def test_proxy_rule_refresh_keeps_a_fail_closed_guard_while_rebuilding_rules():
    agent = _module()
    script = agent.guest_bootstrap_script(_payload())
    apply_path = script.split("# Install a temporary deny guard", 1)[1]

    assert "remove_jumps" not in apply_path
    assert 'iptables -I OUTPUT 1 -j "$TEMP_FILTER_CHAIN"' in apply_path
    assert 'iptables -t nat -I OUTPUT 1 -p tcp -j "$CHAIN"' in apply_path
    assert 'iptables -t nat -I OUTPUT 1 -p udp -j "$CHAIN"' in apply_path
    assert 'iptables -I OUTPUT 1 -j "$FILTER_CHAIN"' in apply_path
    assert 'iptables -A "$ALLOW_CHAIN" -m owner --uid-owner cashpilot-redsocks -j ACCEPT' in apply_path
    assert 'iptables -A "$ALLOW_CHAIN" -p tcp -d "$PROXY_ENDPOINT_IPV4" --dport "$PROXY_PORT" -j ACCEPT' in apply_path
    assert 'iptables -t nat -A "$CHAIN" -p tcp -d "$PROXY_ENDPOINT_IPV4" --dport "$PROXY_PORT" -j RETURN' in apply_path
    assert ('iptables -A "$FILTER_CHAIN" -p udp -j REJECT --reject-with icmp-port-unreachable') in apply_path


@pytest.mark.parametrize(
    "credential",
    [
        "quote\"single'quote",
        r"back\\slash",
        "line-one\nline-two",
        "$dollar`backtick`;semicolon",
    ],
)
def test_proxy_credentials_are_encoded_for_systemd_and_shell_without_losing_bytes(credential, monkeypatch):
    agent = _module()
    proxy = dict(_payload()["proxy"])
    proxy["username"] = credential
    proxy["password"] = credential
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.19", 0))],
    )

    encoded = agent.Controller._proxy_env(proxy).decode("ascii")
    values = dict(line.split("=", 1) for line in encoded.splitlines())

    assert credential not in encoded
    assert base64.b64decode(values["PROXY_USERNAME_B64"]).decode() == credential
    assert base64.b64decode(values["PROXY_PASSWORD_B64"]).decode() == credential
    assert "PROXY_USERNAME=" not in encoded
    assert "PROXY_PASSWORD=" not in encoded


def test_helper_pins_official_installer_before_execution():
    agent = _module()
    script = agent.guest_bootstrap_script(_payload())
    assert len(agent.OFFICIAL_INSTALLER_SHA256) == 64
    assert "sha256sum" in script
    assert "OFFICIAL_INSTALLER_SHA256" in script
    assert "installer checksum" in script.lower()


def test_helper_rejects_existing_instance_with_drifted_lxd_contract():
    agent = _module()
    controller = agent.Controller()
    payload = agent.validate_deploy("earnapp-ubuntu-1", _payload())
    controller._exists = lambda _name: True
    controller._config = lambda _name: {
        "config": {
            "user.cashpilot.provider": "earnapp",
            "user.cashpilot.earnapp.logical_node_id": "earnapp-ubuntu-1",
            "user.cashpilot.earnapp.generation": "3",
            "user.cashpilot.earnapp.device_id": "sdk-node-" + "a" * 32,
            "limits.cpu": "2",
            "limits.memory": "2048MiB",
            "limits.memory.enforce": "hard",
            "limits.memory.swap": "false",
            "boot.autostart": "true",
        }
    }
    with pytest.raises(agent.AgentError, match="LXD runtime contract"):
        controller.deploy(payload)


def test_helper_retries_an_uninitialized_instance_instead_of_treating_it_as_assignment_conflict(monkeypatch):
    agent = _module()
    controller = agent.Controller()
    payload = agent.validate_deploy("earnapp-ubuntu-1", _payload())
    controller._exists = lambda _name: True
    controller._config = lambda _name: {
        "config": {
            "limits.cpu": "1",
            "limits.memory": "1024MiB",
            "limits.memory.enforce": "hard",
            "limits.memory.swap": "false",
            "boot.autostart": "true",
        }
    }
    configured = []
    controller._allocate_lxd_ipv4 = lambda _name: "10.252.0.3"
    controller._pin_instance_ip = lambda *_args: None
    controller._configure_instance_network = lambda *_args: None
    controller._wait_ready = lambda _name: None
    controller._status = lambda _name: "stopped"
    controller._configure_guest = lambda name, body: configured.append((name, body)) or {"version": "1.651.510"}
    controller._set_metadata = lambda *_args: None
    controller._evidence = lambda *_args: {
        "instance_id": "cashpilot-earnapp-earnapp-ubuntu-1",
        "running": True,
        "online": False,
        "runtime_backend": "lxd",
        "device_id": payload["device_id"],
    }
    monkeypatch.setattr(
        agent,
        "_run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, b"", b""),
    )

    result = controller.deploy(payload)

    assert configured == [("cashpilot-earnapp-earnapp-ubuntu-1", payload)]
    assert result["device_id"] == payload["device_id"]


def test_helper_evidence_and_errors_never_return_proxy_credentials(monkeypatch):
    agent = _module()
    controller = agent.Controller()
    payload = agent.validate_deploy("earnapp-ubuntu-1", _payload())
    controller._assigned = lambda *_args: ("cashpilot-earnapp-earnapp-ubuntu-1", payload)
    controller._status = lambda _name: "running"
    monkeypatch.setattr(
        agent,
        "_run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args,
            0,
            json.dumps(
                {
                    "device_id": payload["device_id"],
                    "version": "1.651.510",
                    "earnapp_active": True,
                    "proxy_active": True,
                }
            ).encode(),
            b"",
        ),
    )

    evidence = controller.evidence("earnapp-ubuntu-1", payload)
    assert evidence["running"] is True
    assert evidence["device_id"] == payload["device_id"]
    assert "secret" not in json.dumps(evidence)


def test_helper_presence_checks_lxd_metadata_without_worker_state_file():
    agent = _module()
    controller = agent.Controller()
    payload = _payload()
    controller._exists = lambda name: name == "cashpilot-earnapp-earnapp-ubuntu-1"
    controller._config = lambda _name: {
        "config": {
            "user.cashpilot.provider": "earnapp",
            "user.cashpilot.earnapp.logical_node_id": "earnapp-ubuntu-1",
            "user.cashpilot.earnapp.generation": "3",
            "user.cashpilot.earnapp.device_id": payload["device_id"],
        }
    }

    result = agent.dispatch(
        "POST",
        "/v1/nodes/earnapp-ubuntu-1/presence",
        {"generation": 3, "device_id": payload["device_id"]},
        controller,
    )

    assert result == {
        "present": True,
        "instance_id": "cashpilot-earnapp-earnapp-ubuntu-1",
        "runtime_backend": "lxd",
        "device_id": payload["device_id"],
    }


def test_helper_presence_reports_absence_only_when_the_exact_lxd_instance_is_missing():
    agent = _module()
    controller = agent.Controller()
    controller._exists = lambda _name: False

    with pytest.raises(agent.AgentError) as exc:
        controller.presence(
            "earnapp-ubuntu-1",
            {"generation": 3, "device_id": "sdk-node-" + "a" * 32},
        )

    assert exc.value.status == 404


def test_helper_rejects_presence_when_the_provider_marker_does_not_match():
    agent = _module()
    controller = agent.Controller()
    payload = _payload()
    controller._exists = lambda _name: True
    controller._config = lambda _name: {
        "config": {
            "user.cashpilot.provider": "nkn",
            "user.cashpilot.earnapp.logical_node_id": "earnapp-ubuntu-1",
            "user.cashpilot.earnapp.generation": "3",
            "user.cashpilot.earnapp.device_id": payload["device_id"],
        }
    }

    with pytest.raises(agent.AgentError) as exc:
        controller.presence(
            "earnapp-ubuntu-1",
            {"generation": 3, "device_id": payload["device_id"]},
        )

    assert exc.value.status == 409


def test_helper_evidence_includes_actual_guest_egress_without_credentials(monkeypatch):
    agent = _module()
    controller = agent.Controller()
    payload = agent.validate_deploy("earnapp-ubuntu-1", _payload())
    controller._assigned = lambda *_args: ("cashpilot-earnapp-earnapp-ubuntu-1", payload)
    controller._status = lambda _name: "running"
    controller._probe_egress = lambda _name: "203.0.113.10"
    monkeypatch.setattr(
        agent,
        "_run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args,
            0,
            json.dumps(
                {
                    "device_id": payload["device_id"],
                    "version": "1.651.510",
                    "earnapp_active": True,
                    "proxy_active": True,
                }
            ).encode(),
            b"",
        ),
    )

    evidence = controller.evidence("earnapp-ubuntu-1", payload)
    assert evidence["observed_egress_ip"] == "203.0.113.10"
    assert evidence["probe_ok"] is True
    assert "secret" not in json.dumps(evidence)


def test_helper_proxy_binding_is_cas_scoped_and_dispatches_apply_then_finalize():
    agent = _module()
    payload = _payload()
    payload.update(
        {
            "expected_proxy_id": 12,
            "binding_version": "rotation_12345678",
            "proxy": {**payload["proxy"], "proxy_id": 13, "exit_ip": "203.0.113.13"},
        }
    )

    class Controller:
        def apply_proxy_binding(self, logical_node_id, body):
            assert logical_node_id == "earnapp-ubuntu-1"
            assert body["expected_proxy_id"] == 12
            return {"action": "applied"}

        def finalize_proxy_binding(self, logical_node_id, body):
            assert logical_node_id == "earnapp-ubuntu-1"
            assert body["commit"] is True
            return {"action": "confirmed"}

    assert (
        agent.dispatch("POST", "/v1/nodes/earnapp-ubuntu-1/proxy/apply", payload, Controller())["action"] == "applied"
    )
    payload.update({"new_proxy_id": 13, "commit": True})
    assert (
        agent.dispatch("POST", "/v1/nodes/earnapp-ubuntu-1/proxy/finalize", payload, Controller())["action"]
        == "confirmed"
    )


def test_helper_proxy_binding_status_reports_marker_and_candidate_artifacts(monkeypatch):
    agent = _module()
    controller = agent.Controller()
    payload = _payload()
    controller._assigned = lambda *_args: ("cashpilot-earnapp-earnapp-ubuntu-1", payload)
    monkeypatch.setattr(
        agent,
        "_run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args,
            0,
            json.dumps(
                {
                    "binding_version": "rotation_12345678",
                    "previous_present": True,
                    "candidate_present": False,
                }
            ).encode(),
            b"",
        ),
    )

    result = controller.proxy_binding_status("earnapp-ubuntu-1", payload)

    assert result == {
        "binding_version": "rotation_12345678",
        "previous_present": True,
        "candidate_present": False,
    }


def test_helper_discard_proxy_binding_removes_only_inactive_artifacts(monkeypatch):
    agent = _module()
    controller = agent.Controller()
    payload = _payload()
    payload.update({"expected_proxy_id": 12, "binding_version": "rotation_12345678"})
    controller._assigned = lambda *_args: ("cashpilot-earnapp-earnapp-ubuntu-1", payload)
    controller._config = lambda _name: {"config": {"user.cashpilot.earnapp.proxy_id": "12"}}
    commands = []
    statuses = iter(
        [
            {"binding_version": "", "previous_present": False, "candidate_present": True},
            {"binding_version": "", "previous_present": False, "candidate_present": False},
        ]
    )

    def run(args, **kwargs):
        commands.append(args)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(agent, "_run", run)
    monkeypatch.setattr(agent, "_artifact_status", lambda _name: next(statuses))

    result = controller.discard_proxy_binding("earnapp-ubuntu-1", payload)

    assert result == {
        "binding_version": "rotation_12345678",
        "action": "rolled_back",
        "proxy_id": 12,
        "idempotent": True,
    }
    shell = commands[-1][-1]
    assert "proxy.env.cashpilot-new" in shell
    assert ".cashpilot-binding-version" in shell
    assert "proxy.env.cashpilot-prev" not in shell


def test_installer_bootstrap_and_compose_use_a_dedicated_earnapp_socket():
    assert INSTALLER.is_file()
    assert SERVICE.is_file()
    installer = INSTALLER.read_text(encoding="utf-8")
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "cashpilot-earnapp-agent.py" in installer
    assert "cashpilot-earnapp-agent.service" in installer
    assert "systemctl enable cashpilot-earnapp-agent.service" in installer
    assert "install-earnapp-host-helper.sh" in bootstrap
    assert "/run/cashpilot-earnapp-agent:/run/cashpilot-earnapp-agent" in compose
    service = SERVICE.read_text(encoding="utf-8")
    assert "cashpilot-nkn-agent/agent.sock" not in service
    assert "Requires=snap.lxd.daemon.service" not in service
    assert "After=network-online.target docker.service" in service
    assert "Requires=docker.service" in service
    assert "ExecStart=/usr/bin/python3 /usr/local/lib/cashpilot/cashpilot-earnapp-agent.py" in service
    assert "ProtectHome=true" not in service
    assert "ProtectHome=read-only" in service


def test_helper_systemd_allows_snap_or_deb_lxd_paths_to_be_absent():
    service = SERVICE.read_text(encoding="utf-8")
    assert "ProtectSystem=strict" in service
    assert "RuntimeDirectory=cashpilot-earnapp-agent" in service
    assert "RuntimeDirectoryPreserve=yes" in service
    assert "Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin" in service
    assert "NoNewPrivileges=true" not in service
    assert "ReadWritePaths=/run/cashpilot-earnapp-agent -/var/lib/lxd -/var/snap/lxd" in service


def test_helper_socket_inherits_the_docker_group_for_the_non_root_worker(monkeypatch, tmp_path):
    agent = _module()
    socket_path = tmp_path / "agent.sock"
    chowns = []

    class Server:
        def __init__(self, path, _handler):
            Path(path).touch()

        def serve_forever(self, poll_interval):
            assert poll_interval == 0.5

        def server_close(self):
            return None

    monkeypatch.setattr(agent, "_UnixServer", Server)
    monkeypatch.setattr(agent, "_socket_group", lambda: 1234)
    monkeypatch.setattr(
        agent.os,
        "chown",
        lambda path, uid, gid: chowns.append((Path(path), uid, gid)),
        raising=False,
    )

    agent.serve(socket_path)

    assert chowns == [(socket_path, 0, 1234)]
