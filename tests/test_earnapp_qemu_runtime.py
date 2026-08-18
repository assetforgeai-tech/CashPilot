from __future__ import annotations

import asyncio
import io
import tarfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import earnapp_macos, earnapp_qemu, main, orchestrator


def test_earnapp_qemu_command_boots_ubuntu_2404_with_random_hardware_and_guest_systemd():
    identity = earnapp_qemu.new_identity("earnapp-proxy")
    command = earnapp_qemu.render_qemu_command(identity)

    assert "ubuntu-24.04-server-cloudimg-amd64.img" in command
    assert "qemu-system-x86_64" in command
    assert f"-uuid {identity.uuid}" in command
    assert f"mac={identity.mac}" in command
    assert "file=earnapp.qcow2,if=none,id=drive0,format=qcow2" in command
    assert f"virtio-blk-pci,drive=drive0,serial={identity.serial}" in command
    assert "format=qcow2,serial=" not in command
    assert "manufacturer=CashPilot" in command
    assert "[ systemctl, enable, earnapp-bootstrap.service ]" in command
    assert "[ systemctl, start, --no-block, earnapp-bootstrap.service ]" in command
    assert "TimeoutStartSec=0" in command
    assert "StandardOutput=journal+console" in command
    assert "StandardError=journal+console" in command
    assert "touch /etc/earnapp/earnapp_install.log" in command
    assert "tail -n +1 -F /etc/earnapp/*.log" in command
    assert "curl -m 10 -q4 ifconfig.co" in command
    assert "RID=$(openssl rand -hex 16)" in command
    assert 'sed -i "s|__OAUTH_TOKEN__|$(esc_sed "$OAUTH_TOKEN")|g" user-data' in command
    assert "/etc/systemd/system/earnapp*.service" not in command
    assert "systemctl restart earnapp earnapp_upgrader" in command
    assert "https://brightdata.com/static/earnapp/install.sh" in command
    assert "bash -x /tmp/earnapp.sh -y" not in command
    assert "set -euxo pipefail" not in command
    assert "set -euo pipefail" in command
    assert "bash /tmp/earnapp.sh -y" in command
    assert "__OAUTH_TOKEN__" in command
    assert "https://earnapp.com/dashboard/api/link_device" in command
    assert "\nCLOUD\nesc_sed()" in command
    assert "\ncat >meta-data" in command
    assert "\nMETA\ncloud-localds" in command


def test_earnapp_device_match_uses_sdk_prefix_not_sdk_node_only():
    assert main._earnapp_device_matches({"title": "sdk-node-616e277a"}, "sdk-node-2abb0e0439a943b19a25f182616e277a")
    assert main._earnapp_device_matches({"title": "sdk-mac-616e277a"}, "sdk-mac-2abb0e0439a943b19a25f182616e277a")
    assert not main._earnapp_device_matches({"title": "node-616e277a"}, "sdk-node-2abb0e0439a943b19a25f182616e277a")

@pytest.mark.asyncio
async def test_earnapp_not_earning_masks_proxy_and_retries(monkeypatch):
    proxies = [
        {"proxy_id": 101, "host": "bad.proxy", "port": 1080, "protocol": "socks5"},
        {"proxy_id": 202, "host": "good.proxy", "port": 1080, "protocol": "socks5"},
    ]
    devices = [
        ("sdk-node-bad", {"uuid": "sdk-node-bad", "title": "sdk-node-bad", "banned": {"reason": "ip_quality", "ip": "bad.proxy"}}),
        ("sdk-node-good", {"uuid": "sdk-node-good", "title": "sdk-node-good", "banned": None, "uptime": 12}),
    ]
    deployed_specs = []

    async def fake_proxy(_worker_id: int, *, provider_slug: str | None = None):
        assert provider_slug == "earnapp"
        return proxies.pop(0)

    async def fake_deploy(_worker_id: int, _instance_slug: str, spec: dict):
        deployed_specs.append(spec)
        return {"container_id": f"container-{len(deployed_specs)}"}

    monkeypatch.setattr(main, "_proxy_for_worker_instance", fake_proxy)
    monkeypatch.setattr(main, "_proxy_worker_deploy", fake_deploy)
    monkeypatch.setattr(main, "_earnapp_status_after_link", AsyncMock(side_effect=devices))
    monkeypatch.setattr(main, "_earnapp_remove_dashboard_device", AsyncMock())
    monkeypatch.setattr(main, "_proxy_worker_command", AsyncMock())
    monkeypatch.setattr(main.database, "mask_proxy_for_provider", AsyncMock(return_value=True))
    monkeypatch.setattr(main.database, "set_worker_proxy_assignment", AsyncMock(return_value=True))
    monkeypatch.setattr(main.database, "record_health_event", AsyncMock())

    result, final_spec, device = await main._deploy_earnapp_proxy_with_retry(
        7,
        "earnapp-proxy",
        {"deploy_credentials": {"oauth_token": "tok"}},
        attempts=2,
    )

    assert result["container_id"] == "container-2"
    assert final_spec["proxy"]["proxy_id"] == 202
    assert device and device["uuid"] == "sdk-node-good"
    main.database.mask_proxy_for_provider.assert_awaited_once_with(101, "earnapp", main.EARNAPP_BLOCKED_IP_REASON)
    main.database.set_worker_proxy_assignment.assert_awaited_once_with(7, None)
    main._earnapp_remove_dashboard_device.assert_awaited_once()
    main._proxy_worker_command.assert_awaited_once_with(7, "remove", "earnapp-proxy")

