from app.provider_lifecycle import decide, decide_instance, decide_lane


def test_provider_lifecycle_dispatcher_is_scheduled_separately():
    import inspect

    from app import main

    assert inspect.iscoroutinefunction(main._run_provider_lifecycle_scheduler)


def test_offline_provider_restarts_without_rotating_proxy():
    assert decide("packetstream", online=False, banned=False, proxy_healthy=True) == "restart"


def test_banned_provider_recreates_and_rotates_when_provider_requires_instance_rotation():
    assert decide("iproyal", online=True, banned=True, proxy_healthy=True) == "recreate"


def test_unhealthy_proxy_rotates_only_for_proxy_runtime():
    assert decide("packetstream", online=True, banned=False, proxy_healthy=False) == "rotate"
    assert decide("mysterium", online=True, banned=False, proxy_healthy=False) == "observe"


def test_earnapp_banned_nodes_use_restart_policy():
    assert decide("earnapp", online=True, banned=True, proxy_healthy=True) == "restart"


def test_hybrid_direct_lane_does_not_rotate_when_proxy_health_is_bad():
    assert decide_lane("earnfm", mode="direct", online=True, banned=False, proxy_healthy=False) == "observe"


def test_hybrid_proxy_lane_rotates_when_proxy_health_is_bad():
    assert decide_lane("earnfm", mode="proxy", online=True, banned=False, proxy_healthy=False) == "rotate"


def test_invalid_lane_fails_closed_to_observe():
    assert decide_lane("earnfm", mode="bogus", online=False, banned=False, proxy_healthy=True) == "observe"


def test_decide_instance_requires_explicit_lane_and_returns_observe_without_signals():
    assert decide_instance({"provider_slug": "earnfm", "mode": "direct"}) == "observe"
    assert (
        decide_instance(
            {
                "provider_slug": "earnfm",
                "mode": "proxy",
                "online": True,
                "banned": False,
                "proxy_healthy": False,
            }
        )
        == "rotate"
    )


def test_decide_instance_uses_provider_and_lane_identity():
    assert (
        decide_instance({"slug": "earnfm", "mode": "direct", "online": False, "banned": False, "proxy_healthy": True})
        == "restart"
    )
