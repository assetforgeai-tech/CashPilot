from app.provider_lifecycle import decide, decide_instance, decide_lane


def test_provider_lifecycle_dispatcher_is_scheduled_separately():
    import inspect

    from app import main

    assert inspect.iscoroutinefunction(main._run_provider_lifecycle_scheduler)


def test_generic_lifecycle_scheduler_restarts_only_confirmed_stopped_lane(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    from app import main

    monkeypatch.setattr(
        main.database,
        "list_workers",
        AsyncMock(
            return_value=[
                {
                    "id": 7,
                    "status": "online",
                    "containers": '[{"name":"earnfm-direct-w7-ipv4-001","status":"exited"}]',
                }
            ]
        ),
    )
    monkeypatch.setattr(
        main.database,
        "list_provider_instances",
        AsyncMock(
            return_value=[
                {
                    "slug": "earnfm",
                    "instance_id": "earnfm-direct-w7-ipv4-001",
                    "worker_id": 7,
                    "mode": "direct",
                }
            ]
        ),
    )
    command = AsyncMock()
    monkeypatch.setattr(main, "_proxy_worker_command", command)
    monkeypatch.setattr(main.database, "record_health_event", AsyncMock())

    asyncio.run(main._run_provider_lifecycle_scheduler())

    command.assert_awaited_once_with(7, "restart", "earnfm-direct-w7-ipv4-001")


def test_generic_lifecycle_scheduler_does_not_guess_missing_container_state(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    from app import main

    monkeypatch.setattr(
        main.database,
        "list_workers",
        AsyncMock(return_value=[{"id": 7, "status": "online", "containers": "[]"}]),
    )
    monkeypatch.setattr(
        main.database,
        "list_provider_instances",
        AsyncMock(
            return_value=[
                {
                    "slug": "earnfm",
                    "instance_id": "earnfm-proxy-w7-ipv4-001",
                    "worker_id": 7,
                    "mode": "proxy",
                }
            ]
        ),
    )
    command = AsyncMock()
    monkeypatch.setattr(main, "_proxy_worker_command", command)

    asyncio.run(main._run_provider_lifecycle_scheduler())

    command.assert_not_awaited()


def test_generic_lifecycle_scheduler_rotates_only_verified_unhealthy_proxy_lane(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    from app import main

    monkeypatch.setattr(
        main.database,
        "list_workers",
        AsyncMock(
            return_value=[
                {
                    "id": 7,
                    "status": "online",
                    "containers": (
                        '[{"name":"earnfm-direct-w7-ipv4-001","status":"running"},'
                        '{"name":"earnfm-proxy-w7-proxy-001","status":"running"}]'
                    ),
                }
            ]
        ),
    )
    monkeypatch.setattr(
        main.database,
        "list_provider_instances",
        AsyncMock(
            return_value=[
                {
                    "slug": "earnfm",
                    "instance_id": "earnfm-direct-w7-ipv4-001",
                    "worker_id": 7,
                    "mode": "direct",
                },
                {
                    "slug": "earnfm",
                    "instance_id": "earnfm-proxy-w7-proxy-001",
                    "worker_id": 7,
                    "mode": "proxy",
                    "proxy_id": 11,
                },
            ]
        ),
    )
    candidate = {"proxy_id": 22, "exit_ip": "203.0.113.22"}
    find_candidate = AsyncMock(return_value=candidate)
    rotate = AsyncMock(return_value=True)
    monkeypatch.setattr(main.database, "get_proxy_endpoint", AsyncMock(return_value={"id": 11, "status": "dead"}))
    monkeypatch.setattr(main.database, "find_available_proxy_for_worker", find_candidate)
    monkeypatch.setattr("app.routers.proxies._rotate_provider_instance_after_ack", rotate)
    monkeypatch.setattr(main.database, "record_health_event", AsyncMock())

    asyncio.run(main._run_provider_lifecycle_scheduler())

    find_candidate.assert_awaited_once_with(7, provider_slug="earnfm")
    rotate.assert_awaited_once_with(7, "earnfm", "earnfm-proxy-w7-proxy-001", candidate)


def test_generic_lifecycle_scheduler_restarts_running_lane_when_usage_stalls(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    from app import main

    monkeypatch.setattr(
        main.database,
        "list_workers",
        AsyncMock(
            return_value=[
                {
                    "id": 7,
                    "status": "online",
                    "containers": '[{"name":"earnfm-proxy-w7-proxy-001","status":"running","usage_stalled":true}]',
                }
            ]
        ),
    )
    monkeypatch.setattr(
        main.database,
        "list_provider_instances",
        AsyncMock(
            return_value=[
                {
                    "slug": "earnfm",
                    "instance_id": "earnfm-proxy-w7-proxy-001",
                    "worker_id": 7,
                    "mode": "proxy",
                    "proxy_healthy": True,
                }
            ]
        ),
    )
    command = AsyncMock()
    monkeypatch.setattr(main, "_proxy_worker_command", command)
    monkeypatch.setattr(main.database, "record_health_event", AsyncMock())

    asyncio.run(main._run_provider_lifecycle_scheduler())

    command.assert_awaited_once_with(7, "restart", "earnfm-proxy-w7-proxy-001")


def test_offline_provider_restarts_without_rotating_proxy():
    assert decide("packetstream", online=False, banned=False, proxy_healthy=True) == "restart"


def test_usage_stalled_restarts_same_lane_without_recreating_identity():
    assert decide("packetstream", online=True, banned=False, proxy_healthy=True, usage_stalled=True) == "restart"
    assert (
        decide_lane("earnfm", mode="direct", online=True, banned=False, proxy_healthy=True, usage_stalled=True)
        == "restart"
    )


def test_unhealthy_proxy_rotation_precedes_usage_restart():
    assert (
        decide_lane("earnfm", mode="proxy", online=True, banned=False, proxy_healthy=False, usage_stalled=True)
        == "rotate"
    )


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


def test_lane_banned_action_uses_provider_policy():
    assert decide_lane("earnapp", mode="proxy", online=True, banned=True, proxy_healthy=True) == "restart"


def test_invalid_lane_fails_closed_to_observe():
    assert decide_lane("earnfm", mode="bogus", online=False, banned=False, proxy_healthy=True) == "observe"


def test_direct_route_failure_blocks_without_proxy_fallback():
    assert (
        decide_lane(
            "earnfm",
            mode="direct",
            online=True,
            banned=False,
            proxy_healthy=True,
            direct_route_healthy=False,
        )
        == "blocked"
    )


def test_provider_auth_or_account_suspension_never_mutates_runtime():
    assert (
        decide_lane(
            "earnfm",
            mode="proxy",
            online=False,
            banned=False,
            proxy_healthy=True,
            provider_auth_healthy=False,
        )
        == "observe"
    )
    assert (
        decide_lane(
            "earnfm",
            mode="proxy",
            online=True,
            banned=False,
            proxy_healthy=True,
            account_suspended=True,
        )
        == "observe"
    )


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
