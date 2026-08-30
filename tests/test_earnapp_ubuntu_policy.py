from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import (
    database,
    earnapp_accounts,
    earnapp_canary,
    earnapp_deploy,
    earnapp_recovery,
    earnapp_runtime,
    main,
    provider_runtime,
    worker_api,
)


def _request(path: str) -> Request:
    return Request({"type": "http", "method": "POST", "path": path, "headers": []})


def test_earnapp_policy_allows_only_official_ubuntu_lxd_runtime():
    policy = provider_runtime.get("earnapp")

    assert policy is not None
    assert policy.deployment_allowed is True
    assert policy.deployment_policy == "platform_restricted"
    assert policy.allowed_platforms == ("ubuntu",)
    assert provider_runtime.platform_deployment_allowed("earnapp", "ubuntu", "lxd") is True
    assert provider_runtime.platform_deployment_allowed("earnapp", "macos", "docker") is False
    assert provider_runtime.platform_deployment_allowed("earnapp", "ios", "docker") is False
    assert earnapp_runtime.runtime_deployment_allowed("ubuntu", "lxd") is True
    assert earnapp_runtime.runtime_deployment_allowed("macos", "docker") is False


def test_earnapp_generic_and_apple_deploy_paths_stay_blocked():
    assert provider_runtime.deployment_block("earnapp", {"provider_slug": "earnapp"}) is not None
    assert (
        provider_runtime.deployment_block(
            "earnapp-ios-canary",
            {"provider_slug": "earnapp", "platform": "ios", "runtime_backend": "docker"},
        )
        is not None
    )
    # The generic route is blocked even when a caller supplies Ubuntu/LXD
    # metadata; only the dedicated endpoint may use that contract.
    assert (
        provider_runtime.deployment_block(
            "earnapp-ubuntu-canary",
            {"provider_slug": "earnapp", "platform": "ubuntu", "runtime_backend": "lxd"},
        )
        is not None
    )


def test_earnapp_mutation_policy_is_platform_scoped():
    assert (
        provider_runtime.mutation_block(
            "earnapp-ubuntu-canary",
            {"provider_slug": "earnapp", "platform": "ubuntu", "runtime_backend": "lxd"},
        )
        is None
    )
    assert (
        provider_runtime.mutation_block(
            "earnapp-ios-canary",
            {"provider_slug": "earnapp", "platform": "ios", "runtime_backend": "docker"},
        )
        is not None
    )
    assert provider_runtime.mutation_block("earnapp") is not None


def test_catalog_exposes_the_platform_restriction_without_hiding_ubuntu():
    runtime = provider_runtime.catalog_runtime("earnapp")

    assert runtime["deployment_allowed"] is True
    assert runtime["deployment_policy"] == "platform_restricted"
    assert runtime["allowed_platforms"] == ["ubuntu"]
    assert runtime["blocked_platforms"] == ["macos", "ios"]


def _ubuntu_spec() -> worker_api.EarnAppLxdDeploySpec:
    device_id = "sdk-node-" + "1" * 32
    return worker_api.EarnAppLxdDeploySpec(
        account_id=7,
        generation=3,
        device_id=device_id,
        identity={
            "platform": "ubuntu",
            "machine_id": "2" * 32,
            "device_id": device_id,
            "hostname": "earnapp-ubuntu-policy",
            "arch": "amd64",
        },
        proxy_id=12,
        proxy={
            "proxy_id": 12,
            "host": "proxy.example",
            "port": 1080,
            "protocol": "socks5",
            "exit_ip": "203.0.113.12",
            "country_code": "US",
            "ip_type": "residential",
        },
    )


@pytest.mark.asyncio
async def test_worker_accepts_the_dedicated_ubuntu_lxd_deploy_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    deploy = Mock(
        return_value={
            "instance_id": "cashpilot-earnapp-ubuntu-policy",
            "running": True,
            "online": False,
            "runtime_backend": "lxd",
        }
    )

    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(worker_api.earnapp_lxd_runtime, "deploy_node", deploy),
    ):
        result = await worker_api.api_deploy_earnapp_lxd_node(
            _request("/api/earnapp/nodes/earnapp-ubuntu-policy/deploy"),
            "earnapp-ubuntu-policy",
            _ubuntu_spec(),
        )

    assert result["status"] == "deployed"
    deploy.assert_called_once()


