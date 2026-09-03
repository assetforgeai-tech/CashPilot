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
    earnapp_identity,
    earnapp_policy,
    earnapp_recovery,
    earnapp_runtime,
    main,
    provider_runtime,
    worker_api,
)
from app.routers import proxies as proxy_routes


def _request(path: str) -> Request:
    return Request({"type": "http", "method": "POST", "path": path, "headers": []})


def test_earnapp_policy_allows_geo_platform_lanes():
    policy = provider_runtime.get("earnapp")

    assert policy is not None
    assert policy.deployment_allowed is True
    assert policy.deployment_policy == "platform_restricted"
    assert policy.allowed_platforms == ("macos", "ios", "ubuntu")
    assert provider_runtime.platform_deployment_allowed("earnapp", "ubuntu", "lxd") is False
    assert provider_runtime.platform_deployment_allowed("earnapp", "ubuntu", "docker") is True
    assert provider_runtime.platform_deployment_allowed("earnapp", "macos", "docker") is True
    assert provider_runtime.platform_deployment_allowed("earnapp", "ios", "docker") is True
    assert earnapp_runtime.runtime_deployment_allowed("ubuntu", "lxd") is False
    assert earnapp_runtime.runtime_deployment_allowed("ubuntu", "docker") is True
    assert earnapp_runtime.runtime_deployment_allowed("macos", "docker") is True


def test_earnapp_generic_route_stays_blocked_but_apple_lane_is_allowed():
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
        is not None
    )
    assert (
        provider_runtime.mutation_block(
            "earnapp-ios-canary",
            {"provider_slug": "earnapp", "platform": "ios", "runtime_backend": "docker"},
        )
        is None
    )
    assert provider_runtime.mutation_block("earnapp") is not None


def test_catalog_exposes_the_platform_restriction_without_hiding_ubuntu():
    runtime = provider_runtime.catalog_runtime("earnapp")

    assert runtime["deployment_allowed"] is True
    assert runtime["deployment_policy"] == "platform_restricted"
    assert runtime["allowed_platforms"] == ["macos", "ios", "ubuntu"]
    assert runtime["blocked_platforms"] == []


def _ubuntu_spec() -> worker_api.EarnAppLxdDeploySpec:
    device_id = "sdk-node-" + "1" * 32
    identity = earnapp_identity.generate_identity("earnapp-ubuntu-policy", "ubuntu")
    identity["device_id"] = device_id
    return worker_api.EarnAppLxdDeploySpec(
        account_id=7,
        generation=3,
        device_id=device_id,
        identity=identity,
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
async def test_worker_rejects_retired_ubuntu_lxd_deploy_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    deploy = Mock(
        return_value={
            "instance_id": "cashpilot-earnapp-ubuntu-policy",
            "running": True,
            "online": False,
            "runtime_backend": "docker",
        }
    )

    with patch.object(worker_api, "_verify_api_key"), pytest.raises(HTTPException) as exc:
        await worker_api.api_deploy_earnapp_lxd_node(
            _request("/api/earnapp/nodes/earnapp-ubuntu-policy/deploy"),
            "earnapp-ubuntu-policy",
            _ubuntu_spec(),
        )
    assert exc.value.status_code == 409
    deploy.assert_not_called()


@pytest.mark.asyncio
async def test_auto_deploy_lane_dispatches_geo_platform_routes(monkeypatch):
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
    assert deploy.await_args.kwargs["lxd_settings"] == {"cpu": 2, "memory_mib": 2048}


@pytest.mark.asyncio
async def test_recovery_sweep_covers_all_earnapp_platforms(monkeypatch):
    sweep = AsyncMock(return_value={"held": [], "released": []})
    monkeypatch.setattr(database, "sweep_stale_earnapp_nodes", sweep)

    await earnapp_recovery.sweep_stale_nodes()

    assert sweep.await_args.kwargs["platforms"] == ("macos", "ios", "ubuntu")


@pytest.mark.asyncio
async def test_replacement_ticket_allows_apple_and_ubuntu(monkeypatch):
    create = AsyncMock(return_value="created")
    monkeypatch.setattr(database, "create_earnapp_replacement_ticket", create)
    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(
            return_value={"logical_node_id": "earnapp-ios", "platform": "ios", "state": "RECOVERABLE", "generation": 2}
        ),
    )

    token = await earnapp_recovery.issue_replacement_ticket("earnapp-ios", 9)
    assert token
    create.assert_awaited_once()

    database.get_earnapp_logical_node.return_value = {
        "logical_node_id": "earnapp-ubuntu",
        "platform": "ubuntu",
        "state": "RECOVERABLE",
        "generation": 2,
    }
    token = await earnapp_recovery.issue_replacement_ticket("earnapp-ubuntu", 9)

    assert token
    assert create.await_count == 2


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
                    "runtime_backend": "docker",
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

    await earnapp_accounts._cleanup_account_runtimes(7, cleanup)
    assert cleanup.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("node_id", sorted(earnapp_policy.PROTECTED_LOGICAL_NODE_IDS))
async def test_account_cleanup_refuses_every_protected_live_node(node_id, monkeypatch):
    cleanup = AsyncMock(return_value=True)
    monkeypatch.setattr(
        database,
        "list_earnapp_runtime_bindings",
        AsyncMock(
            return_value=[
                {
                    "logical_node_id": node_id,
                    "instance_id": node_id,
                    "platform": "ubuntu",
                    "runtime_backend": "docker",
                }
            ]
        ),
    )

    with pytest.raises(earnapp_accounts.AccountDeletionDenied, match="protected"):
        await earnapp_accounts._cleanup_account_runtimes(7, cleanup)

    cleanup.assert_not_awaited()


