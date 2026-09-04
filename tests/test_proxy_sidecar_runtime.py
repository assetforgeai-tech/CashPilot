from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app import earnapp_runtime, orchestrator


def test_proxy_instance_runs_provider_inside_singbox_sidecar_namespace():
    client = MagicMock()
    client.containers.get.side_effect = [orchestrator.NotFound("nope"), orchestrator.NotFound("nope")]
    sidecar = MagicMock(short_id="side", id="sidecar-id", name="cashpilot-earnfm-proxy-egress")
    provider = MagicMock(short_id="provider", id="provider-id")
    client.containers.run.side_effect = [sidecar, provider]

    with patch.object(orchestrator, "_get_client", return_value=client):
        container_id = orchestrator.deploy_raw(
            slug="earnfm-proxy",
            image="fazalfarhan01/earnfm-client:latest",
            labels={"cashpilot.provider": "earnfm", "cashpilot.instance_mode": "proxy"},
            proxy={"host": "1.2.3.4", "port": 1080, "protocol": "socks5"},
        )

    assert container_id == "provider-id"
    sidecar_call, provider_call = client.containers.run.call_args_list
    assert sidecar_call.kwargs["name"] == "cashpilot-earnfm-proxy-egress"
    assert sidecar_call.kwargs["image"] == "ghcr.io/sagernet/sing-box:latest"
    assert sidecar_call.kwargs["environment"]["ENABLE_DEPRECATED_LEGACY_DNS_SERVERS"] == "true"
    assert sidecar_call.kwargs["cap_add"] == ["NET_ADMIN"]
    assert "/dev/net/tun:/dev/net/tun" in sidecar_call.kwargs["devices"]
    assert sidecar_call.kwargs["volumes"] == {
        "cashpilot-earnfm-proxy-egress-config": {"bind": "/etc/sing-box", "mode": "rw"}
    }
    assert ".cashpilot-initialized" in sidecar_call.kwargs["entrypoint"][2]
    assert sidecar_call.kwargs["labels"]["cashpilot.provider"] == "earnfm"
    assert sidecar_call.kwargs["labels"]["cashpilot.instance_mode"] == "proxy"
    assert provider_call.kwargs["network_mode"] == "container:cashpilot-earnfm-proxy-egress"
    assert provider_call.kwargs["name"] == "cashpilot-earnfm-proxy"
    assert provider_call.kwargs["labels"]["cashpilot.provider"] == "earnfm"
    assert provider_call.kwargs["labels"]["cashpilot.instance_mode"] == "proxy"


def test_earnapp_operator_artifact_is_never_pulled_from_a_public_registry():
    client = MagicMock()
    client.containers.get.side_effect = [orchestrator.NotFound("provider"), orchestrator.NotFound("sidecar")]
    image = MagicMock()
    image.attrs = {"Config": {"Labels": earnapp_runtime.required_image_labels("macos")}}
    client.images.get.return_value = image
    client.containers.run.side_effect = [MagicMock(id="sidecar-id"), MagicMock(id="provider-id", short_id="provider")]

    with patch.object(orchestrator, "_get_client", return_value=client):
        orchestrator.deploy_raw(
            slug="earnapp-mac-1",
            provider_slug="earnapp",
            image=earnapp_runtime.MAC_RUNTIME_IMAGE,
            labels={"cashpilot.provider": "earnapp", "cashpilot.earnapp.platform": "darwin"},
            host_runtime="earnapp_mac_canary",
            image_delivery="operator_preload",
            proxy={"host": "1.2.3.4", "port": 1080, "protocol": "socks5"},
        )

    client.images.pull.assert_not_called()
    client.images.get.assert_called_once_with(earnapp_runtime.MAC_RUNTIME_IMAGE)


def test_earnapp_deploy_fails_before_cleanup_when_operator_artifact_is_missing():
    client = MagicMock()
    client.images.get.side_effect = orchestrator.NotFound("missing image")

    with patch.object(orchestrator, "_get_client", return_value=client):
        try:
            orchestrator.deploy_raw(
                slug="earnapp-mac-1",
                provider_slug="earnapp",
                image=earnapp_runtime.MAC_RUNTIME_IMAGE,
                labels={"cashpilot.provider": "earnapp", "cashpilot.earnapp.platform": "darwin"},
                host_runtime="earnapp_mac_canary",
                image_delivery="operator_preload",
                proxy={"host": "1.2.3.4", "port": 1080, "protocol": "socks5"},
            )
        except RuntimeError as exc:
            assert "preload" in str(exc).lower()
        else:
            raise AssertionError("missing operator artifact must fail closed")

    client.containers.get.assert_not_called()
    client.containers.run.assert_not_called()
    client.volumes.get.assert_not_called()