@pytest.mark.asyncio
async def test_auto_deploy_lane_dispatches_only_ubuntu_lxd(monkeypatch):
    deploy = AsyncMock(
        return_value={
            "deployed": ["earnapp-proxy-w3-ipv4-001"],
            "verified": [],
            "skipped": [],
            "pending": [],
            "failed": [],
        }
    )
    monkeypatch.setattr(
        main, "_worker_public_ip_slots", AsyncMock(return_value=[{"slot_id": "ipv4-001", "route_ready": True}])
    )
    monkeypatch.setattr(earnapp_deploy, "deploy_worker_nodes_sequentially", deploy)

    result = await main._deploy_earnapp_nodes(3, config={"earnapp_lxd_cpu": "2", "earnapp_lxd_memory_mib": "2048"})

    assert result["deployed"] == ["earnapp-proxy-w3-ipv4-001"]
    assert deploy.await_args.kwargs["required_platform"] == "ubuntu"
    assert deploy.await_args.kwargs["lxd_settings"] == {"cpu": 2, "memory_mib": 2048}


@pytest.mark.asyncio
async def test_recovery_sweep_is_scoped_to_ubuntu(monkeypatch):
    sweep = AsyncMock(return_value={"held": [], "released": []})
    monkeypatch.setattr(database, "sweep_stale_earnapp_nodes", sweep)

    await earnapp_recovery.sweep_stale_nodes()

    assert sweep.await_args.kwargs["platforms"] == ("ubuntu",)


@pytest.mark.asyncio
async def test_replacement_ticket_blocks_apple_but_allows_ubuntu(monkeypatch):
    create = AsyncMock(return_value="created")
    monkeypatch.setattr(database, "create_earnapp_replacement_ticket", create)
    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(
            return_value={"logical_node_id": "earnapp-ios", "platform": "ios", "state": "RECOVERABLE", "generation": 2}
        ),
    )

    with pytest.raises(earnapp_recovery.RecoveryClaimDenied, match="disabled"):
        await earnapp_recovery.issue_replacement_ticket("earnapp-ios", 9)
    create.assert_not_awaited()

    database.get_earnapp_logical_node.return_value = {
        "logical_node_id": "earnapp-ubuntu",
        "platform": "ubuntu",
        "state": "RECOVERABLE",
        "generation": 2,
    }
    token = await earnapp_recovery.issue_replacement_ticket("earnapp-ubuntu", 9)

    assert token
    create.assert_awaited_once()


@pytest.mark.asyncio
async def test_account_cleanup_preflights_every_binding_by_platform(monkeypatch):
    cleanup = AsyncMock(return_value=True)
    monkeypatch.setattr(
        database,
        "list_earnapp_runtime_bindings",
        AsyncMock(
            return_value=[
                {
                    "logical_node_id": "earnapp-ubuntu",
                    "instance_id": "earnapp-ubuntu",
                    "platform": "ubuntu",
                    "runtime_backend": "lxd",
                },
                {
                    "logical_node_id": "earnapp-ios",
                    "instance_id": "earnapp-ios",
                    "platform": "ios",
                    "runtime_backend": "docker",
                },
            ]
        ),
    )

    with pytest.raises(earnapp_accounts.AccountDeletionDenied, match="iOS"):
        await earnapp_accounts._cleanup_account_runtimes(7, cleanup)

    # Fail before partially removing the allowed Ubuntu runtime.
    cleanup.assert_not_awaited()


