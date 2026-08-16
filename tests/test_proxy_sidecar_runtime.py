from __future__ import annotations

from unittest.mock import MagicMock, patch

from app import orchestrator


def test_proxy_instance_runs_provider_inside_singbox_sidecar_namespace():
    client = MagicMock()
    client.containers.get.side_effect = [orchestrator.NotFound("nope"), orchestrator.NotFound("nope")]
    sidecar = MagicMock(short_id="side", id="sidecar-id", name="cashpilot-bitping-proxy-egress")
    provider = MagicMock(short_id="provider", id="provider-id")
    client.containers.run.side_effect = [sidecar, provider]

    with patch.object(orchestrator, "_get_client", return_value=client):
        container_id = orchestrator.deploy_raw(
            slug="bitping-proxy",
            image="bitping/bitpingd:latest",
            labels={"cashpilot.provider": "bitping", "cashpilot.instance_mode": "proxy"},
            proxy={"host": "1.2.3.4", "port": 1080, "protocol": "socks5"},
        )

    assert container_id == "provider-id"
    sidecar_call, provider_call = client.containers.run.call_args_list
    assert sidecar_call.kwargs["name"] == "cashpilot-bitping-proxy-egress"
    assert sidecar_call.kwargs["image"] == "ghcr.io/sagernet/sing-box:latest"
    assert sidecar_call.kwargs["environment"]["ENABLE_DEPRECATED_LEGACY_DNS_SERVERS"] == "true"
    assert sidecar_call.kwargs["cap_add"] == ["NET_ADMIN"]
    assert "/dev/net/tun:/dev/net/tun" in sidecar_call.kwargs["devices"]
    assert provider_call.kwargs["network_mode"] == "container:cashpilot-bitping-proxy-egress"
    assert provider_call.kwargs["name"] == "cashpilot-bitping-proxy"
    assert provider_call.kwargs["labels"]["cashpilot.provider"] == "bitping"
    assert provider_call.kwargs["labels"]["cashpilot.instance_mode"] == "proxy"

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