def test_mysterium_proxy_routes_udp_direct():
    client = MagicMock()
    client.containers.get.side_effect = [orchestrator.NotFound("nope"), orchestrator.NotFound("nope")]
    client.containers.run.side_effect = [MagicMock(id="sidecar-id"), MagicMock(id="provider-id")]

    with (
        patch.object(orchestrator, "_get_client", return_value=client),
        patch.object(orchestrator.singbox_config, "render_tun_proxy_config", return_value={}) as render,
    ):
        orchestrator.deploy_raw(
            slug="mysterium-proxy",
            provider_slug="mysterium",
            image="mysteriumnetwork/myst:latest",
            labels={"cashpilot.provider": "mysterium", "cashpilot.instance_mode": "proxy"},
            proxy={"host": "1.2.3.4", "port": 1080, "protocol": "socks5"},
        )

    assert render.call_args.kwargs["udp_direct"] is True


def test_mysterium_proxy_publishes_udp_ports_on_sidecar():
    client = MagicMock()
    client.containers.get.side_effect = [orchestrator.NotFound("nope"), orchestrator.NotFound("nope")]
    sidecar = MagicMock(short_id="side", id="sidecar-id")
    provider = MagicMock(short_id="provider", id="provider-id")
    client.containers.run.side_effect = [sidecar, provider]

    with patch.object(orchestrator, "_get_client", return_value=client):
        orchestrator.deploy_raw(
            slug="mysterium-proxy",
            provider_slug="mysterium",
            image="mysteriumnetwork/myst:latest",
            ports={"56000/udp": 56000, "56020/udp": 56020},
            labels={"cashpilot.provider": "mysterium", "cashpilot.instance_mode": "proxy"},
            proxy={"host": "1.2.3.4", "port": 1080, "protocol": "socks5"},
        )

    sidecar_call, provider_call = client.containers.run.call_args_list
    assert sidecar_call.kwargs["ports"] == {"56000/udp": 56000, "56020/udp": 56020}
    assert provider_call.kwargs["ports"] is None


def test_remove_proxy_instance_removes_egress_sidecar():
    client = MagicMock()
    provider = MagicMock(attrs={"Mounts": []})
    provider.name = "cashpilot-earnfm-proxy"
    provider.labels = {orchestrator.LABEL_MANAGED: "true"}
    sidecar = MagicMock()
    sidecar.name = "cashpilot-earnfm-proxy-egress"
    client.containers.get.side_effect = [provider, sidecar]

    with patch.object(orchestrator, "_get_client", return_value=client):
        result = orchestrator.remove_service("earnfm-proxy")

    assert result["container"] == provider.name
    provider.remove.assert_called_once_with(force=True)
    sidecar.remove.assert_called_once_with(force=True)
    client.containers.get.assert_any_call("cashpilot-earnfm-proxy-egress")


def test_earnapp_cleanup_fails_closed_when_sidecar_remains():
    """Account cleanup must not report success while its egress sidecar survives."""
    client = MagicMock()
    provider = MagicMock(attrs={"Mounts": []})
    provider.name = "cashpilot-earnapp-node-1"
    provider.labels = {
        orchestrator.LABEL_MANAGED: "true",
        orchestrator.LABEL_SERVICE: "earnapp-node-1",
        "cashpilot.provider": "earnapp",
    }
    sidecar = MagicMock()
    sidecar.name = "cashpilot-earnapp-node-1-egress"
    sidecar.labels = {
        orchestrator.LABEL_MANAGED: "true",
        orchestrator.LABEL_SERVICE: "earnapp-node-1",
        "cashpilot.provider": "earnapp",
        "cashpilot.role": "egress-sidecar",
    }
    # The sidecar remains discoverable after the attempted removal.
    sidecar.remove.side_effect = orchestrator.APIError("sidecar is busy")
    client.containers.get.side_effect = [provider, sidecar, provider, sidecar]

    with patch.object(orchestrator, "_get_client", return_value=client):
        try:
            orchestrator.remove_earnapp_service("earnapp-node-1")
        except RuntimeError as exc:
            assert "sidecar" in str(exc).lower()
        else:
            raise AssertionError("cleanup must fail when the sidecar cannot be removed")

    provider.remove.assert_called_once_with(force=True)