@pytest.mark.asyncio
async def test_server_canary_route_allows_ubuntu_but_blocks_apple_platforms(monkeypatch):
    ubuntu_deploy = AsyncMock(
        return_value={
            "status": "deployed",
            "logical_node_id": "earnapp-ubuntu-policy",
            "worker_id": 3,
            "device_id": "sdk-node-" + "1" * 32,
            "generation": 1,
        }
    )
    verify = AsyncMock(
        return_value={
            "status": "workload_verified",
            "workload_state": "workload_verified",
            "online": True,
        }
    )
    monkeypatch.setattr(main, "_resolve_worker_id", AsyncMock(return_value=3))
    monkeypatch.setattr(earnapp_canary, "deploy_platform_canary", ubuntu_deploy)
    monkeypatch.setattr(earnapp_canary, "verify_canary", verify)
    monkeypatch.setattr(main, "_persist_earnapp_canary_verification", AsyncMock(side_effect=lambda _node, value: value))
    monkeypatch.setattr(main.database, "get_config", AsyncMock(return_value={}))
    monkeypatch.setattr(main.database, "record_health_event", AsyncMock())

    result = await main.api_deploy_earnapp_canary(
        _request("/api/admin/earnapp/canary/deploy"),
        main.EarnAppCanaryDeployRequest(
            logical_node_id="earnapp-ubuntu-policy",
            worker_id=3,
            platform="ubuntu",
        ),
        _auth={"r": "owner"},
    )

    assert result["deployment"]["logical_node_id"] == "earnapp-ubuntu-policy"
    ubuntu_deploy.assert_awaited_once()

    for platform in ("macos", "ios"):
        with pytest.raises(HTTPException) as exc:
            await main.api_deploy_earnapp_canary(
                _request("/api/admin/earnapp/canary/deploy"),
                main.EarnAppCanaryDeployRequest(
                    logical_node_id=f"earnapp-{platform}-policy",
                    worker_id=3,
                    platform=platform,
                ),
                _auth={"r": "owner"},
            )
        assert exc.value.status_code == 409


def _authoritative_node(
    *,
    platform: str = "ubuntu",
    assigned_worker_id: int = 3,
    state: str = "ACTIVE",
    generation: int = 4,
    device_id: str = "sdk-node-" + "4" * 32,
) -> dict[str, object]:
    return {
        "logical_node_id": "earnapp-ubuntu-policy",
        "platform": platform,
        "assigned_worker_id": assigned_worker_id,
        "state": state,
        "generation": generation,
        "device_id": device_id,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "expected_calls"),
    [
        ("stop", [("POST", "/api/earnapp/nodes/earnapp-ubuntu-policy/suspend")]),
        ("start", [("POST", "/api/earnapp/nodes/earnapp-ubuntu-policy/resume")]),
        (
            "restart",
            [
                ("POST", "/api/earnapp/nodes/earnapp-ubuntu-policy/suspend"),
                ("POST", "/api/earnapp/nodes/earnapp-ubuntu-policy/resume"),
            ],
        ),
        ("remove", [("DELETE", "/api/earnapp/nodes/earnapp-ubuntu-policy")]),
    ],
)
async def test_server_lifecycle_dispatches_authoritative_ubuntu_lxd_node(monkeypatch, action, expected_calls):
    device_id = "sdk-node-" + "4" * 32
    proxy = AsyncMock(return_value={"status": "ok"})
    monkeypatch.setattr(main, "_require_writer", lambda _request: {"r": "writer"})
    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(return_value=_authoritative_node(device_id=device_id)),
    )
    monkeypatch.setattr(main, "_proxy_to_worker", proxy)
    monkeypatch.setattr(database, "record_health_event", AsyncMock())
    monkeypatch.setattr(database, "remove_provider_instance", AsyncMock())
    monkeypatch.setattr(database, "finalize_earnapp_node_removal", AsyncMock(return_value=True))
    monkeypatch.setattr(main.metrics, "record_container_lifecycle", lambda *_args, **_kwargs: None)

    if action == "stop":
        await main._svc_stop(_request("/api/stop/earnapp-ubuntu-policy"), "earnapp-ubuntu-policy", 3)
    elif action == "start":
        await main.api_service_start(
            _request("/api/services/earnapp-ubuntu-policy/start"),
            "earnapp-ubuntu-policy",
            3,
        )
    elif action == "restart":
        await main._svc_restart(_request("/api/restart/earnapp-ubuntu-policy"), "earnapp-ubuntu-policy", 3)
    else:
        await main._svc_remove(
            _request("/api/remove/earnapp-ubuntu-policy"),
            "earnapp-ubuntu-policy",
            3,
            False,
        )

    assert [(call.args[1], call.args[2]) for call in proxy.await_args_list] == expected_calls
    for call in proxy.await_args_list:
        assert call.kwargs["json"] == {"generation": 4, "device_id": device_id}