@pytest.mark.asyncio
async def test_earnapp_gray_device_masks_proxy_and_retries(monkeypatch):
    proxies = [
        {"proxy_id": 101, "host": "bad.proxy", "port": 1080, "protocol": "socks5", "location": "Vietnam"},
        {"proxy_id": 202, "host": "good.proxy", "port": 1080, "protocol": "socks5", "location": "Vietnam"},
    ]
    devices = [
        ("sdk-mac-bad", {"uuid": "sdk-mac-bad", "title": "sdk-mac-bad", "banned": None, "uptime": 0, "earned": 0}),
        ("sdk-mac-good", {"uuid": "sdk-mac-good", "title": "sdk-mac-good", "banned": None, "uptime": 12, "earned": 0}),
    ]

    async def fake_proxy(_worker_id: int, *, provider_slug: str | None = None):
        assert provider_slug == "earnapp"
        return proxies.pop(0)

    monkeypatch.setattr(main, "_proxy_for_worker_instance", fake_proxy)
    monkeypatch.setattr(main, "_proxy_worker_deploy", AsyncMock(return_value={"container_id": "container"}))
    monkeypatch.setattr(main, "_earnapp_status_after_link", AsyncMock(side_effect=devices))
    monkeypatch.setattr(main, "_earnapp_remove_dashboard_device", AsyncMock())
    monkeypatch.setattr(main, "_proxy_worker_command", AsyncMock())
    monkeypatch.setattr(main.database, "mask_proxy_for_provider", AsyncMock(return_value=True))
    monkeypatch.setattr(main.database, "set_worker_proxy_assignment", AsyncMock(return_value=True))
    monkeypatch.setattr(main.database, "record_health_event", AsyncMock())

    _result, final_spec, device = await main._deploy_earnapp_proxy_with_retry(
        7,
        "earnapp-proxy",
        {"deploy_credentials": {"oauth_token": "tok"}},
        attempts=2,
    )

    assert final_spec["proxy"]["proxy_id"] == 202
    assert device and device["uuid"] == "sdk-mac-good"
    main.database.mask_proxy_for_provider.assert_awaited_once_with(101, "earnapp", main.EARNAPP_BLOCKED_IP_REASON)

def test_deploy_raw_uses_earnapp_qemu_runtime_instead_of_provider_docker_image():
    client = MagicMock()
    client.containers.get.side_effect = orchestrator.NotFound("nope")
    container = MagicMock(short_id="abc123", id="container-id")
    client.containers.run.return_value = container

    with patch.object(orchestrator, "_get_client", return_value=client):
        result = orchestrator.deploy_raw(
            slug="earnapp-proxy",
            provider_slug="earnapp",
            image="legacy/ignored",
            host_runtime="qemu_systemd",
            deploy_credentials={
                "oauth_refresh_token": "refresh",
                "oauth_token": "token",
                "xsrf_token": "xsrf",
                "brd_sess_id": "sess",
                "cg_uuid": "uuid",
            },
            proxy={"host": "1.2.3.4", "port": 1080, "protocol": "socks5"},
        )

    assert result == "container-id"
    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["image"] == "ubuntu:24.04"
    assert kwargs["restart_policy"] == {"Name": "always"}
    assert kwargs["environment"]["OAUTH_TOKEN"] == "token"
    assert kwargs["labels"]["cashpilot.host-runtime"] == "qemu_systemd"
    assert kwargs["command"][:2] == ["/bin/bash", "-lc"]
    assert "qemu-system-x86_64" in kwargs["command"][2]
    assert kwargs["network_mode"] == "container:cashpilot-earnapp-proxy-egress"
    assert kwargs["devices"] == ["/dev/kvm:/dev/kvm:rwm"]

def test_earnapp_macos_runtime_uses_macos_launcher_not_linux_qemu():
    client = MagicMock()
    client.containers.get.side_effect = orchestrator.NotFound("nope")
    container = MagicMock(short_id="abc123", id="container-id")
    client.containers.run.return_value = container

    with patch.object(orchestrator, "_get_client", return_value=client):
        result = orchestrator.deploy_raw(
            slug="earnapp-proxy",
            provider_slug="earnapp",
            image="legacy/ignored",
            host_runtime="qemu_macos",
            deploy_credentials={"oauth_token": "token"},
            proxy={"host": "1.2.3.4", "port": 1080, "protocol": "socks5", "location": "Vietnam"},
        )

    assert result == "container-id"
    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["image"] == "ubuntu:24.04"
    assert kwargs["labels"]["cashpilot.host-runtime"] == "qemu_macos"
    assert kwargs["environment"]["CASHPILOT_STANDALONE"] == "true"
    assert kwargs["environment"]["INSTANCE"] == "earnapp-macos-001"
    assert kwargs["environment"]["MANUAL_PROXY"].startswith("socks5://1.2.3.4:1080")
    assert "EARNAPP_SINGBOX_DNS_MODE" not in kwargs["environment"]
    assert kwargs["environment"]["MANUAL_PROXY_DNS_IPS"] == "1.1.1.1,8.8.8.8"
    assert "docker-compose-v2" in kwargs["command"][2]
    assert "sshpass" in kwargs["command"][2]
    assert "/var/run/docker.sock" in kwargs["volumes"]
    assert kwargs["volumes"]["/opt/cashpilot-secrets/earnapp-macos"]["bind"] == "/runtime/secrets"
    assert kwargs["pid_mode"] == "host"
    assert kwargs["cap_add"] == ["NET_ADMIN", "SYS_ADMIN"]
    assert kwargs["privileged"] is True
    container.put_archive.assert_called_once()

