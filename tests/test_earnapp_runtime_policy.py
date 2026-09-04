from __future__ import annotations

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import database, earnapp_accounts, main, provider_runtime, worker_api


@pytest.fixture(autouse=True)
def _supported_lifecycle_worker(monkeypatch):
    """Provide the capability record expected by direct lifecycle tests."""
    monkeypatch.setattr(
        database,
        "get_worker",
        AsyncMock(return_value={"status": "online", "system_info": {"version": "1.18.21"}}),
    )


def _request(path: str) -> Request:
    return Request({"type": "http", "method": "POST", "path": path, "headers": []})


def test_runtime_policy_allows_dedicated_apple_earnapp_mutation():
    block = provider_runtime.mutation_block(
        "earnapp-node-1",
        {"provider_slug": "earnapp", "platform": "macos", "runtime_backend": "docker"},
    )

    assert block is None


def test_runtime_guards_follow_the_authoritative_policy_when_earnapp_is_reenabled(monkeypatch):
    providers = dict(provider_runtime.PROVIDERS)
    providers["earnapp"] = replace(
        providers["earnapp"],
        deployment_allowed=True,
        deployment_policy="enabled",
        policy_message="",
    )
    monkeypatch.setattr(provider_runtime, "PROVIDERS", providers)

    assert provider_runtime.deployment_block("earnapp-node-1") is None
    assert provider_runtime.deployment_block("legacy-node", {"provider_slug": "earnapp"}) is None
    assert provider_runtime.mutation_block("earnapp-node-1") is None


@pytest.mark.asyncio
async def test_pending_reconciliation_is_inspection_only_when_runtime_is_blocked(monkeypatch):
    finalize = AsyncMock()
    monkeypatch.setattr(main, "_proxy_to_worker", finalize)

    result = await main._reconcile_earnapp_pending_proxy_binding(
        {
            "logical_node_id": "earnapp-node-1",
            "generation": 1,
            "proxy_id": 11,
            "pending_proxy_id": 12,
            "device_id": "sdk-mac-12345678",
            "pending_binding_version": "rotation_12345678",
            "pending_expected_egress_ip": "198.51.100.12",
        },
        7,
    )

    assert result is False
    finalize.assert_not_awaited()


@pytest.mark.asyncio
async def test_unhealthy_rotation_blocks_apple_after_authoritative_lookup(monkeypatch):
    authority = AsyncMock(return_value={"platform": "macos"})
    worker = AsyncMock()
    monkeypatch.setattr(database, "get_earnapp_logical_node", authority)
    monkeypatch.setattr(main, "_proxy_to_worker", worker)

    result = await main._rotate_unhealthy_earnapp_node("earnapp-node-1", 7, generation=1, expected_proxy_id=11)

    assert result is False
    authority.assert_awaited_once_with("earnapp-node-1")
    worker.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "worker",
    [
        {"status": "online", "system_info": {"version": "1.18.20"}},
        {"status": "online", "system_info": {}},
        {"status": "offline", "system_info": {"version": "1.18.21"}},
        None,
    ],
)
async def test_pending_reconciliation_never_mutates_unsupported_worker(monkeypatch, worker):
    monkeypatch.setattr(database, "get_worker", AsyncMock(return_value=worker))
    finalize = AsyncMock()
    monkeypatch.setattr(main, "_proxy_to_worker", finalize)

    result = await main._reconcile_earnapp_pending_proxy_binding(
        {
            "logical_node_id": "earnapp-node-capability-gate",
            "generation": 1,
            "proxy_id": 11,
            "pending_proxy_id": 12,
            "device_id": "sdk-mac-12345678",
            "pending_binding_version": "rotation_12345678",
            "pending_expected_egress_ip": "198.51.100.12",
        },
        7,
    )

    assert result is False
    finalize.assert_not_awaited()


@pytest.mark.asyncio
async def test_unhealthy_rotation_never_mutates_when_worker_lookup_fails(monkeypatch):
    monkeypatch.setattr(database, "get_worker", AsyncMock(side_effect=RuntimeError("database unavailable")))
    worker_call = AsyncMock()
    monkeypatch.setattr(main, "_proxy_to_worker", worker_call)

    result = await main._rotate_unhealthy_earnapp_node(
        "earnapp-node-capability-gate",
        7,
        generation=1,
        expected_proxy_id=11,
    )

    assert result is False
    worker_call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["proxy/apply", "proxy/finalize"])