@pytest.mark.asyncio
async def test_account_cleanup_uses_logical_node_id_when_runtime_instance_id_differs(monkeypatch):
    node_id = "earnapp-ubuntu-canary-test-sing-4"
    cleanup = AsyncMock(return_value=True)
    monkeypatch.setattr(
        database,
        "list_earnapp_runtime_bindings",
        AsyncMock(
            return_value=[
                {
                    "logical_node_id": node_id,
                    "instance_id": "cashpilot-earnapp-ubuntu-canary-test-sing-4",
                    "platform": "ubuntu",
                    "runtime_backend": "docker",
                }
            ]
        ),
    )

    with pytest.raises(earnapp_accounts.AccountDeletionDenied, match="protected"):
        await earnapp_accounts._cleanup_account_runtimes(7, cleanup)

    cleanup.assert_not_awaited()


@pytest.mark.parametrize("node_id", sorted(earnapp_policy.PROTECTED_LOGICAL_NODE_IDS))
def test_worker_mutation_policy_refuses_every_protected_live_node(node_id):
    with pytest.raises(HTTPException, match="Protected EarnApp"):
        worker_api._reject_earnapp_runtime_mutation(
            node_id,
            platform="ubuntu",
            runtime_backend="lxd",
        )


@pytest.mark.asyncio
async def test_worker_deploy_refuses_protected_ubuntu_node_before_host_mutation():
    deploy = Mock(return_value={"running": True})
    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(worker_api.earnapp_lxd_runtime, "deploy_node", deploy),
        pytest.raises(HTTPException, match="Protected EarnApp"),
    ):
        await worker_api.api_deploy_earnapp_lxd_node(
            _request("/api/earnapp/nodes/earnapp-ubuntu-canary-test-sing-4/deploy"),
            "earnapp-ubuntu-canary-test-sing-4",
            _ubuntu_spec(),
        )

    deploy.assert_not_called()


@pytest.mark.asyncio
async def test_server_lifecycle_refuses_protected_ubuntu_node_before_authority_lookup(monkeypatch):
    lookup = AsyncMock(
        return_value={
            "logical_node_id": "earnapp-ubuntu-canary-test-sing-4",
            "platform": "ubuntu",
            "assigned_worker_id": 3,
            "generation": 1,
            "device_id": "sdk-node-" + "4" * 32,
            "state": "ACTIVE",
        }
    )
    monkeypatch.setattr(database, "get_earnapp_logical_node", lookup)

    with pytest.raises(HTTPException, match="Protected EarnApp"):
        await main._resolve_earnapp_ubuntu_lifecycle("earnapp-ubuntu-canary-test-sing-4", 3)

    lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_server_refuses_deleting_worker_that_hosts_protected_earnapp_node(monkeypatch):
    delete = AsyncMock()
    monkeypatch.setattr(main, "_require_owner", lambda _request: {"r": "owner"})
    monkeypatch.setattr(database, "get_worker", AsyncMock(return_value={"id": 3}))
    monkeypatch.setattr(
        database,
        "list_earnapp_logical_nodes",
        AsyncMock(
            return_value=[
                {
                    "logical_node_id": "earnapp-ubuntu-canary-test-sing-5",
                    "assigned_worker_id": 3,
                    "state": "ACTIVE",
                }
            ]
        ),
    )
    monkeypatch.setattr(database, "delete_worker", delete)

    with pytest.raises(HTTPException, match="protected EarnApp"):
        await main.api_delete_worker(_request("/api/workers/3"), 3)

    delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_server_refuses_deleting_worker_when_protected_node_is_only_last_worker(monkeypatch):
    """A recovery node keeps its former worker in last_worker_id."""
    delete = AsyncMock()
    monkeypatch.setattr(main, "_require_owner", lambda _request: {"r": "owner"})
    monkeypatch.setattr(database, "get_worker", AsyncMock(return_value={"id": 3}))
    monkeypatch.setattr(
        database,
        "list_earnapp_logical_nodes",
        AsyncMock(
            return_value=[
                {
                    "logical_node_id": "earnapp-ubuntu-canary-test-sing-5",
                    "assigned_worker_id": None,
                    "last_worker_id": 3,
                    "state": "RECOVERABLE",
                }
            ]
        ),
    )
    monkeypatch.setattr(database, "delete_worker", delete)

    with pytest.raises(HTTPException, match="protected EarnApp"):
        await main.api_delete_worker(_request("/api/workers/3"), 3)

    delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_database_delete_worker_refuses_protected_earnapp_last_worker_reference(tmp_path):
    """The database guard must survive callers that bypass the HTTP route."""
    with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
        await database.init_db()
        worker_id = await database.upsert_worker("protected-worker", "protected-worker", "http://worker")
        account_id = await database.upsert_earnapp_account(
            profile_key="protected-worker-profile",
            account_name="protected-worker@example.com",
            email="protected-worker@example.com",
            auth_method="google",
            credentials={"cookies": {"oauth-refresh-token": "refresh", "xsrf-token": "xsrf"}},
            credential_keys=["oauth-refresh-token", "xsrf-token"],
            token_expires_at=None,
            cookie_expires_at=None,
        )
        db = await database._get_db()
        try:
            await db.execute(
                """
                INSERT INTO earnapp_logical_nodes
                    (logical_node_id, account_id, platform, state, generation,
                     assigned_worker_id, last_worker_id, device_id)
                VALUES (?, ?, 'ubuntu', 'RECOVERABLE', 1, NULL, ?, ?)
                """,
                (
                    "earnapp-ubuntu-canary-test-sing-5",
                    account_id,
                    worker_id,
                    "sdk-node-" + "5" * 32,
                ),
            )
            await db.commit()
        finally:
            await db.close()

        with pytest.raises(RuntimeError, match="protected EarnApp"):
            await database.delete_worker(worker_id)

        assert await database.get_worker(worker_id) is not None