def test_earnapp_macos_runtime_uses_worker_runtime_root(monkeypatch):
    client = MagicMock()
    client.containers.get.side_effect = orchestrator.NotFound("nope")
    container = MagicMock(short_id="abc123", id="container-id")
    client.containers.run.return_value = container
    monkeypatch.setenv("CASHPILOT_RUNTIME_ROOT", "/mnt/cashpilot-runtime")

    with patch.object(orchestrator, "_get_client", return_value=client):
        orchestrator.deploy_raw(
            slug="earnapp-proxy",
            provider_slug="earnapp",
            image="legacy/ignored",
            host_runtime="qemu_macos",
            deploy_credentials={"oauth_token": "token"},
            proxy={"host": "1.2.3.4", "port": 1080, "protocol": "socks5", "location": "Vietnam"},
        )

    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["environment"]["MAC_ROOT"] == "/mnt/cashpilot-runtime/dockur-macos"
    assert kwargs["environment"]["MACOS_R2_ENV_FILE"] == "/runtime/macos-r2.env"
    assert kwargs["volumes"]["/mnt/cashpilot-runtime/dockur-macos"]["bind"] == "/mnt/cashpilot-runtime/dockur-macos"

def test_earnapp_macos_launcher_defaults_to_monterey12_image():
    bundle = earnapp_macos._bundle_tar({"oauth_token": "token"})
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as tar:
        script_file = tar.extractfile("scripts/proxy-manager-macos-earnapp-smoke.sh")
        assert script_file is not None
        script = script_file.read().decode()
    assert "MACOS_VERSION=${MACOS_VERSION:-12}" in script
    assert "monterey12-os-only-1792m-v1-20260716T153103Z.qcow2" in script
    assert "os-only-1792m-v1.qcow2" not in script
    assert "cee45546058701852b822662971fbe1e8fc420e33eadc40c407ba239181324e3" not in script

def test_earnapp_macos_launcher_strips_sha256_prefix_before_bootstrap():
    bundle = earnapp_macos._bundle_tar({"oauth_token": "token"})
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as tar:
        script_file = tar.extractfile("scripts/proxy-manager-macos-earnapp-smoke.sh")
        assert script_file is not None
        script = script_file.read().decode()
    assert 'local bootstrap_base_sha256="${BASE_SHA256:-${MACOS_BASE_SHA256:-}}"' in script
    assert 'local BOOTSTRAP_BASE_SHA256="${bootstrap_base_sha256#sha256:}"' in script
    assert '--source-sha256 "$BOOTSTRAP_BASE_SHA256"' in script

def test_earnapp_macos_bundle_marks_launcher_executable():
    bundle = earnapp_macos._bundle_tar({"oauth_token": "token"})
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as tar:
        script = tar.getmember("scripts/proxy-manager-macos-earnapp-smoke.sh")
        auth = tar.extractfile("earnapp-auth-state.json")
        r2_env = tar.extractfile("macos-r2.env")
        assert script.mode & 0o111
        assert auth and b"oauth-token" in auth.read()
        assert r2_env and b"R2_ENDPOINT_URL=" in r2_env.read()

def test_earnapp_macos_launcher_uses_mac_root_for_runtime_paths():
    bundle = earnapp_macos._bundle_tar({"oauth_token": "token"})
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as tar:
        script_file = tar.extractfile("scripts/proxy-manager-macos-earnapp-smoke.sh")
        assert script_file is not None
        script = script_file.read().decode()
    assert 'Path(os.environ["MAC_ROOT"]) / "identity" / "registry.jsonl"' in script
    assert 'Path("/opt/dockur-macos/identity/registry.jsonl")' not in script
    assert "proxy_route_endpoint = socket.gethostbyname(endpoint)" in script
    assert '"server": proxy_route_endpoint' in script
    assert 'f"{proxy_route_endpoint}/32"' in script
    assert 'endpoint_ip=$(getent ahostsv4 "$endpoint" | awk' in script

def test_earnapp_macos_launcher_uses_redsocks_tcp_redirect():
    bundle = earnapp_macos._bundle_tar({"oauth_token": "token"})
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as tar:
        script_file = tar.extractfile("scripts/proxy-manager-macos-earnapp-smoke.sh")
        assert script_file is not None
        script = script_file.read().decode()
    assert "redsocks -c /etc/redsocks.conf" in script
    assert "local_ip = 0.0.0.0;" in script
    assert "iptables -t nat -A OUTPUT -p tcp -j REDSOCKS" in script
    assert "iptables -t nat -A PREROUTING -p tcp -j REDSOCKS" in script
    assert "REDIRECT --to-ports 12345" in script
    assert "NODE_TLS_REJECT_UNAUTHORIZED: \"0\"" in script
    assert "SING_BOX_IMAGE" not in script