def test_earnapp_cleanup_removes_orphan_sidecar_after_main_is_gone():
    """A retry can remove an orphan sidecar without resurrecting or touching a node."""
    client = MagicMock()
    sidecar = MagicMock()
    sidecar.name = "cashpilot-earnapp-node-1-egress"
    sidecar.labels = {
        orchestrator.LABEL_MANAGED: "true",
        orchestrator.LABEL_SERVICE: "earnapp-node-1",
        "cashpilot.provider": "earnapp",
        "cashpilot.role": "egress-sidecar",
    }
    client.containers.get.side_effect = [
        orchestrator.NotFound("main is already gone"),
        sidecar,
        orchestrator.NotFound("main is gone"),
        orchestrator.NotFound("sidecar is gone"),
    ]

    with patch.object(orchestrator, "_get_client", return_value=client):
        result = orchestrator.remove_earnapp_service("earnapp-node-1")

    assert result["main_present"] is False
    assert result["sidecar_present"] is False
    sidecar.remove.assert_called_once_with(force=True)


def test_apply_proxy_binding_preflights_every_sidecar_before_writing_any_config():
    client = MagicMock()
    current = MagicMock()
    current.labels = {
        "cashpilot.role": "egress-sidecar",
        "cashpilot.provider": "earnfm",
    }
    current.attrs = {"Mounts": [{"Destination": "/etc/sing-box", "RW": True}]}
    legacy = MagicMock()
    legacy.labels = {
        "cashpilot.role": "egress-sidecar",
        "cashpilot.provider": "proxybase",
    }
    legacy.attrs = {"Mounts": []}
    client.containers.get.side_effect = [current, legacy]

    with patch.object(orchestrator, "_get_client", return_value=client):
        try:
            orchestrator.apply_proxy_binding_batch(
                ["earnfm-proxy", "proxybase-proxy"],
                {"host": "2.2.2.2", "port": 1080, "protocol": "socks5"},
                "rotation_1234567890",
            )
        except RuntimeError as exc:
            assert "predates persistent binding support" in str(exc)
        else:
            raise AssertionError("legacy sidecar must fail closed")

    current.exec_run.assert_not_called()
    current.restart.assert_not_called()


def test_apply_proxy_binding_restarts_only_sidecar_and_reports_config_hash():
    client = MagicMock()
    sidecar = MagicMock()
    sidecar.labels = {
        "cashpilot.role": "egress-sidecar",
        "cashpilot.provider": "earnfm",
    }
    sidecar.attrs = {"Mounts": [{"Destination": "/etc/sing-box", "RW": True}]}
    sidecar.exec_run.return_value = MagicMock(exit_code=0)
    sidecar.status = "running"
    client.containers.get.return_value = sidecar

    with (
        patch.object(orchestrator, "_get_client", return_value=client),
        patch.object(
            orchestrator.singbox_config, "render_tun_proxy_config", return_value={"route": {"final": "proxy-out"}}
        ),
    ):
        result = orchestrator.apply_proxy_binding_batch(
            ["earnfm-proxy"],
            {"host": "2.2.2.2", "port": 1080, "protocol": "socks5"},
            "rotation_1234567890",
        )

    assert result["applied_instances"] == ["earnfm-proxy"]
    assert len(result["config_sha256"]) == 64
    assert sidecar.exec_run.call_count >= 3
    sidecar.put_archive.assert_called_once()
    archive_path, archive_payload = sidecar.put_archive.call_args.args
    assert archive_path == "/etc/sing-box"
    assert len(archive_payload) > 0
    commands = [call.args[0][2] for call in sidecar.exec_run.call_args_list]
    assert any("sing-box check" in command for command in commands)
    assert any("rotation_1234567890" in command for command in commands)
    assert all("base64" not in command for command in commands)
    sidecar.restart.assert_called_once_with(timeout=30)