@pytest.mark.asyncio
async def test_database_delete_worker_refuses_protected_earnapp_alias_lease(tmp_path):
    """A provider lease alone is enough to prevent a cascading worker delete."""
    with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
        await database.init_db()
        worker_id = await database.upsert_worker("protected-lease-worker", "protected-lease-worker", "http://worker")
        provider_id = await database.upsert_proxy_provider("protected-lease-provider", "manual")
        (proxy_id,) = await database.upsert_proxy_endpoints_returning_ids(
            provider_id,
            [
                {
                    "provider_proxy_id": "protected-lease-proxy",
                    "endpoint": "proxy.example:1080",
                    "host": "proxy.example",
                    "port": 1080,
                    "protocol": "socks5",
                    "status": "alive",
                    "exit_ip": "203.0.113.55",
                }
            ],
        )
        db = await database._get_db()
        try:
            await db.execute(
                """
                INSERT INTO provider_proxy_leases
                    (provider_slug, worker_id, instance_id, proxy_id, exit_ip)
                VALUES ('earnapp', ?, ?, ?, '203.0.113.55')
                """,
                (worker_id, "cashpilot-earnapp-earnapp-ubuntu-canary-test-sing-5", proxy_id),
            )
            await db.commit()
        finally:
            await db.close()

        with pytest.raises(RuntimeError, match="protected EarnApp"):
            await database.delete_worker(worker_id)

        assert await database.get_worker(worker_id) is not None


@pytest.mark.asyncio
async def test_server_canary_route_allows_all_platform_lanes(monkeypatch):
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

    apple_deploy = AsyncMock(return_value={"status": "deployed", "logical_node_id": "x"})
    monkeypatch.setattr(earnapp_canary, "deploy_canary", apple_deploy)
    monkeypatch.setattr(earnapp_canary, "deploy_platform_canary", apple_deploy)
    monkeypatch.setattr(earnapp_canary, "verify_canary", verify)
    for platform in ("macos", "ios"):
        result = await main.api_deploy_earnapp_canary(
            _request("/api/admin/earnapp/canary/deploy"),
            main.EarnAppCanaryDeployRequest(
                logical_node_id=f"earnapp-{platform}-policy",
                worker_id=3,
                platform=platform,
            ),
            _auth={"r": "owner"},
        )
        assert result["online"] is True


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
        ("stop", [("POST", "/api/containers/earnapp-ubuntu-policy/stop")]),
        ("start", [("POST", "/api/containers/earnapp-ubuntu-policy/start")]),
        (
            "restart",
            [
                ("POST", "/api/containers/earnapp-ubuntu-policy/restart"),
            ],
        ),
        ("remove", [("DELETE", "/api/earnapp/docker-nodes/earnapp-ubuntu-policy")]),
    ],
)
async def test_server_lifecycle_dispatches_authoritative_ubuntu_docker_node(monkeypatch, action, expected_calls):
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
    if action == "remove":
        assert proxy.await_args.kwargs["json"] == {"generation": 4, "device_id": device_id}


@pytest.mark.asyncio
async def test_server_lifecycle_dispatches_persisted_ubuntu_docker_node(monkeypatch):
    device_id = "sdk-node-" + "6" * 32
    proxy = AsyncMock(return_value={"status": "ok"})
    monkeypatch.setattr(main, "_require_writer", lambda _request: {"r": "writer"})
    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(return_value=_authoritative_node(generation=6, device_id=device_id)),
    )
    monkeypatch.setattr(
        database, "get_provider_instance", AsyncMock(return_value={"instance_id": "earnapp-ubuntu-policy"})
    )
    monkeypatch.setattr(database, "get_provider_instance_spec", AsyncMock(return_value={"runtime_backend": "docker"}))
    monkeypatch.setattr(main, "_proxy_to_worker", proxy)
    monkeypatch.setattr(database, "record_health_event", AsyncMock())
    monkeypatch.setattr(main.metrics, "record_container_lifecycle", lambda *_args, **_kwargs: None)

    await main._svc_stop(_request("/api/stop/earnapp-ubuntu-policy"), "earnapp-ubuntu-policy", 3)

    proxy.assert_awaited_once_with(3, "POST", "/api/containers/earnapp-ubuntu-policy/stop")


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
async def test_raw_worker_lifecycle_dispatches_ubuntu_docker_without_trusting_body_spec(monkeypatch):
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
        "/api/containers/earnapp-ubuntu-policy/start",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["start", "stop", "restart", "remove"])
async def test_raw_worker_command_refuses_protected_runtime_alias_before_proxy(monkeypatch, action):
    proxy = AsyncMock(side_effect=AssertionError("protected alias reached worker"))
    lookup = AsyncMock(side_effect=AssertionError("protected alias reached authority lookup"))
    monkeypatch.setattr(main, "_require_writer", lambda _request: {"r": "writer"})
    monkeypatch.setattr(database, "get_earnapp_logical_node", lookup)
    monkeypatch.setattr(main, "_proxy_to_worker", proxy)

    with pytest.raises(HTTPException, match="Protected EarnApp"):
        await main.api_worker_command(
            _request("/api/workers/3/command"),
            3,
            main.WorkerCommand(
                command=action,
                slug="cashpilot-earnapp-earnapp-ubuntu-canary-test-sing-5",
            ),
        )

    lookup.assert_not_awaited()
    proxy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["start", "stop", "restart", "remove"])