def test_earnapp_macos_launcher_links_with_source_payload_shape():
    bundle = earnapp_macos._bundle_tar({"oauth_token": "token"})
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as tar:
        script_file = tar.extractfile("scripts/proxy-manager-macos-earnapp-smoke.sh")
        assert script_file is not None
        script = script_file.read().decode()
    assert '-d "{\\"uuid\\":\\"$uuid\\",\\"platform\\":\\"macos\\",\\"_csrf\\":\\"$xsrf\\"}"' in script
    assert '-d "{\\"data\\":{\\"uuid\\":\\"$uuid\\"' not in script
    assert "earnapp-link-response.last" in script
    assert "client.earnapp.com/install_device" in script
    assert "earnapp-install-device-response.last" in script
    assert "already linked" in script
    assert "dashboard pending after link" in script
    link_block = script[script.index("link_earnapp_device()") : script.index("ensure_earnapp_running()")]
    assert "earnapp_guest_dashboard_curl" in link_block
    assert "earnapp_dashboard_curl" not in link_block
    assert "capture_earnapp_guest_diagnostics" in script

def test_earnapp_macos_already_linked_continues_to_dashboard_check():
    bundle = earnapp_macos._bundle_tar({"oauth_token": "token"})
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as tar:
        script_file = tar.extractfile("scripts/proxy-manager-macos-earnapp-smoke.sh")
        assert script_file is not None
        script = script_file.read().decode()
    link_block = script[script.index("link_earnapp_device()") : script.index("ensure_earnapp_running()")]
    assert 'already_linked = true' not in link_block
    assert '[ "$already_linked" = true ]' in link_block
    assert 'status=already_linked_unverified' not in link_block
    assert '{ [ "$ok_marker" = true ] || [ "$already_linked" = true ]; }' in link_block

def test_earnapp_macos_launcher_links_runtime_uuid_not_stale_registration_uuid():
    bundle = earnapp_macos._bundle_tar({"oauth_token": "token"})
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as tar:
        script_file = tar.extractfile("scripts/proxy-manager-macos-earnapp-smoke.sh")
        assert script_file is not None
        script = script_file.read().decode()
    identity_block = script[script.index("wait_earnapp_identity()") : script.index("wait_earnapp_local_runtime_ready()")]
    ready_block = script[script.index("wait_earnapp_local_runtime_ready()") : script.index("earnapp_proxy_curl()")]
    assert "defaults read com.earnapp.brdsdk.shared uuid 2>/dev/null || defaults read com.earnapp registration_uuid" in identity_block
    assert 'printf \'%s\\n\' "$uuid" >"$STATE/earnapp-device-uuid.txt"' in ready_block

def test_earnapp_macos_launcher_keeps_container_alive_after_link():
    bundle = earnapp_macos._bundle_tar({"oauth_token": "token"})
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as tar:
        script_file = tar.extractfile("scripts/proxy-manager-macos-earnapp-smoke.sh")
        assert script_file is not None
        script = script_file.read().decode()
    assert "hold_linked_runtime()" in script
    assert "while sleep 300" in script
    assert "heartbeat_earnapp_cookie linked || true" in script
    assert "jq . \"$REPORT\"\n      hold_linked_runtime" in script

def test_earnapp_macos_registers_and_links_from_guest_egress():
    bundle = earnapp_macos._bundle_tar({"oauth_token": "token"})
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as tar:
        script_file = tar.extractfile("scripts/proxy-manager-macos-earnapp-smoke.sh")
        assert script_file is not None
        script = script_file.read().decode()
    link_block = script[script.index("register_earnapp_macos_device()") : script.index("ensure_earnapp_running()")]
    assert "earnapp_guest_dashboard_curl" in link_block
    assert "check_earnapp_macos_linked" in link_block
    assert "client.earnapp.com/is_linked" in script
    assert "guest_pipe \"$ip\"" in script
    assert "earnapp_dashboard_curl" not in link_block
    assert "register_earnapp_macos_device \"$ip\" \"$uuid\"" in link_block
    register_block = script[script.index("register_earnapp_macos_device()") : script.index("link_earnapp_device()")]
    assert "--insecure" in register_block
    assert "--http1.1" in register_block
    assert 'printf \'%s\\n\' "${status:-000}"' in register_block

def test_earnapp_macos_link_flow_matches_2movn_soft_retry():
    bundle = earnapp_macos._bundle_tar({"oauth_token": "token"})
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as tar:
        script_file = tar.extractfile("scripts/proxy-manager-macos-earnapp-smoke.sh")
        assert script_file is not None
        script = script_file.read().decode()

    register_block = script[script.index("register_earnapp_macos_device()") : script.index("check_earnapp_macos_linked()")]
    link_block = script[script.index("link_earnapp_device()") : script.index("ensure_earnapp_running()")]

    assert "EARNAPP_INSTALL_DEVICE_ATTEMPTS=${EARNAPP_INSTALL_DEVICE_ATTEMPTS:-1}" in script
    assert "EARNAPP_LINK_ATTEMPTS=${EARNAPP_LINK_ATTEMPTS:-3}" in script
    assert "for attempt in" not in register_block
    assert "body=${3:-}" in register_block
    assert 'printf \'%s\\n\' "${status:-000}"' in register_block
    assert 'install_status=$(register_earnapp_macos_device "$ip" "$uuid" "$install_body")' in link_block
    assert 'register_earnapp_macos_device "$ip" "$uuid" || true' not in link_block
    assert "--arg install_status" in link_block
    assert '[ "$link_attempt" -lt "$link_attempts" ] && sleep "$EARNAPP_LINK_RETRY_SECONDS"' in link_block
    assert '[ "$status" = linked ] && break' in link_block