def test_apply_earnapp_proxy_binding_recreates_main_with_same_identity_volume_and_new_proxy():
    client = MagicMock()
    sidecar = MagicMock()
    sidecar.labels = {
        "cashpilot.role": "egress-sidecar",
        "cashpilot.provider": "earnapp",
    }
    sidecar.attrs = {"Mounts": [{"Destination": "/etc/sing-box", "RW": True}]}
    sidecar.id = "sidecar-id"
    sidecar.name = "earnapp-proxy-egress"
    sidecar.exec_run.return_value = MagicMock(exit_code=0)
    sidecar.status = "running"
    main = MagicMock()
    main.id = "old-main-id"
    main.name = "cashpilot-earnapp-proxy"
    main.labels = {
        orchestrator.LABEL_MANAGED: "true",
        orchestrator.LABEL_SERVICE: "earnapp-proxy",
        "cashpilot.provider": "earnapp",
        "cashpilot.role": "main",
        "cashpilot.earnapp.device_id": "sdk-node-" + "a" * 32,
    }
    main.attrs = {
        "Config": {
            "Image": "cashpilot/earnapp-ubuntu:asset-test",
            "Env": ["EARNAPP_DEVICE_ID=sdk-node-" + "a" * 32],
            "Cmd": ["/usr/local/bin/entrypoint.sh"],
            "Entrypoint": None,
            "Labels": main.labels,
            "Hostname": "earnapp-ubuntu-a",
            "User": "",
        },
        "HostConfig": {
            "NetworkMode": "container:sidecar-id",
            "Binds": ["earnapp-state:/etc/earnapp:rw"],
            "CapAdd": [],
            "Devices": [],
            "RestartPolicy": {"Name": "always"},
            "SecurityOpt": ["no-new-privileges:true"],
            "PidsLimit": 256,
        },
        "Mounts": [{"Type": "volume", "Name": "earnapp-state", "Destination": "/etc/earnapp", "RW": True}],
    }
    main.status = "running"
    main.exec_run.return_value = MagicMock(exit_code=0)
    replacement = MagicMock()
    replacement.id = "new-main-id"
    replacement.status = "running"
    client.containers.create.return_value = replacement
    client.containers.get.side_effect = [sidecar, main]

    with (
        patch.object(orchestrator, "_get_client", return_value=client),
        patch.object(
            orchestrator.singbox_config, "render_tun_proxy_config", return_value={"route": {"final": "proxy-out"}}
        ),
        patch.object(orchestrator, "_find_earnapp_runtime_container", return_value=main),
    ):
        result = orchestrator.apply_proxy_binding_batch(
            ["earnapp-proxy"],
            {"host": "2.2.2.2", "port": 1080, "protocol": "socks5", "exit_ip": "203.0.113.10"},
            "rotation_1234567890",
        )

    assert main.exec_run.called
    assert any("203.0.113.10" in repr(call.args) for call in main.exec_run.call_args_list)
    main.stop.assert_called_once_with(timeout=30)
    main.rename.assert_called_once()
    main.remove.assert_called_once_with(force=True)
    client.containers.create.assert_called_once()
    create_kwargs = client.containers.create.call_args.kwargs
    assert create_kwargs["volumes"] == {"earnapp-state": {"bind": "/etc/earnapp", "mode": "rw"}}
    assert create_kwargs["environment"]["EARNAPP_DEVICE_ID"] == "sdk-node-" + "a" * 32
    assert create_kwargs["network_mode"] == "container:sidecar-id"
    assert result["recreated_main_ids"] == {"earnapp-proxy": "new-main-id"}


def test_failed_earnapp_main_recreate_restores_the_previous_container():
    client = MagicMock()
    sidecar = MagicMock(id="sidecar-id", name="cashpilot-earnapp-node-egress")
    main = MagicMock(id="old-main-id", name="cashpilot-earnapp-node", status="running")
    main.labels = {
        orchestrator.LABEL_MANAGED: "true",
        orchestrator.LABEL_SERVICE: "earnapp-node",
        "cashpilot.provider": "earnapp",
    }
    main.attrs = {
        "Config": {"Image": "cashpilot/earnapp-ubuntu:asset-test", "Env": [], "Labels": main.labels},
        "HostConfig": {"NetworkMode": "container:sidecar-id", "RestartPolicy": {"Name": "always"}},
        "Mounts": [{"Type": "volume", "Name": "earnapp-state", "Destination": "/etc/earnapp", "RW": True}],
    }
    client.containers.create.side_effect = RuntimeError("create failed")

    with pytest.raises(RuntimeError, match="create failed"):
        orchestrator._recreate_earnapp_main_after_sidecar_restart(client, "earnapp-node", sidecar, main=main)

    main.stop.assert_called_once_with(timeout=30)
    assert main.rename.call_count == 2
    main.start.assert_called_once()
    main.remove.assert_not_called()