@pytest.mark.asyncio
async def test_server_remove_releases_only_the_removed_ubuntu_node(monkeypatch):
    node_id = "earnapp-ubuntu-policy"
    other_node_id = "earnapp-ubuntu-other"
    worker_remove = AsyncMock(return_value={"status": "removed", "logical_node_id": node_id})
    finalize = AsyncMock(return_value=True)
    remove_instance = AsyncMock()

    monkeypatch.setattr(main, "_require_writer", lambda _request: {"r": "writer"})
    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(return_value=_authoritative_node()),
    )
    monkeypatch.setattr(main, "_proxy_to_worker", worker_remove)
    monkeypatch.setattr(database, "finalize_earnapp_node_removal", finalize)
    monkeypatch.setattr(database, "remove_provider_instance", remove_instance)
    monkeypatch.setattr(database, "record_health_event", AsyncMock())
    monkeypatch.setattr(main.metrics, "record_container_lifecycle", lambda *_args, **_kwargs: None)

    result = await main._svc_remove(
        _request(f"/api/remove/{node_id}"),
        node_id,
        3,
        False,
    )

    assert result["status"] == "removed"
    worker_remove.assert_awaited_once()
    finalize.assert_awaited_once_with(
        node_id,
        3,
        generation=4,
        device_id="sdk-node-" + "4" * 32,
        reason="EARNAPP_NODE_REMOVED",
    )
    remove_instance.assert_awaited_once_with(node_id)
    assert other_node_id not in repr(finalize.await_args_list)


@pytest.mark.asyncio
async def test_server_remove_keeps_bookkeeping_when_worker_remove_fails(monkeypatch):
    finalize = AsyncMock()
    remove_instance = AsyncMock()

    monkeypatch.setattr(main, "_require_writer", lambda _request: {"r": "writer"})
    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(return_value=_authoritative_node()),
    )
    monkeypatch.setattr(
        main, "_proxy_to_worker", AsyncMock(side_effect=HTTPException(status_code=503, detail="worker failed"))
    )
    monkeypatch.setattr(database, "finalize_earnapp_node_removal", finalize)
    monkeypatch.setattr(database, "remove_provider_instance", remove_instance)

    with pytest.raises(HTTPException) as exc:
        await main._svc_remove(
            _request("/api/remove/earnapp-ubuntu-policy"),
            "earnapp-ubuntu-policy",
            3,
            False,
        )

    assert exc.value.status_code == 503
    finalize.assert_not_awaited()
    remove_instance.assert_not_awaited()