def test_earnapp_macos_links_after_uuid_and_heartbeats():
    bundle = earnapp_macos._bundle_tar({"oauth_token": "token"})
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as tar:
        script_file = tar.extractfile("scripts/proxy-manager-macos-earnapp-smoke.sh")
        assert script_file is not None
        script = script_file.read().decode()
    ready_block = script[script.index("wait_earnapp_local_runtime_ready()") : script.index("earnapp_proxy_curl()")]
    assert "*perr_install_device_success.log" in script
    assert '[ -n "$app_config_file" ]' not in ready_block
    assert '[ -n "$cid" ]' not in ready_block
    assert "real macOS 12 EarnApp writes heartbeats" in ready_block
    assert "EARNAPP_LOCAL_RUNTIME_READY_MIN_HEARTBEATS" in ready_block

def test_earnapp_macos_local_ready_probe_does_not_inline_quoted_path_tests():
    bundle = earnapp_macos._bundle_tar({"oauth_token": "token"})
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as tar:
        script_file = tar.extractfile("scripts/proxy-manager-macos-earnapp-smoke.sh")
        assert script_file is not None
        script = script_file.read().decode()
    ready_block = script[script.index("wait_earnapp_local_runtime_ready()") : script.index("earnapp_proxy_curl()")]
    assert 'support_flag=$([ -n "$support_cid_file" ] && echo yes || echo no)' in ready_block
    assert 'brdsdk_flag=$([ -n "$brdsdk_log" ] && echo yes || echo no)' in ready_block
    assert 'support=$( [ -n \\"$support_cid_file\\" ]' not in ready_block

def test_earnapp_macos_launcher_waits_for_netns_before_redsocks():
    bundle = earnapp_macos._bundle_tar({"oauth_token": "token"})
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as tar:
        script_file = tar.extractfile("scripts/proxy-manager-macos-earnapp-smoke.sh")
        assert script_file is not None
        script = script_file.read().decode()
    assert "wait_netns_pid()" in script
    assert "apply_netns_firewall()" in script
    assert "wait_netns_pid >/dev/null" in script
    assert "run_start_step redsocks-up" in script

def test_earnapp_macos_launcher_excludes_proxy_endpoint_from_redsocks():
    bundle = earnapp_macos._bundle_tar({"oauth_token": "token"})
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as tar:
        script_file = tar.extractfile("scripts/proxy-manager-macos-earnapp-smoke.sh")
        assert script_file is not None
        script = script_file.read().decode()
    assert "endpoint = socket.gethostbyname(endpoint)" in script
    assert "iptables -t nat -A REDSOCKS -d {endpoint}/32 -j RETURN" in script

def test_earnapp_macos_launcher_resolves_proxy_hostname_before_singbox_outbound():
    bundle = earnapp_macos._bundle_tar({"oauth_token": "token"})
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as tar:
        script_file = tar.extractfile("scripts/proxy-manager-macos-earnapp-smoke.sh")
        assert script_file is not None
        script = script_file.read().decode()
    assert "import socket" in script
    assert "endpoint = socket.gethostbyname(endpoint)" in script
    assert 'proxy["endpoint_ip"] = endpoint' in script

def test_earnapp_macos_launcher_links_after_redsocks_netns_probe_and_heartbeats():
    bundle = earnapp_macos._bundle_tar({"oauth_token": "token"})
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as tar:
        script_file = tar.extractfile("scripts/proxy-manager-macos-earnapp-smoke.sh")
        assert script_file is not None
        script = script_file.read().decode()
    assert "export MANUAL_PROXY_DNS_IPS" in script
    assert "EARNAPP_SINGBOX_DNS_MODE" not in script
    ready_block = script[script.index("wait_earnapp_local_runtime_ready()") : script.index("earnapp_proxy_curl()")]
    assert "proxy_connected=true" in ready_block
    assert '[ "$proxy_connected" = true ]' not in ready_block
    assert "wait_network_ready" in script

def test_earnapp_macos_runtime_keeps_random_identity_controller():
    bundle = earnapp_macos._bundle_tar({"oauth_token": "token"})
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as tar:
        identity = tar.extractfile("tools/macos-on-vps/controller/identity.py")
        assert identity is not None
        source = identity.read().decode()
        for marker in ("secrets.token_bytes(6)", "uuid.uuid4()", "secrets.token_hex(4)", "_fallback_smbios"):
            assert marker in source

@pytest.mark.asyncio
async def test_earnapp_proxy_rotation_keeps_vietnam_assignment_for_macos(monkeypatch):
    current = {"proxy_id": 2, "host": "vn.proxy", "port": 1080, "protocol": "socks5", "location": "Vietnam"}

    async def get_assignment(_worker_id: int):
        return current

    monkeypatch.setattr(main.database, "get_worker_proxy_assignment", get_assignment)
    monkeypatch.setattr(main.database, "set_worker_proxy_assignment", AsyncMock(return_value=True))
    monkeypatch.setattr(main.database, "lease_proxy_for_worker", AsyncMock())
    monkeypatch.setattr(main.database, "proxy_masked_for_provider", AsyncMock(return_value=False))
    monkeypatch.setattr(main.database, "mask_proxy_for_provider", AsyncMock())

    proxy = await main._proxy_for_worker_instance(8532, provider_slug="earnapp")

    assert proxy["proxy_id"] == 2
    assert main._earnapp_host_runtime_for_proxy(proxy) == "qemu_macos"
    main.database.lease_proxy_for_worker.assert_not_awaited()