def test_recreate_earnapp_main_supports_bridge_runtime_without_sidecar():
    client = MagicMock()
    main = MagicMock(id="old-main-id", name="cashpilot-earnapp-node", status="running")
    main.labels = {
        orchestrator.LABEL_MANAGED: "true",
        orchestrator.LABEL_SERVICE: "earnapp-node",
        "cashpilot.provider": "earnapp",
    }
    main.attrs = {
        "Config": {"Image": "cashpilot/earnapp-mac:asset-test", "Env": [], "Labels": main.labels},
        "HostConfig": {"NetworkMode": "bridge", "RestartPolicy": {"Name": "always"}},
        "Mounts": [{"Type": "volume", "Name": "earnapp-state", "Destination": "/etc/earnapp", "RW": True}],
    }
    replacement = MagicMock(id="new-main-id", status="running")
    client.containers.create.return_value = replacement
    client.containers.get.side_effect = orchestrator.NotFound("missing")

    with (
        patch.object(orchestrator, "_get_client", return_value=client),
        patch.object(orchestrator, "_find_earnapp_runtime_container", return_value=main),
    ):
        result = orchestrator.recreate_earnapp_main("earnapp-node")

    assert result == "new-main-id"
    client.containers.get.assert_called_once()
    assert client.containers.create.call_args.kwargs["network_mode"] == "bridge"


def test_proxy_binding_status_reports_active_marker_and_artifacts():
    client = MagicMock()
    sidecar = MagicMock()
    sidecar.labels = {
        orchestrator.LABEL_MANAGED: "true",
        orchestrator.LABEL_SERVICE: "earnapp-proxy-1",
        "cashpilot.provider": "earnapp",
        "cashpilot.role": "egress-sidecar",
    }
    sidecar.attrs = {"Mounts": [{"Destination": "/etc/sing-box", "RW": True}]}
    sidecar.exec_run.return_value = MagicMock(
        exit_code=0,
        output=b'{"binding_version":"rotation_1234567890","previous_present":true,"candidate_present":false}\n',
    )
    client.containers.get.return_value = sidecar

    with patch.object(orchestrator, "_get_client", return_value=client):
        result = orchestrator.proxy_binding_status("earnapp-proxy-1")

    assert result == {
        "binding_version": "rotation_1234567890",
        "previous_present": True,
        "candidate_present": False,
    }


def test_discard_proxy_binding_removes_only_inactive_candidate_artifacts():
    client = MagicMock()
    sidecar = MagicMock()
    sidecar.labels = {
        orchestrator.LABEL_MANAGED: "true",
        orchestrator.LABEL_SERVICE: "earnapp-proxy-1",
        "cashpilot.provider": "earnapp",
        "cashpilot.role": "egress-sidecar",
    }
    sidecar.attrs = {"Mounts": [{"Destination": "/etc/sing-box", "RW": True}]}
    sidecar.exec_run.side_effect = [
        MagicMock(
            exit_code=0,
            output=b'{"binding_version":"","previous_present":false,"candidate_present":true}\n',
        ),
        MagicMock(exit_code=0),
        MagicMock(
            exit_code=0,
            output=b'{"binding_version":"","previous_present":false,"candidate_present":false}\n',
        ),
    ]
    client.containers.get.return_value = sidecar

    with patch.object(orchestrator, "_get_client", return_value=client):
        result = orchestrator.discard_proxy_binding("earnapp-proxy-1", "rotation_1234567890")

    assert result == {
        "binding_version": "rotation_1234567890",
        "action": "rolled_back",
        "idempotent": True,
    }
    cleanup_commands = [
        call.args[0][2] for call in sidecar.exec_run.call_args_list if call.args[0][2].startswith("rm -f")
    ]
    assert len(cleanup_commands) == 1
    cleanup = cleanup_commands[0]
    assert "config.json.cashpilot-new" in cleanup
    assert ".cashpilot-binding-version" in cleanup
    assert "config.json.cashpilot-prev" not in cleanup


def test_deploy_raw_replaces_ephemeral_config_volume_before_seeding_new_proxy():
    client = MagicMock()
    client.containers.get.side_effect = [orchestrator.NotFound("provider"), orchestrator.NotFound("sidecar")]
    client.containers.run.side_effect = [MagicMock(id="sidecar-id"), MagicMock(id="provider-id", short_id="provider")]
    with patch.object(orchestrator, "_get_client", return_value=client):
        orchestrator.deploy_raw(
            slug="earnfm-proxy",
            image="fazalfarhan01/earnfm-client:latest",
            labels={"cashpilot.provider": "earnfm", "cashpilot.instance_mode": "proxy"},
            proxy={"host": "2.2.2.2", "port": 1080, "protocol": "socks5"},
        )

    client.volumes.get.assert_called_once_with("cashpilot-earnfm-proxy-egress-config")
    client.volumes.get.return_value.remove.assert_called_once_with(force=True)