@pytest.mark.asyncio
async def test_database_finalize_ubuntu_remove_releases_exact_lease_and_preserves_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_DIR", tmp_path)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "cashpilot.db")
    await database.init_db()
    worker_id = await database.upsert_worker("earnapp-worker", "EarnApp worker", "http://worker")
    account_id = await database.upsert_earnapp_account(
        profile_key="profile-ubuntu-remove",
        account_name="ubuntu-remove@example.com",
        email="ubuntu-remove@example.com",
        auth_method="google",
        credentials={"cookies": {"oauth-refresh-token": "oauth", "xsrf-token": "xsrf"}},
        credential_keys=["oauth-refresh-token", "xsrf-token"],
        token_expires_at=None,
        cookie_expires_at=None,
    )
    other_account_id = await database.upsert_earnapp_account(
        profile_key="profile-ubuntu-other",
        account_name="ubuntu-other@example.com",
        email="ubuntu-other@example.com",
        auth_method="google",
        credentials={"cookies": {"oauth-refresh-token": "oauth-2", "xsrf-token": "xsrf-2"}},
        credential_keys=["oauth-refresh-token", "xsrf-token"],
        token_expires_at=None,
        cookie_expires_at=None,
    )
    assert account_id != other_account_id

    db = await database._get_db()
    try:
        await db.execute(
            """
            INSERT INTO proxy_endpoints
                (endpoint, host, port, protocol, status, exit_ip, ip_type, country_code)
            VALUES
                ('proxy-a.example:1080', 'proxy-a.example', 1080, 'socks5', 'alive', '203.0.113.10', 'residential', 'US'),
                ('proxy-b.example:1080', 'proxy-b.example', 1080, 'socks5', 'alive', '203.0.113.11', 'residential', 'US')
            """
        )
        rows = await (await db.execute("SELECT id FROM proxy_endpoints ORDER BY id")).fetchall()
        proxy_id, other_proxy_id = (int(rows[0]["id"]), int(rows[1]["id"]))
        device_id = "sdk-node-" + "4" * 32
        other_device_id = "sdk-node-" + "5" * 32
        await db.execute(
            """
            INSERT INTO earnapp_logical_nodes
                (logical_node_id, account_id, platform, state, generation, assigned_worker_id,
                 last_worker_id, device_id, current_proxy_id, preferred_proxy_id)
            VALUES (?, ?, 'ubuntu', 'ACTIVE', 4, ?, ?, ?, ?, ?)
            """,
            ("earnapp-ubuntu-policy", account_id, worker_id, worker_id, device_id, proxy_id, proxy_id),
        )
        await db.execute(
            """
            INSERT INTO earnapp_logical_nodes
                (logical_node_id, account_id, platform, state, generation, assigned_worker_id,
                 last_worker_id, device_id, current_proxy_id, preferred_proxy_id)
            VALUES (?, ?, 'ubuntu', 'ACTIVE', 7, ?, ?, ?, ?, ?)
            """,
            (
                "earnapp-ubuntu-other",
                other_account_id,
                worker_id,
                worker_id,
                other_device_id,
                other_proxy_id,
                other_proxy_id,
            ),
        )
        await db.execute(
            """
            INSERT INTO provider_proxy_leases
                (provider_slug, worker_id, instance_id, proxy_id, exit_ip)
            VALUES
                ('earnapp', ?, 'earnapp-ubuntu-policy', ?, '203.0.113.10'),
                ('earnapp', ?, 'earnapp-ubuntu-other', ?, '203.0.113.11')
            """,
            (worker_id, proxy_id, worker_id, other_proxy_id),
        )
        await db.commit()
    finally:
        await db.close()

    assert (
        await database.finalize_earnapp_node_removal(
            "earnapp-ubuntu-policy",
            worker_id,
            generation=4,
            device_id=device_id,
            reason="EARNAPP_NODE_REMOVED",
        )
        is True
    )

    removed = await database.get_earnapp_logical_node("earnapp-ubuntu-policy")
    other = await database.get_earnapp_logical_node("earnapp-ubuntu-other")
    leases = await database.list_provider_proxy_leases(provider_slug="earnapp")
    removed_lease = next(row for row in leases if row["instance_id"] == "earnapp-ubuntu-policy")
    other_lease = next(row for row in leases if row["instance_id"] == "earnapp-ubuntu-other")

    assert removed["state"] == "PLANNED"
    assert removed["assigned_worker_id"] is None
    assert removed["last_worker_id"] == worker_id
    assert removed["current_proxy_id"] is None
    assert removed["preferred_proxy_id"] == proxy_id
    assert removed["device_id"] == device_id
    assert removed["generation"] == 4
    assert removed_lease["released_at"] is not None
    assert removed_lease["release_reason"] == "EARNAPP_NODE_REMOVED"
    assert other["state"] == "ACTIVE"
    assert other["assigned_worker_id"] == worker_id
    assert other["current_proxy_id"] == other_proxy_id
    assert other_lease["released_at"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["macos", "ios", "unknown"])
async def test_server_lifecycle_blocks_non_ubuntu_nodes_from_authoritative_db(monkeypatch, platform):
    proxy = AsyncMock()
    monkeypatch.setattr(main, "_require_writer", lambda _request: {"r": "writer"})
    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(return_value=_authoritative_node(platform=platform)),
    )
    monkeypatch.setattr(main, "_proxy_to_worker", proxy)

    with pytest.raises(HTTPException) as exc:
        await main._svc_stop(_request("/api/stop/earnapp-ubuntu-policy"), "earnapp-ubuntu-policy", 3)

    assert exc.value.status_code == 409
    proxy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "node",
    [
        None,
        _authoritative_node(assigned_worker_id=9),
        _authoritative_node(state="PLANNED"),
        _authoritative_node(state="RECOVERABLE"),
        _authoritative_node(state="RETIRED"),
        _authoritative_node(generation=0),
        _authoritative_node(device_id=""),
    ],
)
async def test_server_lifecycle_fails_closed_on_invalid_authoritative_state(monkeypatch, node):
    proxy = AsyncMock()
    monkeypatch.setattr(main, "_require_writer", lambda _request: {"r": "writer"})
    monkeypatch.setattr(database, "get_earnapp_logical_node", AsyncMock(return_value=node))
    monkeypatch.setattr(main, "_proxy_to_worker", proxy)

    with pytest.raises(HTTPException) as exc:
        await main._svc_stop(_request("/api/stop/earnapp-ubuntu-policy"), "earnapp-ubuntu-policy", 3)

    assert exc.value.status_code == 409
    proxy.assert_not_awaited()