@pytest.mark.asyncio
async def test_earnapp_non_vietnam_and_unknown_use_ubuntu_qemu():
    assert main._earnapp_host_runtime_for_proxy({"location": "Singapore"}) == "qemu_systemd"
    assert main._earnapp_host_runtime_for_proxy({"location": ""}) == "qemu_systemd"

@pytest.mark.asyncio
async def test_earnapp_deploy_sets_macos_runtime_for_vietnam_proxy(monkeypatch):
    deployed_specs = []

    async def fake_proxy(_worker_id: int, *, provider_slug: str | None = None):
        return {"proxy_id": 2, "host": "vn.proxy", "port": 1080, "protocol": "socks5", "location": "Vietnam"}

    async def fake_deploy(_worker_id: int, _instance_slug: str, spec: dict):
        deployed_specs.append(spec)
        return {"container_id": "container-1"}

    monkeypatch.setattr(main, "_proxy_for_worker_instance", fake_proxy)
    monkeypatch.setattr(main, "_proxy_worker_deploy", fake_deploy)
    monkeypatch.setattr(main, "_earnapp_status_after_link", AsyncMock(return_value=("sdk-mac-ok", {"uuid": "sdk-mac-ok", "banned": None, "uptime": 12})))

    await main._deploy_earnapp_proxy_with_retry(7, "earnapp-proxy", {"deploy_credentials": {"oauth_token": "tok"}})

    assert deployed_specs[0]["host_runtime"] == "qemu_macos"


@pytest.mark.asyncio
async def test_earnapp_macos_pending_does_not_mask_proxy_or_remove_container(monkeypatch):
    async def fake_proxy(_worker_id: int, *, provider_slug: str | None = None):
        return {"proxy_id": 2, "host": "vn.proxy", "port": 1080, "protocol": "socks5", "location": "Vietnam"}

    monkeypatch.setattr(main, "_proxy_for_worker_instance", fake_proxy)
    monkeypatch.setattr(main, "_proxy_worker_deploy", AsyncMock(return_value={"container_id": "container-1"}))
    monkeypatch.setattr(main, "_earnapp_status_after_link", AsyncMock(return_value=("", None)))
    monkeypatch.setattr(main.database, "record_health_event", AsyncMock())
    monkeypatch.setattr(main.database, "mask_proxy_for_provider", AsyncMock())
    monkeypatch.setattr(main, "_proxy_worker_command", AsyncMock())

    result, final_spec, device = await main._deploy_earnapp_proxy_with_retry(7, "earnapp-proxy", {"deploy_credentials": {"oauth_token": "tok"}})

    assert result == {"container_id": "container-1"}
    assert final_spec["host_runtime"] == "qemu_macos"
    assert device is None
    main.database.mask_proxy_for_provider.assert_not_awaited()
    main._proxy_worker_command.assert_not_awaited()

@pytest.mark.asyncio
async def test_earnapp_macos_status_wait_covers_link_and_green_window(monkeypatch):
    calls = 0

    async def fake_logs(_worker_id: int, _instance_slug: str, lines: int = 300):
        return {"logs": "sdk-mac-wait"}

    async def fake_fetch(_creds: dict, _sdk_id: str):
        nonlocal calls
        calls += 1
        return None

    monkeypatch.setattr(main, "_proxy_worker_logs", fake_logs)
    monkeypatch.setattr(main, "_earnapp_fetch_device", fake_fetch)
    monkeypatch.setattr(main.asyncio, "sleep", AsyncMock())

    await main._earnapp_status_after_link(7, "earnapp-proxy", {"host_runtime": "qemu_macos"})

    assert calls == main.EARNAPP_MACOS_STATUS_POLLS

@pytest.mark.asyncio
async def test_earnapp_macos_sdk_id_wait_covers_slow_guest_link(monkeypatch):
    log_calls = 0

    async def fake_logs(_worker_id: int, _instance_slug: str, lines: int = 300):
        nonlocal log_calls
        log_calls += 1
        assert lines == 1000
        if log_calls == main.EARNAPP_MACOS_SDK_ID_POLLS:
            return {"logs": "EARNAPP_DEVICE_UUID=sdk-mac-slow"}
        return {"logs": ""}

    monkeypatch.setattr(main, "_proxy_worker_logs", fake_logs)
    monkeypatch.setattr(main, "_earnapp_fetch_device", AsyncMock(return_value={"uuid": "sdk-mac-slow", "uptime": 12}))
    monkeypatch.setattr(main.asyncio, "sleep", AsyncMock())

    sdk_id, device = await main._earnapp_status_after_link(7, "earnapp-proxy", {"host_runtime": "qemu_macos"})

    assert sdk_id == "sdk-mac-slow"
    assert device == {"uuid": "sdk-mac-slow", "uptime": 12}
    assert log_calls == main.EARNAPP_MACOS_SDK_ID_POLLS

