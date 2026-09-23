import pytest


def test_entrypoint_orders_redsocks_before_dns_and_provider():
    from app.proxy_runtime import render_entrypoint

    script = render_entrypoint(["/usr/bin/provider", "--run"]).decode()

    redsocks = script.index('start_process "redsocks"')
    redsocks_ready = script.index('wait_tcp "127.0.0.1" "$REDSOCKS_PORT"')
    dns = script.index('start_process "dns"')
    dns_ready = script.index('wait_udp_dns "127.0.0.1" "$DNS_PORT"')
    egress = script.index('verify_egress "$EXPECTED_EGRESS_IP"')
    provider = script.index("/usr/bin/provider --run")
    assert redsocks < redsocks_ready < dns < dns_ready < egress < provider
    assert "command -v dig >/dev/null 2>&1" in script
    assert "command -v getent >/dev/null 2>&1" in script


def test_entrypoint_is_fail_closed_for_direct_ipv4_ipv6_and_udp():
    from app.proxy_runtime import render_entrypoint

    script = render_entrypoint(["provider"]).decode()

    assert 'iptables -A CP_PROXY_OUT -d "$PROXY_IP"/32 -p tcp --dport "$PROXY_PORT" -j ACCEPT' in script
    assert "iptables -A CP_PROXY_OUT -j DROP" in script
    assert "ip6tables -A CP_PROXY6_OUT -j DROP" in script
    assert "iptables -A CP_PROXY_OUT -p udp -j DROP" in script
    assert 'iptables -t nat -A CP_PROXY_REDSOCKS -p tcp -j REDIRECT --to-ports "$REDSOCKS_PORT"' in script
    assert "iptables -t nat -A CP_PROXY_DNS -p udp --dport 53 -j REDIRECT" in script
    assert "command -v redsocks >/dev/null 2>&1 || exit 69" in script
    assert "command -v node >/dev/null 2>&1 || exit 69" in script


def test_entrypoint_pins_proxy_ipv4_before_installing_firewall():
    from app.proxy_runtime import render_entrypoint

    script = render_entrypoint(["provider"]).decode()

    resolve = script.index('PROXY_IP=$(getent ahostsv4 "$PROXY_HOST"')
    firewall = script.index("install_firewall\n")
    assert resolve < firewall
    assert 'iptables -A CP_PROXY_OUT -d "$PROXY_IP"/32' in script


def test_entrypoint_watchdog_stops_provider_when_route_process_dies():
    from app.proxy_runtime import render_entrypoint

    script = render_entrypoint(["provider"]).decode()

    assert 'watchdog "$PROVIDER_PID" "$REDSOCKS_PID" "$DNS_PID"' in script
    assert 'kill -TERM "$provider_pid"' in script
    assert "install_firewall ||" in script


def test_entrypoint_has_explicit_route_readiness_and_bounded_restart_contract():
    from app.proxy_runtime import render_entrypoint

    script = render_entrypoint(["provider"]).decode()

    assert 'ROUTE_READY_MARKER="${ROUTE_READY_MARKER:-/run/cashpilot/route-ready}"' in script
    assert 'STARTUP_GRACE_SECONDS="${STARTUP_GRACE_SECONDS:-30}"' in script
    assert 'RESTART_BUDGET="${RESTART_BUDGET:-3}"' in script
    assert 'touch "$ROUTE_READY_MARKER"' in script
    assert 'rm -f "$ROUTE_READY_MARKER"' in script
    assert "record_restart_evidence" in script
    assert "route_blocked" in script


def test_sidecar_guard_stops_provider_when_route_marker_disappears():
    from app.proxy_runtime import render_sidecar_guard_entrypoint

    script = render_sidecar_guard_entrypoint(["provider", "--run"]).decode()

    assert 'ROUTE_READY_MARKER="${ROUTE_READY_MARKER:-/run/cashpilot/route-ready}"' in script
    assert 'STARTUP_GRACE_SECONDS="${STARTUP_GRACE_SECONDS:-30}"' in script
    assert 'kill -TERM "$PROVIDER_PID"' in script
    assert "route_blocked" in script
    assert "record_restart_evidence" in script


def test_entrypoint_rejects_empty_provider_command():
    from app.proxy_runtime import render_entrypoint

    with pytest.raises(ValueError, match="provider command"):
        render_entrypoint([])


def test_rotation_contract_rebuilds_route_in_order():
    from app.proxy_runtime import rotation_steps

    assert rotation_steps() == (
        "stop_provider",
        "remove_route",
        "lease_provider_proxy",
        "install_route",
        "verify_route",
        "start_provider",
        "record_evidence",
    )


def test_route_teardown_removes_proxy_processes_and_firewall_state():
    from app.proxy_runtime import render_route_teardown

    script = render_route_teardown().decode()
    assert 'kill -TERM "$pid"' in script
    assert "CP_PROXY_REDSOCKS" in script
    assert "CP_PROXY_DNS" in script
    assert "CP_PROXY_OUT" in script
    assert "CP_PROXY6_OUT" in script
