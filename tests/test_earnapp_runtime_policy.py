from __future__ import annotations

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import database, earnapp_accounts, main, provider_runtime, worker_api


def _request(path: str) -> Request:
    return Request({"type": "http", "method": "POST", "path": path, "headers": []})


def test_runtime_policy_exposes_a_mutation_block_for_disabled_earnapp():
    block = provider_runtime.mutation_block("earnapp-node-1")

    assert block is not None
    assert block.slug == "earnapp"
    assert block.deployment_allowed is False


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
async def test_unhealthy_rotation_is_blocked_before_authority_or_worker_mutation(monkeypatch):
    authority = AsyncMock()
    worker = AsyncMock()
    monkeypatch.setattr(database, "get_earnapp_logical_node", authority)
    monkeypatch.setattr(main, "_proxy_to_worker", worker)

    result = await main._rotate_unhealthy_earnapp_node(
        "earnapp-node-1", 7, generation=1, expected_proxy_id=11
    )

    assert result is False
    authority.assert_not_awaited()
    worker.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "route",
    [
        "suspend",
        "resume",
        "remove",
        "proxy/apply",
        "proxy/finalize",
    ],
)
async def test_worker_earnapp_mutation_routes_fail_closed_before_runtime_calls(monkeypatch, route):
    monkeypatch.setattr(worker_api, "_verify_api_key", lambda _request: None)
    lxd_state = AsyncMock()
    monkeypatch.setattr(worker_api.earnapp_lxd_runtime, "suspend_node", lxd_state)
    monkeypatch.setattr(worker_api.earnapp_lxd_runtime, "resume_node", lxd_state)
    monkeypatch.setattr(worker_api.earnapp_lxd_runtime, "remove_node", lxd_state)
    monkeypatch.setattr(worker_api.earnapp_lxd_runtime, "apply_proxy_binding", lxd_state)
    monkeypatch.setattr(worker_api.earnapp_lxd_runtime, "finalize_proxy_binding", lxd_state)
    monkeypatch.setattr(worker_api, "_earnapp_lxd_state", lambda _node: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(worker_api, "_earnapp_node_state", lambda _node: (_ for _ in ()).throw(AssertionError()))

    node_id = "earnapp-node-1"
    if route in {"suspend", "resume", "remove"}:
        spec = worker_api.EarnAppNodeCasSpec(generation=1, device_id="sdk-node-" + "1" * 32)
        handler = {
            "suspend": worker_api.api_suspend_earnapp_lxd_node,
            "resume": worker_api.api_resume_earnapp_lxd_node,
            "remove": worker_api.api_remove_earnapp_lxd_node,
        }[route]
    elif route == "proxy/apply":
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
    assert "prohibits virtual machines" in str(exc.value.detail)
    lxd_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_earnapp_mutation_route_does_not_depend_on_node_id_prefix(monkeypatch):
    monkeypatch.setattr(worker_api, "_verify_api_key", lambda _request: None)
    monkeypatch.setattr(
        worker_api,
        "_earnapp_lxd_state",
        lambda _node: (_ for _ in ()).throw(AssertionError("runtime state must stay unread")),
    )
    spec = worker_api.EarnAppNodeCasSpec(generation=1, device_id="sdk-node-" + "1" * 32)

    with pytest.raises(HTTPException) as exc:
        await worker_api.api_suspend_earnapp_lxd_node(_request("/api/earnapp/nodes/legacy-node/suspend"), "legacy-node", spec)

    assert exc.value.status_code == 409
    assert "prohibits virtual machines" in str(exc.value.detail)


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

            with pytest.raises(earnapp_accounts.AccountDeletionDenied, match="inspection-only"):
                await earnapp_accounts.delete_account(account_id, runtime_cleanup=AsyncMock(return_value=True))

    asyncio.run(run())