@pytest.mark.asyncio
async def test_server_allows_earnapp_host_systemd_by_sending_qemu_runtime(monkeypatch):
    service = {
        "slug": "earnapp",
        "name": "EarnApp",
        "status": "active",
        "category": "bandwidth",
        "docker": {"image": "legacy/ignored", "env": [], "ports": [], "volumes": []},
        "deploy": {
            "deploy_surface": "host_systemd",
            "credentials": [
                {"key": "oauth_refresh_token", "arg": "oauth_refresh_token", "label": "refresh", "required": True},
                {"key": "oauth_token", "arg": "oauth_token", "label": "token", "required": True},
                {"key": "xsrf_token", "arg": "xsrf_token", "label": "xsrf", "required": True},
                {"key": "brd_sess_id", "arg": "brd_sess_id", "label": "session", "required": True},
                {"key": "cg_uuid", "arg": "cg_uuid", "label": "uuid", "required": True},
            ],
        },
    }
    config = {
        "earnapp_oauth_refresh_token": "refresh",
        "earnapp_oauth_token": "token",
        "earnapp_xsrf_token": "xsrf",
        "earnapp_brd_sess_id": "sess",
        "earnapp_cg_uuid": "uuid",
    }

    async def no_record(*_args, **_kwargs):
        return None

    deployed_specs = []

    async def fake_deploy(_worker_id: int, instance_slug: str, spec: dict):
        deployed_specs.append((instance_slug, spec))
        return {"container_id": "remote-id"}

    monkeypatch.setattr(main, "_require_owner", lambda _request: {"uid": 1, "r": "owner"})
    monkeypatch.setattr(main, "_resolve_worker_id", AsyncMock(return_value=7))
    monkeypatch.setattr(main.catalog, "get_service", lambda slug: service if slug == "earnapp" else None)
    monkeypatch.setattr(main.database, "get_config", AsyncMock(return_value=config))
    monkeypatch.setattr(main.database, "get_deployment_spec", no_record)
    monkeypatch.setattr(main.database, "get_worker", AsyncMock(return_value={"id": 7, "name": "vps-test-sing", "system_info": "{}"}))
    monkeypatch.setattr(main.database, "get_worker_proxy_assignment", AsyncMock(return_value=None))
    monkeypatch.setattr(main.database, "lease_proxy_for_worker", AsyncMock(return_value={"proxy_id": 1, "host": "1.2.3.4", "port": 1080, "protocol": "socks5", "location": "Singapore"}))
    monkeypatch.setattr(main.database, "proxy_masked_for_provider", AsyncMock(return_value=False))
    monkeypatch.setattr(main.database, "save_provider_instance", AsyncMock())
    monkeypatch.setattr(main.database, "record_health_event", AsyncMock())
    monkeypatch.setattr(main, "_proxy_worker_deploy", fake_deploy)
    monkeypatch.setattr(main, "_earnapp_status_after_link", AsyncMock(return_value=("sdk-node-ok", {"uuid": "sdk-node-ok", "banned": None, "uptime": 12})))
    monkeypatch.setattr(main, "_run_collection", AsyncMock())
    monkeypatch.setattr(main, "_run_post_deploy_automation", AsyncMock())
    monkeypatch.setattr(main, "_spawn", lambda coro: coro.close())

    resp = await main.api_deploy(
        main.Request({"type": "http", "method": "POST", "path": "/api/deploy/earnapp", "headers": []}),
        "earnapp",
        main.DeployRequest(env={}, mode="proxy"),
        _auth={"uid": 1, "r": "owner"},
    )

    assert resp["status"] == "deployed"
    assert deployed_specs[0][0] == "earnapp-proxy"
    assert deployed_specs[0][1]["host_runtime"] == "qemu_systemd"
    assert deployed_specs[0][1]["image"] == "ubuntu:24.04"