def test_deploy_raw_fails_closed_when_config_volume_cannot_be_reset():
    client = MagicMock()
    client.containers.get.side_effect = [orchestrator.NotFound("provider"), orchestrator.NotFound("sidecar")]
    client.volumes.get.return_value.remove.side_effect = orchestrator.APIError("volume is busy")

    with patch.object(orchestrator, "_get_client", return_value=client):
        try:
            orchestrator.deploy_raw(
                slug="earnfm-proxy",
                image="fazalfarhan01/earnfm-client:latest",
                labels={"cashpilot.provider": "earnfm", "cashpilot.instance_mode": "proxy"},
                proxy={"host": "2.2.2.2", "port": 1080, "protocol": "socks5"},
            )
        except orchestrator.APIError as exc:
            assert "volume is busy" in str(exc)
        else:
            raise AssertionError("a stale config volume must block proxy deployment")

    client.containers.run.assert_not_called()


def test_proxy_binding_validates_every_candidate_before_activating_any_sidecar():
    client = MagicMock()
    first = MagicMock()
    first.labels = {"cashpilot.role": "egress-sidecar", "cashpilot.provider": "earnfm"}
    first.attrs = {"Mounts": [{"Destination": "/etc/sing-box", "RW": True}]}
    first.exec_run.return_value = MagicMock(exit_code=0)
    second = MagicMock()
    second.labels = {"cashpilot.role": "egress-sidecar", "cashpilot.provider": "proxybase"}
    second.attrs = {"Mounts": [{"Destination": "/etc/sing-box", "RW": True}]}
    second.exec_run.return_value = MagicMock(exit_code=1)
    client.containers.get.side_effect = [first, second]

    with patch.object(orchestrator, "_get_client", return_value=client):
        try:
            orchestrator.apply_proxy_binding_batch(
                ["earnfm-proxy", "proxybase-proxy"],
                {"host": "2.2.2.2", "port": 1080, "protocol": "socks5"},
                "rotation_1234567890",
            )
        except RuntimeError as exc:
            assert "rejected the candidate" in str(exc)
        else:
            raise AssertionError("invalid candidate must fail closed")

    first.restart.assert_not_called()
    second.restart.assert_not_called()
    first_commands = [call.args[0][2] for call in first.exec_run.call_args_list]
    assert any("sing-box check" in command for command in first_commands)
    assert all('mv "$tmp" /etc/sing-box/config.json' not in command for command in first_commands)


def test_proxy_binding_rolls_back_all_activated_sidecars_when_restart_fails():
    client = MagicMock()
    first = MagicMock()
    first.labels = {"cashpilot.role": "egress-sidecar", "cashpilot.provider": "earnfm"}
    first.attrs = {"Mounts": [{"Destination": "/etc/sing-box", "RW": True}]}
    first.exec_run.return_value = MagicMock(exit_code=0)
    first.status = "running"
    second = MagicMock()
    second.labels = {"cashpilot.role": "egress-sidecar", "cashpilot.provider": "proxybase"}
    second.attrs = {"Mounts": [{"Destination": "/etc/sing-box", "RW": True}]}
    second.exec_run.return_value = MagicMock(exit_code=0)
    second.restart.side_effect = [RuntimeError("docker restart failed"), None]
    client.containers.get.side_effect = [first, second]

    with patch.object(orchestrator, "_get_client", return_value=client):
        try:
            orchestrator.apply_proxy_binding_batch(
                ["earnfm-proxy", "proxybase-proxy"],
                {"host": "2.2.2.2", "port": 1080, "protocol": "socks5"},
                "rotation_1234567890",
            )
        except RuntimeError as exc:
            assert "docker restart failed" in str(exc)
        else:
            raise AssertionError("restart failure must fail the binding")

    first_commands = [call.args[0][2] for call in first.exec_run.call_args_list]
    second_commands = [call.args[0][2] for call in second.exec_run.call_args_list]
    assert any("config.json.cashpilot-prev" in command and "mv" in command for command in first_commands)
    assert any("config.json.cashpilot-prev" in command and "mv" in command for command in second_commands)