async def test_worker_apple_mutation_routes_fail_closed_before_runtime_calls(monkeypatch, route):
    monkeypatch.setattr(worker_api, "_verify_api_key", lambda _request: None)
    lxd_state = AsyncMock()
    monkeypatch.setattr(worker_api.earnapp_lxd_runtime, "apply_proxy_binding", lxd_state)
    monkeypatch.setattr(worker_api.earnapp_lxd_runtime, "finalize_proxy_binding", lxd_state)
    monkeypatch.setattr(
        worker_api,
        "_earnapp_node_state",
        lambda _node: {"platform": "macos", "runtime_backend": "docker"},
    )

    node_id = "earnapp-node-1"
    if route == "proxy/apply":
        spec = worker_api.EarnAppProxyApplySpec(
            generation=1,
            device_id="sdk-mac-" + "1" * 32,
            expected_proxy_id=11,
            binding_version="rotation_12345678",
            proxy={"proxy_id": 12, "exit_ip": "198.51.100.12", "ip_type": "residential"},
        )
        handler = worker_api.api_apply_earnapp_node_proxy
    else:
        spec = worker_api.EarnAppProxyFinalizeSpec(
            generation=1,
            device_id="sdk-mac-" + "1" * 32,
            expected_proxy_id=11,
            new_proxy_id=12,
            binding_version="rotation_12345678",
            commit=False,
        )
        handler = worker_api.api_finalize_earnapp_node_proxy

    with pytest.raises(HTTPException) as exc:
        await handler(_request(f"/api/earnapp/nodes/{node_id}/{route}"), node_id, spec)

    assert exc.value.status_code == 409
    assert "assignment conflict" in str(exc.value.detail).lower()
    lxd_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_ubuntu_lxd_mutation_route_is_retired_for_any_node_id(monkeypatch):
    monkeypatch.setattr(worker_api, "_verify_api_key", lambda _request: None)
    monkeypatch.setattr(
        worker_api,
        "_earnapp_lxd_state",
        lambda _node: {
            "generation": 1,
            "device_id": "sdk-node-" + "1" * 32,
            "platform": "ubuntu",
            "runtime_backend": "lxd",
        },
    )
    suspend = Mock(return_value={"running": False})
    monkeypatch.setattr(worker_api.earnapp_lxd_runtime, "suspend_node", suspend)
    spec = worker_api.EarnAppNodeCasSpec(generation=1, device_id="sdk-node-" + "1" * 32)

    with pytest.raises(HTTPException) as exc:
        await worker_api.api_suspend_earnapp_lxd_node(
            _request("/api/earnapp/nodes/legacy-node/suspend"), "legacy-node", spec
        )
    assert exc.value.status_code == 409
    suspend.assert_not_called()


def test_locked_account_with_existing_runtime_cannot_be_deleted_under_disabled_policy(tmp_path, monkeypatch):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account_id = await database.upsert_earnapp_account(
                profile_key="profile-policy",
                account_name="policy@example.com",
                email="policy@example.com",
                auth_method="google",
                credentials={"cookies": {"oauth-refresh-token": "refresh", "xsrf-token": "xsrf"}},
                credential_keys=["oauth-refresh-token", "xsrf-token"],
                token_expires_at=None,
                cookie_expires_at=None,
            )
            await database.assign_earnapp_account("earnapp-node-1", platform="macos")
            db = await database._get_db()
            await db.execute(
                "UPDATE earnapp_logical_nodes SET state='ACTIVE', device_id='sdk-mac-11111111' WHERE logical_node_id=?",
                ("earnapp-node-1",),
            )
            await db.commit()
            await database.set_earnapp_account_state(account_id, "ACCOUNT_LOCKED")

            cleanup = AsyncMock(return_value=True)
            await earnapp_accounts.delete_account(account_id, runtime_cleanup=cleanup)
            cleanup.assert_awaited_once()

    asyncio.run(run())