async def test_server_service_lifecycle_refuses_protected_runtime_alias_before_worker(monkeypatch, action):
    resolve = AsyncMock(side_effect=AssertionError("protected alias reached worker resolution"))
    proxy = AsyncMock(side_effect=AssertionError("protected alias reached worker"))
    monkeypatch.setattr(main, "_require_writer", lambda _request: {"r": "writer"})
    monkeypatch.setattr(main, "_resolve_worker_id", resolve)
    monkeypatch.setattr(main, "_proxy_worker_command", proxy)
    slug = "cashpilot-earnapp-earnapp-ubuntu-canary-test-sing-5"

    with pytest.raises(HTTPException, match="Protected EarnApp"):
        if action == "start":
            await main.api_service_start(_request(f"/api/services/{slug}/start"), slug, 3)
        elif action == "stop":
            await main._svc_stop(_request(f"/api/stop/{slug}"), slug, 3)
        elif action == "restart":
            await main._svc_restart(_request(f"/api/restart/{slug}"), slug, 3)
        else:
            await main._svc_remove(_request(f"/api/remove/{slug}"), slug, 3, False)

    resolve.assert_not_awaited()
    proxy.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_dedicated_docker_cleanup_requires_runtime_state(monkeypatch):
    monkeypatch.setattr(worker_api, "_verify_api_key", lambda _request: None)
    monkeypatch.setattr(
        worker_api,
        "_earnapp_node_state",
        lambda _node: (_ for _ in ()).throw(AssertionError("generic cleanup must not read EarnApp state")),
    )

    with pytest.raises(AssertionError, match="generic cleanup"):
        await worker_api.api_remove_earnapp_docker_node(
            _request("/api/earnapp/docker-nodes/earnapp-legacy-node"),
            "earnapp-legacy-node",
            worker_api.EarnAppDockerNodeCasSpec(generation=1, device_id="sdk-mac-" + "1" * 32),
        )


def test_worker_local_state_cleanup_refuses_protected_node_before_unlink(monkeypatch):
    node_id = "earnapp-ubuntu-canary-test-sing-5"
    path = Mock()
    monkeypatch.setattr(worker_api, "_earnapp_state_path", Mock(return_value=path))

    with pytest.raises(ValueError, match="protected"):
        worker_api._remove_earnapp_state(node_id)

    path.unlink.assert_not_called()


@pytest.mark.asyncio
async def test_direct_database_assignment_and_binding_refuse_protected_node_before_db(monkeypatch):
    node_id = "earnapp-ubuntu-canary-test-sing-4"
    open_transaction = AsyncMock(side_effect=AssertionError("protected node reached the database"))
    monkeypatch.setattr(database, "_open_transaction_connection", open_transaction)

    with pytest.raises(ValueError, match="protected"):
        await database.assign_earnapp_account(node_id, platform="ubuntu")
    with pytest.raises(ValueError, match="protected"):
        await database.bind_earnapp_node_runtime(
            node_id,
            3,
            device_id="sdk-node-" + "4" * 32,
            proxy_id=12,
        )

    open_transaction.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_database_state_transitions_noop_for_protected_node_before_db(monkeypatch):
    node_id = "earnapp-ubuntu-canary-test-sing-4"
    open_transaction = AsyncMock(side_effect=AssertionError("protected node reached the database"))
    get_db = AsyncMock(side_effect=AssertionError("protected node reached the database"))
    monkeypatch.setattr(database, "_open_transaction_connection", open_transaction)
    monkeypatch.setattr(database, "_get_db", get_db)

    assert (
        await database.rollback_earnapp_canary_binding(
            node_id,
            3,
            generation=1,
            proxy_id=12,
            reason="test",
        )
        is False
    )
    assert (
        await database.finalize_earnapp_node_removal(
            node_id,
            3,
            generation=1,
            device_id="sdk-node-" + "4" * 32,
        )
        is False
    )
    assert await database.begin_earnapp_recovery_hold(node_id, hold_seconds=3600) is None

    open_transaction.assert_not_awaited()
    get_db.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_database_proxy_mutations_noop_for_protected_node_before_db(monkeypatch):
    node_id = "earnapp-ubuntu-canary-test-sing-4"
    open_transaction = AsyncMock(side_effect=AssertionError("protected node reached the database"))
    get_db = AsyncMock(side_effect=AssertionError("protected node reached the database"))
    monkeypatch.setattr(database, "_open_transaction_connection", open_transaction)
    monkeypatch.setattr(database, "_get_db", get_db)

    assert (
        await database.reserve_earnapp_proxy_candidate(
            node_id,
            3,
            generation=1,
            expected_proxy_id=12,
            candidate_proxy_id=13,
            binding_version="rotation_12345678",
        )
        is None
    )
    assert (
        await database.release_earnapp_proxy_reservation(
            node_id,
            binding_version="rotation_12345678",
            reason="test",
        )
        is False
    )
    assert (
        await database.commit_earnapp_proxy_rotation(
            node_id,
            3,
            expected_generation=1,
            expected_proxy_id=12,
            new_proxy_id=13,
            binding_version="rotation_12345678",
        )
        is None
    )
    assert await database.lease_proxy_for_provider_instance("earnapp", 3, node_id) is None
    assert (
        await database.release_proxy_for_provider_instance(
            "earnapp",
            3,
            node_id,
            reason="test",
        )
        is False
    )

    open_transaction.assert_not_awaited()
    get_db.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_database_recovery_mutations_noop_for_protected_node_before_db(monkeypatch):
    node_id = "earnapp-ubuntu-canary-test-sing-4"
    open_transaction = AsyncMock(side_effect=AssertionError("protected node reached the database"))
    monkeypatch.setattr(database, "_open_transaction_connection", open_transaction)

    assert (
        await database.create_earnapp_replacement_ticket(
            node_id,
            9,
            generation=1,
            token_hash="hash",
            expires_seconds=900,
        )
        == "protected_node"
    )
    assert await database.claim_earnapp_node(node_id, 9, expected_generation=1) is None

    open_transaction.assert_not_awaited()


@pytest.mark.asyncio
async def test_provision_node_refuses_protected_node_before_account_assignment(monkeypatch):
    assign = AsyncMock(side_effect=AssertionError("protected node reached account assignment"))
    monkeypatch.setattr(database, "assign_earnapp_account", assign)

    with pytest.raises(earnapp_recovery.RecoveryClaimDenied, match="protected"):
        await earnapp_recovery.provision_node(
            "earnapp-ubuntu-canary-test-sing-4",
            3,
            device_id="sdk-node-" + "4" * 32,
            proxy_country_code="US",
            platform="ubuntu",
        )

    assign.assert_not_awaited()