def test_proxy_binding_finalize_confirms_matching_version_without_restart():
    client = MagicMock()
    sidecar = MagicMock()
    sidecar.labels = {"cashpilot.role": "egress-sidecar"}
    sidecar.attrs = {"Mounts": [{"Destination": "/etc/sing-box", "RW": True}]}
    sidecar.exec_run.return_value = MagicMock(exit_code=0)
    client.containers.get.return_value = sidecar

    with patch.object(orchestrator, "_get_client", return_value=client):
        result = orchestrator.finalize_proxy_binding_batch(["earnfm-proxy"], "rotation_1234567890", commit=True)

    assert result == {"finalized_instances": ["earnfm-proxy"], "action": "confirmed"}
    commands = [call.args[0][2] for call in sidecar.exec_run.call_args_list]
    assert any(".cashpilot-binding-version" in command for command in commands)
    assert any("rm -f /etc/sing-box/config.json.cashpilot-prev" in command for command in commands)
    sidecar.restart.assert_not_called()


def test_proxy_binding_finalize_rolls_back_matching_version_and_restarts_sidecar():
    client = MagicMock()
    sidecar = MagicMock()
    sidecar.labels = {"cashpilot.role": "egress-sidecar"}
    sidecar.attrs = {"Mounts": [{"Destination": "/etc/sing-box", "RW": True}]}
    sidecar.exec_run.return_value = MagicMock(exit_code=0)
    sidecar.status = "running"
    client.containers.get.return_value = sidecar

    with patch.object(orchestrator, "_get_client", return_value=client):
        result = orchestrator.finalize_proxy_binding_batch(["earnfm-proxy"], "rotation_1234567890", commit=False)

    assert result == {"finalized_instances": ["earnfm-proxy"], "action": "rolled_back"}
    command = sidecar.exec_run.call_args.args[0][2]
    assert "mv /etc/sing-box/config.json.cashpilot-prev /etc/sing-box/config.json" in command
    sidecar.restart.assert_called_once_with(timeout=30)


def test_earnapp_proxy_binding_recreates_main_container_after_sidecar_restart():
    """A route change must recreate the EarnApp process on the new namespace."""
    client = MagicMock()
    sidecar = MagicMock()
    sidecar.labels = {
        orchestrator.LABEL_MANAGED: "true",
        orchestrator.LABEL_SERVICE: "earnapp-node-1",
        "cashpilot.provider": "earnapp",
        "cashpilot.role": "egress-sidecar",
    }
    sidecar.attrs = {"Mounts": [{"Destination": "/etc/sing-box", "RW": True}]}
    sidecar.name = "cashpilot-earnapp-node-1-egress"
    sidecar.id = "sidecar-container-id"
    sidecar.exec_run.return_value = MagicMock(exit_code=0)
    sidecar.status = "running"
    main = MagicMock()
    main.labels = {
        orchestrator.LABEL_MANAGED: "true",
        orchestrator.LABEL_SERVICE: "earnapp-node-1",
        "cashpilot.provider": "earnapp",
    }
    main.id = "old-main-id"
    main.name = "cashpilot-earnapp-node-1"
    main.attrs = {
        "Config": {
            "Image": "cashpilot/earnapp-ubuntu:asset-test",
            "Env": ["EARNAPP_DEVICE_ID=sdk-node-" + "a" * 32],
            "Labels": main.labels,
        },
        "HostConfig": {"NetworkMode": "container:sidecar-container-id", "RestartPolicy": {"Name": "always"}},
        "Mounts": [{"Type": "volume", "Name": "earnapp-state", "Destination": "/etc/earnapp", "RW": True}],
    }
    client.containers.get.side_effect = [sidecar, main]
    main.status = "running"
    replacement = MagicMock(id="new-main-id", status="running")
    client.containers.create.return_value = replacement

    with patch.object(orchestrator, "_get_client", return_value=client):
        result = orchestrator.apply_proxy_binding_batch(
            ["earnapp-node-1"],
            {"host": "2.2.2.2", "port": 1080, "protocol": "socks5"},
            "rotation_1234567890",
        )

    assert result["applied_instances"] == ["earnapp-node-1"]
    assert result["recreated_main_ids"] == {"earnapp-node-1": "new-main-id"}
    main.stop.assert_called_once_with(timeout=30)
    main.remove.assert_called_once_with(force=True)


