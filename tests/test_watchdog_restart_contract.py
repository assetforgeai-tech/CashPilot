import pytest


@pytest.mark.parametrize("platform", ["macos", "ios", "ubuntu"])
def test_earnapp_watchdog_has_route_marker_and_restart_budget(platform):
    from app import earnapp_runtime

    script = earnapp_runtime.proxy_entrypoint_script(platform).decode()

    assert 'ROUTE_READY_MARKER="${ROUTE_READY_MARKER:-/run/cashpilot/route-ready}"' in script
    assert 'RESTART_BUDGET="${RESTART_BUDGET:-3}"' in script
    assert 'touch "$ROUTE_READY_MARKER"' in script
    assert 'rm -f "$ROUTE_READY_MARKER"' in script
    assert "record_restart_evidence" in script
    assert "route_blocked" in script


def test_sidecar_provider_guard_waits_for_route_then_fails_closed():
    from app.proxy_runtime import render_sidecar_guard_entrypoint

    script = render_sidecar_guard_entrypoint(["/usr/local/bin/provider"]).decode()

    assert 'for _ in $(seq 1 "$STARTUP_GRACE_SECONDS")' in script
    assert "route_is_ready || { route_blocked startup-grace-expired; exit 70; }" in script
    assert 'kill -TERM "$PROVIDER_PID"' in script
    assert "exit 75" in script