@pytest.mark.asyncio
async def test_prepare_node_refuses_protected_node_before_authority_lookup(monkeypatch):
    lookup = AsyncMock(side_effect=AssertionError("protected node reached authority lookup"))
    monkeypatch.setattr(database, "get_earnapp_logical_node", lookup)
    plan = earnapp_deploy.EarnAppNodePlan(
        worker_id=3,
        slot_id="ipv4-001",
        logical_node_id="earnapp-ubuntu-canary-test-sing-4",
    )

    with pytest.raises(RuntimeError, match="protected"):
        await earnapp_deploy.prepare_node(plan, required_platform="ubuntu")

    lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_generic_proxy_binding_apply_refuses_protected_node_before_probe(monkeypatch):
    probe = AsyncMock(return_value={"ok": True, "observed_exit_ip": "203.0.113.12"})
    apply = Mock(return_value={"applied_instances": [], "config_sha256": ""})
    monkeypatch.setattr(worker_api, "_verify_api_key", lambda _request: None)
    monkeypatch.setattr(worker_api, "_probe_proxy_targets", probe)
    monkeypatch.setattr(worker_api.orchestrator, "apply_proxy_binding_batch", apply)
    spec = worker_api.ProxyBindingApplySpec(
        binding_version="rotation_12345678",
        proxy={"proxy_id": 12, "host": "proxy.example", "port": 1080},
        instances=["other-node", "earnapp-ubuntu-canary-test-sing-4"],
    )

    with pytest.raises(HTTPException, match="Protected EarnApp"):
        await worker_api.api_apply_proxy_binding(_request("/api/egress/bindings/apply"), spec)

    probe.assert_not_awaited()
    apply.assert_not_called()


@pytest.mark.asyncio
async def test_generic_proxy_binding_finalize_refuses_protected_node_before_orchestrator(monkeypatch):
    finalize = Mock(return_value={"action": "confirmed", "finalized_instances": []})
    monkeypatch.setattr(worker_api, "_verify_api_key", lambda _request: None)
    monkeypatch.setattr(worker_api.orchestrator, "finalize_proxy_binding_batch", finalize)
    spec = worker_api.ProxyBindingFinalizeSpec(
        binding_version="rotation_12345678",
        instances=["other-node", "earnapp-ubuntu-canary-test-sing-4"],
        commit=True,
    )

    with pytest.raises(HTTPException, match="Protected EarnApp"):
        await worker_api.api_finalize_proxy_binding(_request("/api/egress/bindings/finalize"), spec)

    finalize.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route", "mutator"),
    [
        (worker_api.api_restart_container, "restart_service"),
        (worker_api.api_stop_container, "stop_service"),
        (worker_api.api_start_container, "start_service"),
    ],
)
async def test_generic_worker_lifecycle_refuses_protected_runtime_alias_before_orchestrator(
    monkeypatch, route, mutator
):
    mutate = Mock(side_effect=AssertionError("protected runtime reached orchestrator"))
    monkeypatch.setattr(worker_api, "_verify_api_key", lambda _request: None)
    monkeypatch.setattr(worker_api.orchestrator, mutator, mutate)

    with pytest.raises(HTTPException, match="Protected EarnApp"):
        await route(
            _request("/api/containers/protected/lifecycle"),
            "cashpilot-earnapp-ubuntu-canary-test-sing-4-egress",
        )

    mutate.assert_not_called()


@pytest.mark.asyncio
async def test_generic_worker_remove_refuses_protected_runtime_alias_before_orchestrator(monkeypatch):
    remove = Mock(side_effect=AssertionError("protected runtime reached orchestrator"))
    monkeypatch.setattr(worker_api, "_verify_api_key", lambda _request: None)
    monkeypatch.setattr(worker_api.orchestrator, "remove_service", remove)

    with pytest.raises(HTTPException, match="Protected EarnApp"):
        await worker_api.api_remove_container(
            _request("/api/containers/protected"),
            "cashpilot-earnapp-canary-test-sing-1",
        )

    remove.assert_not_called()


@pytest.mark.asyncio
async def test_generic_worker_deploy_refuses_protected_runtime_alias_before_asset_mutation(monkeypatch):
    materialize = AsyncMock(side_effect=AssertionError("protected runtime reached asset mutation"))
    deploy = Mock(side_effect=AssertionError("protected runtime reached orchestrator"))
    monkeypatch.setattr(worker_api, "_verify_api_key", lambda _request: None)
    monkeypatch.setattr(worker_api, "_materialize_runtime_assets", materialize)
    monkeypatch.setattr(worker_api.orchestrator, "deploy_raw", deploy)

    with pytest.raises(HTTPException, match="Protected EarnApp"):
        await worker_api.api_deploy_container(
            _request("/api/containers/protected/deploy"),
            "cashpilot-earnapp-earnapp-ubuntu-canary-test-sing-5",
            worker_api.DeploySpec(image="example.invalid/earnapp:test"),
        )

    materialize.assert_not_awaited()
    deploy.assert_not_called()


@pytest.mark.asyncio
async def test_proxy_delete_refuses_endpoint_referenced_by_protected_node(tmp_path):
    with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
        await database.init_db()
        account_id = await database.upsert_earnapp_account(
            profile_key="protected-profile",
            account_name="protected@example.com",
            email="protected@example.com",
            auth_method="google",
            credentials={"cookies": {"oauth-refresh-token": "refresh", "xsrf-token": "xsrf"}},
            credential_keys=["oauth-refresh-token", "xsrf-token"],
            token_expires_at=None,
            cookie_expires_at=None,
        )
        provider_id = await database.upsert_proxy_provider("manual", "manual")
        [proxy_id] = await database.upsert_proxy_endpoints_returning_ids(
            provider_id,
            [
                {
                    "provider_proxy_id": "protected-proxy",
                    "endpoint": "proxy.example:1080",
                    "host": "proxy.example",
                    "port": 1080,
                    "protocol": "socks5",
                    "status": "alive",
                    "exit_ip": "203.0.113.12",
                }
            ],
        )
        db = await database._get_db()
        await db.execute(
            """
            INSERT INTO earnapp_logical_nodes
                (logical_node_id, account_id, platform, state, generation, current_proxy_id, preferred_proxy_id)
            VALUES (?, ?, 'ubuntu', 'ACTIVE', 1, ?, ?)
            """,
            ("earnapp-ubuntu-canary-test-sing-4", account_id, proxy_id, proxy_id),
        )
        await db.commit()
        await db.close()

        with pytest.raises(database.ProtectedEarnAppProxyError, match="protected"):
            await database.delete_proxy_endpoints([proxy_id])

        rows = await database.list_proxy_pool()
        assert any(int(row["id"]) == proxy_id for row in rows)