def test_earnapp_proxy_rollback_recreates_main_container_after_sidecar_restart():
    """Rollback must also recreate the process on the restored namespace."""
    client = MagicMock()
    sidecar = MagicMock()
    sidecar.name = "cashpilot-earnapp-node-1-egress"
    sidecar.id = "sidecar-container-id"
    sidecar.labels = {
        orchestrator.LABEL_MANAGED: "true",
        orchestrator.LABEL_SERVICE: "earnapp-node-1",
        "cashpilot.provider": "earnapp",
        "cashpilot.role": "egress-sidecar",
    }
    sidecar.attrs = {"Mounts": [{"Destination": "/etc/sing-box", "RW": True}]}
    sidecar.exec_run.return_value = MagicMock(exit_code=0)
    sidecar.status = "running"
    main = MagicMock()
    main.status = "running"
    main.labels = {
        orchestrator.LABEL_MANAGED: "true",
        orchestrator.LABEL_SERVICE: "earnapp-node-1",
        "cashpilot.provider": "earnapp",
    }
    main.id = "candidate-main-id"
    main.name = "cashpilot-earnapp-node-1"
    main.attrs = {
        "Config": {"Image": "cashpilot/earnapp-ubuntu:asset-test", "Env": [], "Labels": main.labels},
        "HostConfig": {"NetworkMode": "container:sidecar-container-id", "RestartPolicy": {"Name": "always"}},
        "Mounts": [{"Type": "volume", "Name": "earnapp-state", "Destination": "/etc/earnapp", "RW": True}],
    }
    client.containers.get.side_effect = [sidecar, main]
    client.containers.create.return_value = MagicMock(id="rollback-main-id", status="running")

    with patch.object(orchestrator, "_get_client", return_value=client):
        result = orchestrator.finalize_proxy_binding_batch(["earnapp-node-1"], "rotation_1234567890", commit=False)

    assert result["action"] == "rolled_back"
    main.stop.assert_called_once_with(timeout=30)
    main.remove.assert_called_once_with(force=True)


def test_earnapp_failed_proxy_apply_reconnects_main_after_internal_rollback():
    """A failed candidate must not leave the main process on the rolled-back sidecar's old namespace."""
    client = MagicMock()
    sidecar = MagicMock()
    sidecar.name = "cashpilot-earnapp-node-1-egress"
    sidecar.id = "sidecar-container-id"
    sidecar.labels = {
        orchestrator.LABEL_MANAGED: "true",
        orchestrator.LABEL_SERVICE: "earnapp-node-1",
        "cashpilot.provider": "earnapp",
        "cashpilot.role": "egress-sidecar",
    }
    sidecar.attrs = {"Mounts": [{"Destination": "/etc/sing-box", "RW": True}]}
    sidecar.exec_run.side_effect = [
        MagicMock(exit_code=0),
        MagicMock(exit_code=0),
        MagicMock(exit_code=1),
        MagicMock(exit_code=0),
    ]
    sidecar.status = "running"
    main = MagicMock()
    main.status = "running"
    main.labels = {
        orchestrator.LABEL_MANAGED: "true",
        orchestrator.LABEL_SERVICE: "earnapp-node-1",
        "cashpilot.provider": "earnapp",
    }
    main.id = "candidate-main-id"
    main.name = "cashpilot-earnapp-node-1"
    main.attrs = {
        "Config": {"Image": "cashpilot/earnapp-ubuntu:asset-test", "Env": [], "Labels": main.labels},
        "HostConfig": {"NetworkMode": "container:sidecar-container-id", "RestartPolicy": {"Name": "always"}},
        "Mounts": [{"Type": "volume", "Name": "earnapp-state", "Destination": "/etc/earnapp", "RW": True}],
    }
    client.containers.get.side_effect = [sidecar, main, main]
    client.containers.create.side_effect = [
        MagicMock(id="candidate-new-id", status="running"),
        MagicMock(id="rollback-new-id", status="running"),
    ]

    with patch.object(orchestrator, "_get_client", return_value=client):
        try:
            orchestrator.apply_proxy_binding_batch(
                ["earnapp-node-1"],
                {"host": "2.2.2.2", "port": 1080, "protocol": "socks5"},
                "rotation_1234567890",
            )
        except RuntimeError as exc:
            assert "did not acknowledge" in str(exc)
        else:
            raise AssertionError("a failed candidate verification must roll back")

    assert sidecar.restart.call_count == 2
    assert main.stop.call_count == 1
    assert main.remove.call_count == 1