@pytest.mark.asyncio
async def test_raw_worker_lifecycle_rejects_unknown_earnapp_action_before_proxy(monkeypatch):
    proxy = AsyncMock()
    lookup = AsyncMock(return_value=_authoritative_node())
    monkeypatch.setattr(main, "_require_writer", lambda _request: {"r": "writer"})
    monkeypatch.setattr(database, "get_earnapp_logical_node", lookup)
    monkeypatch.setattr(main, "_proxy_to_worker", proxy)

    with pytest.raises(HTTPException) as exc:
        await main.api_worker_command(
            _request("/api/workers/3/command"),
            3,
            main.WorkerCommand(command="snapshot", slug="earnapp-ubuntu-policy"),
        )

    assert exc.value.status_code == 400
    lookup.assert_not_awaited()
    proxy.assert_not_awaited()


@pytest.mark.asyncio
async def test_server_lifecycle_keeps_bare_earnapp_slug_blocked(monkeypatch):
    lookup = AsyncMock()
    proxy = AsyncMock()
    monkeypatch.setattr(main, "_require_writer", lambda _request: {"r": "writer"})
    monkeypatch.setattr(database, "get_earnapp_logical_node", lookup)
    monkeypatch.setattr(main, "_proxy_to_worker", proxy)

    with pytest.raises(HTTPException) as exc:
        await main._svc_stop(_request("/api/stop/earnapp"), "earnapp", 3)

    assert exc.value.status_code == 409
    lookup.assert_not_awaited()
    proxy.assert_not_awaited()


@pytest.mark.asyncio
async def test_raw_worker_lifecycle_dispatches_ubuntu_lxd_without_trusting_body_spec(monkeypatch):
    device_id = "sdk-node-" + "5" * 32
    proxy = AsyncMock(return_value={"status": "resumed"})
    monkeypatch.setattr(main, "_require_writer", lambda _request: {"r": "writer"})
    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(return_value=_authoritative_node(generation=5, device_id=device_id)),
    )
    monkeypatch.setattr(main, "_proxy_to_worker", proxy)
    monkeypatch.setattr(database, "record_health_event", AsyncMock())
    monkeypatch.setattr(main.metrics, "record_container_lifecycle", lambda *_args, **_kwargs: None)

    await main.api_worker_command(
        _request("/api/workers/3/command"),
        3,
        main.WorkerCommand(
            command="start",
            slug="earnapp-ubuntu-policy",
            spec={"platform": "macos", "runtime_backend": "docker", "generation": 999},
        ),
    )

    proxy.assert_awaited_once_with(
        3,
        "POST",
        "/api/earnapp/nodes/earnapp-ubuntu-policy/resume",
        json={"generation": 5, "device_id": device_id},
        timeout=180,
    )


@pytest.mark.asyncio
async def test_worker_generic_docker_cleanup_blocks_before_state_lookup(monkeypatch):
    monkeypatch.setattr(worker_api, "_verify_api_key", lambda _request: None)
    monkeypatch.setattr(
        worker_api,
        "_earnapp_node_state",
        lambda _node: (_ for _ in ()).throw(AssertionError("generic cleanup must not read EarnApp state")),
    )

    with pytest.raises(HTTPException) as exc:
        await worker_api.api_remove_earnapp_docker_node(
            _request("/api/earnapp/docker-nodes/earnapp-legacy-node"),
            "earnapp-legacy-node",
            worker_api.EarnAppDockerNodeCasSpec(generation=1, device_id="sdk-mac-" + "1" * 32),
        )

    assert exc.value.status_code == 409