@pytest.mark.asyncio
async def test_proxy_delete_refuses_duplicate_egress_and_control_route_of_protected_account(tmp_path):
    with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
        await database.init_db()
        account_id = await database.upsert_earnapp_account(
            profile_key="protected-control-profile",
            account_name="protected-control@example.com",
            email="protected-control@example.com",
            auth_method="google",
            credentials={"cookies": {"oauth-refresh-token": "refresh", "xsrf-token": "xsrf"}},
            credential_keys=["oauth-refresh-token", "xsrf-token"],
            token_expires_at=None,
            cookie_expires_at=None,
        )
        provider_id = await database.upsert_proxy_provider("manual", "manual")
        proxy_ids = await database.upsert_proxy_endpoints_returning_ids(
            provider_id,
            [
                {
                    "provider_proxy_id": "protected-control-proxy",
                    "endpoint": "control.example:1080",
                    "host": "control.example",
                    "port": 1080,
                    "protocol": "socks5",
                    "status": "alive",
                    "exit_ip": "203.0.113.30",
                },
                {
                    "provider_proxy_id": "duplicate-control-proxy",
                    "endpoint": "duplicate.example:1080",
                    "host": "duplicate.example",
                    "port": 1080,
                    "protocol": "socks5",
                    "status": "alive",
                    "exit_ip": "203.0.113.30",
                },
            ],
        )
        db = await database._get_db()
        await db.execute(
            """
            INSERT INTO earnapp_logical_nodes
                (logical_node_id, account_id, platform, state, generation)
            VALUES (?, ?, 'ubuntu', 'ACTIVE', 1)
            """,
            ("earnapp-ubuntu-canary-test-sing-4", account_id),
        )
        await db.execute(
            """
            INSERT INTO earnapp_account_control_routes
                (account_id, proxy_id, state, assigned_logical_node_id)
            VALUES (?, ?, 'ACTIVE', '')
            """,
            (account_id, proxy_ids[0]),
        )
        await db.commit()
        await db.close()

        with pytest.raises(database.ProtectedEarnAppProxyError, match="protected"):
            await database.delete_proxy_endpoints([proxy_ids[1]])

        rows = await database.list_proxy_pool()
        assert {int(row["id"]) for row in rows} == set(proxy_ids)


@pytest.mark.asyncio
async def test_proxy_delete_operates_normally_without_protected_reference(tmp_path):
    with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
        await database.init_db()
        provider_id = await database.upsert_proxy_provider("manual", "manual")
        [proxy_id] = await database.upsert_proxy_endpoints_returning_ids(
            provider_id,
            [
                {
                    "provider_proxy_id": "ordinary-delete-proxy",
                    "endpoint": "ordinary-delete.example:1080",
                    "host": "ordinary-delete.example",
                    "port": 1080,
                    "protocol": "socks5",
                    "status": "alive",
                    "exit_ip": "203.0.113.31",
                }
            ],
        )

        assert await database.delete_proxy_endpoints([proxy_id]) == 1
        assert await database.list_proxy_pool() == []


@pytest.mark.asyncio
async def test_delete_all_proxy_pool_operates_normally_without_protected_reference(tmp_path):
    with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
        await database.init_db()
        provider_id = await database.upsert_proxy_provider("manual", "manual")
        proxy_ids = await database.upsert_proxy_endpoints_returning_ids(
            provider_id,
            [
                {
                    "provider_proxy_id": "ordinary-delete-all-a",
                    "endpoint": "ordinary-a.example:1080",
                    "host": "ordinary-a.example",
                    "port": 1080,
                    "protocol": "socks5",
                    "status": "alive",
                    "exit_ip": "203.0.113.32",
                },
                {
                    "provider_proxy_id": "ordinary-delete-all-b",
                    "endpoint": "ordinary-b.example:1080",
                    "host": "ordinary-b.example",
                    "port": 1080,
                    "protocol": "socks5",
                    "status": "alive",
                    "exit_ip": "203.0.113.33",
                },
            ],
        )

        assert await database.delete_all_proxy_pool() == len(proxy_ids)
        assert await database.list_proxy_pool() == []


@pytest.mark.asyncio
async def test_delete_all_proxy_pool_fails_closed_before_deleting_protected_endpoint(tmp_path):
    with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
        await database.init_db()
        account_id = await database.upsert_earnapp_account(
            profile_key="protected-profile-all",
            account_name="protected-all@example.com",
            email="protected-all@example.com",
            auth_method="google",
            credentials={"cookies": {"oauth-refresh-token": "refresh", "xsrf-token": "xsrf"}},
            credential_keys=["oauth-refresh-token", "xsrf-token"],
            token_expires_at=None,
            cookie_expires_at=None,
        )
        provider_id = await database.upsert_proxy_provider("manual", "manual")
        proxy_ids = await database.upsert_proxy_endpoints_returning_ids(
            provider_id,
            [
                {
                    "provider_proxy_id": "protected-all-proxy",
                    "endpoint": "proxy-all.example:1080",
                    "host": "proxy-all.example",
                    "port": 1080,
                    "protocol": "socks5",
                    "status": "alive",
                    "exit_ip": "203.0.113.13",
                },
                {
                    "provider_proxy_id": "ordinary-proxy",
                    "endpoint": "ordinary.example:1080",
                    "host": "ordinary.example",
                    "port": 1080,
                    "protocol": "socks5",
                    "status": "alive",
                    "exit_ip": "203.0.113.14",
                },
            ],
        )
        db = await database._get_db()
        await db.execute(
            """
            INSERT INTO earnapp_logical_nodes
                (logical_node_id, account_id, platform, state, generation, current_proxy_id)
            VALUES (?, ?, 'ubuntu', 'ACTIVE', 1, ?)
            """,
            ("earnapp-ubuntu-canary-test-sing-5", account_id, proxy_ids[0]),
        )
        await db.commit()
        await db.close()

        with pytest.raises(database.ProtectedEarnAppProxyError, match="protected"):
            await database.delete_all_proxy_pool()

        rows = await database.list_proxy_pool()
        assert {int(row["id"]) for row in rows} == set(proxy_ids)


