from app import orchestrator


def test_sidecar_uses_immutable_sing_box_reference():
    assert orchestrator.SING_BOX_IMAGE_PIN == (
        "ghcr.io/sagernet/sing-box@sha256:3c1ee82d450df9b336b6f63b1d272cf86e3835392d99596ef8c35f206a457999"
    )


def test_proxy_route_contract_exposes_fail_closed_watchdog_controls():
    contract = orchestrator.proxy_route_contract()

    assert contract == {
        "route_ready_marker": "/etc/sing-box/.cashpilot-route-ready",
        "route_blocked_marker": "/etc/sing-box/.cashpilot-route-blocked",
        "restart_evidence": "/etc/sing-box/restart-evidence.log",
        "restart_budget": "3",
        "restart_backoff_seconds": "5",
    }