@pytest.mark.asyncio
async def test_earnapp_deploy_uses_account_pool_when_available(monkeypatch):
    service = {
        "slug": "earnapp",
        "name": "EarnApp",
        "status": "active",
        "category": "bandwidth",
        "docker": {"image": "legacy/ignored", "env": [], "ports": [], "volumes": []},
        "deploy": {
            "deploy_surface": "host_systemd",
            "credentials": [
                {"key": "oauth_refresh_token", "arg": "oauth_refresh_token", "label": "refresh", "required": True},
                {"key": "oauth_token", "arg": "oauth_token", "label": "token", "required": True},
                {"key": "xsrf_token", "arg": "xsrf_token", "label": "xsrf", "required": True},
                {"key": "brd_sess_id", "arg": "brd_sess_id", "label": "session", "required": True},
                {"key": "cg_uuid", "arg": "cg_uuid", "label": "uuid", "required": True},
            ],
        },
    }
    config = {
        "earnapp_oauth_refresh_token": "settings-refresh",
        "earnapp_oauth_token": "settings-token",
        "earnapp_xsrf_token": "settings-xsrf",
        "earnapp_brd_sess_id": "settings-sess",
        "earnapp_cg_uuid": "settings-uuid",
    }
    leased = {
        "account_name": "assetforgeai.gmail.com",
        "cookies": {
            "oauth_refresh_token": "pool-refresh",
            "oauth_token": "pool-token",
            "xsrf_token": "pool-xsrf",
            "brd_sess_id": "pool-sess",
            "cg_uuid": "pool-uuid",
        },
    }
    deployed_specs = []

    async def no_record(*_args, **_kwargs):
        return None

    async def fake_deploy(_worker_id: int, instance_slug: str, spec: dict):
        deployed_specs.append((instance_slug, spec))
        return {"container_id": "remote-id"}

    monkeypatch.setattr(main, "_resolve_worker_id", AsyncMock(return_value=7))
    monkeypatch.setattr(main.catalog, "get_service", lambda slug: service if slug == "earnapp" else None)
    monkeypatch.setattr(main.database, "get_config", AsyncMock(return_value=config))
    monkeypatch.setattr(main.database, "get_deployment_spec", no_record)
    monkeypatch.setattr(main.database, "get_worker_proxy_assignment", AsyncMock(return_value=None))
    monkeypatch.setattr(main.database, "lease_proxy_for_worker", AsyncMock(return_value={"proxy_id": 1, "host": "1.2.3.4", "port": 1080, "protocol": "socks5", "location": "Singapore"}))
    monkeypatch.setattr(main.database, "proxy_masked_for_provider", AsyncMock(return_value=False))
    monkeypatch.setattr(main.database, "lease_earnapp_account", AsyncMock(return_value=leased))
    monkeypatch.setattr(main.database, "save_provider_instance", AsyncMock())
    monkeypatch.setattr(main.database, "record_health_event", AsyncMock())
    monkeypatch.setattr(main, "_proxy_worker_deploy", fake_deploy)
    monkeypatch.setattr(main, "_earnapp_status_after_link", AsyncMock(return_value=("sdk-node-ok", {"uuid": "sdk-node-ok", "banned": None, "uptime": 12})))
    monkeypatch.setattr(main, "_run_collection", AsyncMock())
    monkeypatch.setattr(main, "_run_post_deploy_automation", AsyncMock())
    monkeypatch.setattr(main, "_spawn", lambda coro: coro.close())

    await main.api_deploy(
        main.Request({"type": "http", "method": "POST", "path": "/api/deploy/earnapp", "headers": []}),
        "earnapp",
        main.DeployRequest(env={}, mode="proxy"),
        _auth={"uid": 1, "r": "owner"},
    )

    creds = deployed_specs[0][1]["deploy_credentials"]
    assert creds["oauth_token"] == "pool-token"
    assert creds["earnapp_account_name"] == "assetforgeai.gmail.com"

@pytest.mark.asyncio
async def test_earnapp_account_pool_allows_empty_settings_credentials(monkeypatch):
    service = {
        "slug": "earnapp",
        "name": "EarnApp",
        "status": "active",
        "category": "bandwidth",
        "docker": {"image": "legacy/ignored", "env": [], "ports": [], "volumes": []},
        "deploy": {
            "deploy_surface": "host_systemd",
            "credentials": [
                {"key": "oauth_refresh_token", "arg": "oauth_refresh_token", "label": "refresh", "required": True},
                {"key": "oauth_token", "arg": "oauth_token", "label": "token", "required": True},
                {"key": "xsrf_token", "arg": "xsrf_token", "label": "xsrf", "required": True},
                {"key": "brd_sess_id", "arg": "brd_sess_id", "label": "session", "required": True},
                {"key": "cg_uuid", "arg": "cg_uuid", "label": "uuid", "required": True},
            ],
        },
    }
    deployed_specs = []

    async def no_record(*_args, **_kwargs):
        return None

    async def fake_deploy(_worker_id: int, instance_slug: str, spec: dict):
        deployed_specs.append((instance_slug, spec))
        return {"container_id": "remote-id"}

    monkeypatch.setattr(main, "_resolve_worker_id", AsyncMock(return_value=7))
    monkeypatch.setattr(main.catalog, "get_service", lambda slug: service if slug == "earnapp" else None)
    monkeypatch.setattr(main.database, "get_config", AsyncMock(return_value={}))
    monkeypatch.setattr(main.database, "get_deployment_spec", no_record)
    monkeypatch.setattr(main.database, "get_worker_proxy_assignment", AsyncMock(return_value=None))
    monkeypatch.setattr(main.database, "lease_proxy_for_worker", AsyncMock(return_value={"proxy_id": 1, "host": "1.2.3.4", "port": 1080, "protocol": "socks5", "location": "Singapore"}))
    monkeypatch.setattr(main.database, "proxy_masked_for_provider", AsyncMock(return_value=False))
    monkeypatch.setattr(main.database, "lease_earnapp_account", AsyncMock(return_value={"account_name": "a@example.com", "cookies": {"oauth_token": "pool-token", "oauth_refresh_token": "r", "xsrf_token": "x", "brd_sess_id": "b", "cg_uuid": "c"}}))
    monkeypatch.setattr(main.database, "save_provider_instance", AsyncMock())
    monkeypatch.setattr(main.database, "record_health_event", AsyncMock())
    monkeypatch.setattr(main, "_proxy_worker_deploy", fake_deploy)
    monkeypatch.setattr(main, "_earnapp_status_after_link", AsyncMock(return_value=("sdk-node-ok", {"uuid": "sdk-node-ok", "banned": None, "uptime": 12})))
    monkeypatch.setattr(main, "_run_collection", AsyncMock())
    monkeypatch.setattr(main, "_run_post_deploy_automation", AsyncMock())
    monkeypatch.setattr(main, "_spawn", lambda coro: coro.close())

    await main.api_deploy(
        main.Request({"type": "http", "method": "POST", "path": "/api/deploy/earnapp", "headers": []}),
        "earnapp",
        main.DeployRequest(env={}, mode="proxy"),
        _auth={"uid": 1, "r": "owner"},
    )

    assert deployed_specs[0][1]["deploy_credentials"]["oauth_token"] == "pool-token"