@pytest.mark.asyncio
async def test_direct_recovery_sweep_always_excludes_protected_nodes(tmp_path):
    with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
        await database.init_db()
        worker_id = await database.upsert_worker("protected-worker", "Protected worker", "http://worker")
        account_id = await database.upsert_earnapp_account(
            profile_key="protected-sweep-profile",
            account_name="protected-sweep@example.com",
            email="protected-sweep@example.com",
            auth_method="google",
            credentials={"cookies": {"oauth-refresh-token": "refresh", "xsrf-token": "xsrf"}},
            credential_keys=["oauth-refresh-token", "xsrf-token"],
            token_expires_at=None,
            cookie_expires_at=None,
        )
        provider_id = await database.upsert_proxy_provider("manual", "manual")
        [proxy_id] = await database.upsert_proxy_endpoints_returning_ids(
            provider_id,
            [
                {
                    "provider_proxy_id": "protected-sweep-proxy",
                    "endpoint": "sweep.example:1080",
                    "host": "sweep.example",
                    "port": 1080,
                    "protocol": "socks5",
                    "status": "alive",
                    "exit_ip": "203.0.113.20",
                }
            ],
        )
        db = await database._get_db()
        await db.execute(
            "UPDATE workers SET last_heartbeat = datetime('now', '-2 hours') WHERE id = ?",
            (worker_id,),
        )
        await db.execute(
            """
            INSERT INTO earnapp_logical_nodes
                (logical_node_id, account_id, platform, state, generation, assigned_worker_id,
                 last_worker_id, device_id, current_proxy_id, preferred_proxy_id)
            VALUES (?, ?, 'ubuntu', 'ACTIVE', 1, ?, ?, ?, ?, ?)
            """,
            (
                "earnapp-ubuntu-canary-test-sing-4",
                account_id,
                worker_id,
                worker_id,
                "sdk-node-" + "4" * 32,
                proxy_id,
                proxy_id,
            ),
        )
        await db.execute(
            """
            INSERT INTO provider_proxy_leases
                (provider_slug, worker_id, instance_id, proxy_id, exit_ip)
            VALUES ('earnapp', ?, ?, ?, '203.0.113.20')
            """,
            (worker_id, "earnapp-ubuntu-canary-test-sing-4", proxy_id),
        )
        await db.commit()
        await db.close()

        result = await database.sweep_stale_earnapp_nodes(
            stale_after_seconds=60,
            hold_seconds=1,
            platforms=("ubuntu",),
        )
        node = await database.get_earnapp_logical_node("earnapp-ubuntu-canary-test-sing-4")
        lease = await database.get_active_provider_proxy_lease(
            "earnapp",
            worker_id,
            "earnapp-ubuntu-canary-test-sing-4",
        )

        assert result == {"held": [], "released": []}
        assert node["state"] == "ACTIVE"
        assert node["current_proxy_id"] == proxy_id
        assert lease is not None


@pytest.mark.asyncio
async def test_control_route_mutations_refuse_account_bound_to_protected_node_before_db(monkeypatch):
    node_id = "earnapp-ubuntu-canary-test-sing-4"
    protected_lookup = AsyncMock(return_value=node_id)
    open_transaction = AsyncMock(side_effect=AssertionError("protected account reached transaction"))
    monkeypatch.setattr(database, "_protected_earnapp_account_reference", protected_lookup)
    monkeypatch.setattr(database, "_open_transaction_connection", open_transaction)

    assert (
        await database.release_earnapp_account_control_route(
            7,
            expected_proxy_id=12,
            reason="test",
        )
        is False
    )
    assert await database.lease_earnapp_account_control_proxy(7) is None
    assert (
        await database.transfer_earnapp_control_route_to_node(
            7,
            "earnapp-new-node",
            worker_id=3,
        )
        is None
    )

    assert protected_lookup.await_count == 3
    open_transaction.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_locked_account_refuses_protected_runtime_before_transaction(monkeypatch):
    protected_lookup = AsyncMock(return_value="earnapp-ubuntu-canary-test-sing-4")
    open_transaction = AsyncMock(side_effect=AssertionError("protected account reached transaction"))
    monkeypatch.setattr(database, "_protected_earnapp_account_reference", protected_lookup)
    monkeypatch.setattr(database, "_open_transaction_connection", open_transaction)

    assert (
        await database.delete_locked_earnapp_account(
            7,
            runtime_instance_ids=["cashpilot-earnapp-earnapp-ubuntu-canary-test-sing-4"],
        )
        == "PROTECTED_RUNTIME"
    )

    protected_lookup.assert_not_awaited()
    open_transaction.assert_not_awaited()


@pytest.mark.asyncio
async def test_proxy_pool_delete_route_maps_protected_reference_to_conflict(monkeypatch):
    monkeypatch.setattr(proxy_routes.deps, "_require_owner", lambda _request: {"r": "owner"})
    monkeypatch.setattr(
        database,
        "delete_proxy_endpoints",
        AsyncMock(side_effect=database.ProtectedEarnAppProxyError("protected reference")),
    )

    with pytest.raises(HTTPException) as exc:
        await proxy_routes.api_proxy_pool_delete(
            _request("/api/proxy-pool"),
            proxy_routes.ProxyDeleteIn(proxy_ids=[12]),
        )

    assert exc.value.status_code == 409
    assert "protected EarnApp" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_proxy_pool_delete_all_route_maps_protected_reference_to_conflict(monkeypatch):
    phrase = "DELETE ALL PROXY POOL"
    monkeypatch.setattr(proxy_routes.deps, "_require_owner", lambda _request: {"r": "owner"})
    monkeypatch.setattr(
        database,
        "delete_all_proxy_pool",
        AsyncMock(side_effect=database.ProtectedEarnAppProxyError("protected reference")),
    )

    with pytest.raises(HTTPException) as exc:
        await proxy_routes.api_proxy_pool_delete(
            _request("/api/proxy-pool"),
            proxy_routes.ProxyDeleteIn(
                delete_all=True,
                confirmation=phrase,
                confirmation_again=phrase,
            ),
        )

    assert exc.value.status_code == 409
    assert "protected EarnApp" in str(exc.value.detail)


def test_protected_policy_recognizes_runtime_aliases_without_matching_other_providers():
    node_id = "earnapp-ubuntu-canary-test-sing-4"

    assert earnapp_policy.is_protected_runtime_reference(node_id)
    assert earnapp_policy.is_protected_runtime_reference(f"cashpilot-{node_id}")
    assert earnapp_policy.is_protected_runtime_reference(f"cashpilot-{node_id}-egress")
    assert earnapp_policy.is_protected_runtime_reference(f"cashpilot-earnapp-{node_id}")
    assert not earnapp_policy.is_protected_runtime_reference("cashpilot-nkn-earnapp-ubuntu-canary-test-sing-4")


@pytest.mark.asyncio
async def test_canary_helpers_refuse_protected_node_before_lookup_or_link(monkeypatch):
    protected = "earnapp-ubuntu-canary-test-sing-4"
    lookup = AsyncMock(side_effect=AssertionError("protected canary reached database"))
    deploy = AsyncMock(side_effect=AssertionError("protected canary reached worker"))
    collector = Mock(side_effect=AssertionError("protected canary reached account link"))
    monkeypatch.setattr(database, "get_earnapp_logical_node", lookup)
    monkeypatch.setattr(earnapp_canary, "EarnAppAccountCollector", collector)

    with pytest.raises(ValueError, match="protected"):
        await earnapp_canary.provision_canary(protected, 3, "sdk-mac-" + "1" * 32)
    with pytest.raises(ValueError, match="protected"):
        await earnapp_canary.deploy_canary(
            protected,
            3,
            worker_deploy=deploy,
            worker_remove=AsyncMock(),
        )
    with pytest.raises(ValueError, match="protected"):
        await earnapp_canary.deploy_platform_canary(
            protected,
            3,
            platform="ubuntu",
            worker_deploy=deploy,
            worker_remove=AsyncMock(),
        )
    with pytest.raises(ValueError, match="protected"):
        await earnapp_canary.verify_canary(protected, attempts=1, interval_seconds=0)

    lookup.assert_not_awaited()
    deploy.assert_not_awaited()
    collector.assert_not_called()


@pytest.mark.asyncio
async def test_canary_verify_route_refuses_protected_node_before_link(monkeypatch):
    verify = AsyncMock(side_effect=AssertionError("protected canary reached link verification"))
    monkeypatch.setattr(earnapp_canary, "verify_canary", verify)

    with pytest.raises(HTTPException) as exc:
        await main.api_verify_earnapp_canary(
            _request("/api/admin/earnapp/canary/earnapp-ubuntu-canary-test-sing-4/verify"),
            "earnapp-ubuntu-canary-test-sing-4",
            _auth={"r": "owner"},
        )

    assert exc.value.status_code == 409
    verify.assert_not_awaited()


@pytest.mark.asyncio
async def test_generic_proxy_binding_refuses_protected_sidecar_alias_before_probe(monkeypatch):
    probe = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(worker_api, "_verify_api_key", lambda _request: None)
    monkeypatch.setattr(worker_api, "_probe_proxy_targets", probe)
    spec = worker_api.ProxyBindingApplySpec(
        binding_version="rotation_12345678",
        proxy={"proxy_id": 12, "host": "proxy.example", "port": 1080},
        instances=["cashpilot-earnapp-ubuntu-canary-test-sing-4-egress"],
    )

    with pytest.raises(HTTPException, match="Protected EarnApp"):
        await worker_api.api_apply_proxy_binding(_request("/api/egress/bindings/apply"), spec)

    probe.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_database_bookkeeping_mutators_refuse_protected_aliases_before_db(monkeypatch):
    node_id = "earnapp-ubuntu-canary-test-sing-4"
    get_db = AsyncMock(side_effect=AssertionError("protected bookkeeping reached database"))
    set_config = AsyncMock(side_effect=AssertionError("protected identity reached config"))
    monkeypatch.setattr(database, "_get_db", get_db)
    monkeypatch.setattr(database, "set_config", set_config)

    assert await database.set_earnapp_logical_node_state(node_id, "RECOVERY_HOLD") is False
    with pytest.raises(ValueError, match="protected"):
        await database.save_earnapp_identity_profile(
            node_id,
            platform="ubuntu",
            asset_kind="ubuntu_identity_profile",
            device_id="sdk-node-" + "4" * 32,
            value="{}",
        )
    with pytest.raises(ValueError, match="protected"):
        await database.save_provider_instance(
            "earnapp",
            "cashpilot-earnapp-earnapp-ubuntu-canary-test-sing-4",
            worker_id=3,
            status="running",
        )
    assert await database.remove_provider_instance("cashpilot-earnapp-earnapp-ubuntu-canary-test-sing-4") is False

    get_db.assert_not_awaited()
    set_config.assert_not_awaited()
