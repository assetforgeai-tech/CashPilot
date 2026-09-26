from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from app import main


def test_resolve_worker_id_adopts_online_reenrollment_with_same_endpoint(monkeypatch):
    async def run():
        monkeypatch.setattr(
            main.database,
            "get_worker",
            AsyncMock(
                return_value={
                    "id": 112494,
                    "status": "offline",
                    "url": "http://20.187.79.110:8081",
                    "name": "20.187.79.110",
                }
            ),
        )
        monkeypatch.setattr(
            main.database,
            "list_workers",
            AsyncMock(
                return_value=[
                    {"id": 112494, "status": "offline", "url": "http://20.187.79.110:8081", "name": "20.187.79.110"},
                    {"id": 118903, "status": "online", "url": "http://20.187.79.110:8081", "name": "20.187.79.110"},
                ]
            ),
        )
        assert await main._resolve_worker_id(112494) == 118903

    asyncio.run(run())


def test_resolve_worker_id_counts_one_physical_worker_per_endpoint(monkeypatch):
    async def run():
        monkeypatch.setattr(
            main.database,
            "list_workers",
            AsyncMock(
                return_value=[
                    {
                        "id": 112494,
                        "status": "online",
                        "url": "http://20.187.79.110:8081",
                        "registered_at": "2026-09-10 10:00:00",
                        "last_heartbeat": "2026-09-16 12:01:00",
                    },
                    {
                        "id": 118903,
                        "status": "online",
                        "url": "http://20.187.79.110:8081/",
                        "registered_at": "2026-09-15 10:00:00",
                        "last_heartbeat": "2026-09-16 12:00:00",
                    },
                ]
            ),
        )
        assert await main._resolve_worker_id(None) == 118903

    asyncio.run(run())


def test_auto_deploy_is_disabled_by_default():
    assert main._auto_deploy_settings({})["enabled"] is False
    assert main._auto_deploy_settings({})["delay_seconds"] == 10


def test_auto_deploy_targets_deployable_catalog_services_only():
    services = [
        {"slug": "ok", "status": "active", "docker": {"image": "img"}},
        {"slug": "manual", "status": "active", "docker": {"image": ""}},
        {"slug": "dead", "status": "dead", "docker": {"image": "img"}},
    ]

    assert main._auto_deploy_slugs(services) == ["ok"]


def test_auto_deploy_includes_failed_target_only_in_operator_armed_round():
    async def run():
        main._WORKER_HEARTBEAT_STREAKS[7] = 2
        main._NKN_AUTO_DEPLOY_DONE.add(7)
        main._EARNAPP_AUTO_DEPLOY_DONE.add(7)
        services = [
            {"slug": slug, "status": "active", "docker": {"image": "img"}}
            for slug in ("legacy", "failed", "running", "planned", "verification")
        ]
        instances = [
            {"slug": "failed", "status": "failed"},
            {"slug": "running", "status": "running"},
            {"slug": "planned", "status": "planned"},
            {"slug": "verification", "status": "verification_pending"},
        ]
        captured = []
        with (
            patch.object(
                main.database,
                "get_config",
                AsyncMock(
                    return_value={
                        "cashpilot_auto_deploy_enabled": "true",
                        "cashpilot_autodeploy_round_generation": "1",
                        "cashpilot_autodeploy_worker_ids": "7",
                    }
                ),
            ),
            patch.object(
                main.database,
                "get_worker",
                AsyncMock(return_value={"id": 7, "name": "worker-a", "status": "online", "key_confirmed": 1}),
            ),
            patch.object(main.database, "get_deployments", AsyncMock(return_value=[{"slug": "legacy"}])) as global_rows,
            patch.object(main.database, "list_provider_instances", AsyncMock(return_value=instances)) as worker_rows,
            patch.object(main.catalog, "get_services", return_value=services),
            patch.object(main, "_auto_deploy_credentials_ready", return_value=True),
            patch.object(main.database, "claim_rollout_round", AsyncMock(return_value="run-1")) as claim,
            patch.object(main, "_run_auto_deploy_sequence", AsyncMock()) as sequence,
            patch.object(main, "_spawn", side_effect=captured.append),
        ):
            await main._maybe_auto_deploy_after_heartbeat(7)
            assert len(captured) == 1
            await captured.pop()
        worker_rows.assert_awaited_once_with(worker_id=7)
        global_rows.assert_not_awaited()
        claim.assert_awaited_once_with(7, 1, ["legacy", "failed"])
        assert sequence.await_args.args[2] == ["legacy", "failed"]

    asyncio.run(run())


def test_auto_deploy_skips_services_with_missing_required_credentials():
    services = [
        {
            "slug": "needs-token",
            "status": "active",
            "docker": {"image": "example/client"},
            "deploy": {},
        },
        {
            "slug": "ready",
            "status": "active",
            "docker": {"image": "example/client"},
            "deploy": {},
        },
    ]
    with patch.object(
        main,
        "_auto_deploy_credentials_ready",
        side_effect=lambda slug, _svc, _config: slug == "ready",
    ):
        assert main._auto_deploy_slugs(services, {}) == ["ready"]


def test_auto_deploy_skips_server_worker_by_default():
    assert (
        main._worker_allowed_for_auto_deploy(
            {"id": 1, "name": "cashpilot"}, {"cashpilot_autodeploy_include_server": ""}
        )
        is False
    )


def test_auto_deploy_worker_scope_defaults_open_and_restricts_when_configured():
    assert main._worker_allowed_for_auto_deploy({"id": 7, "name": "worker"}, {}) is True
    config = {"cashpilot_autodeploy_worker_ids": "112444, 112494"}
    assert main._worker_allowed_for_auto_deploy({"id": 112444, "name": "worker"}, config) is True
    assert main._worker_allowed_for_auto_deploy({"id": 7, "name": "worker"}, config) is False
    assert (
        main._worker_allowed_for_auto_deploy(
            {"id": 1, "name": "cashpilot"}, {"cashpilot_autodeploy_include_server": "true"}
        )
        is True
    )


def test_auto_deploy_uses_one_lock_per_worker_and_continues_after_failure():
    async def run():
        calls: list[str] = []

        async def fake_deploy(worker_id: int, slug: str):
            await asyncio.sleep(0)
            calls.append(slug)
            if slug == "bad":
                raise RuntimeError("boom")
            return {"status": "deployed"}

        with patch.object(main, "_auto_deploy_one", AsyncMock(side_effect=fake_deploy)):
            await asyncio.gather(
                main._run_auto_deploy_batch(7, ["ok", "bad", "next"], delay_seconds=0),
                main._run_auto_deploy_batch(7, ["dup"], delay_seconds=0),
            )

        assert calls == ["ok", "bad", "next"]

    asyncio.run(run())


def test_earnapp_auto_deploy_calls_the_dedicated_ubuntu_lane():
    async def run():
        main._NKN_AUTO_DEPLOY_DONE.add(7)
        main._EARNAPP_AUTO_DEPLOY_DONE.discard(7)

        with patch.object(
            main,
            "_deploy_earnapp_nodes",
            AsyncMock(
                return_value={
                    "deployed": ["earnapp-proxy-w7-ipv4-001"],
                    "verified": ["earnapp-proxy-w7-ipv4-001"],
                    "skipped": [],
                    "pending": [],
                    "failed": [],
                }
            ),
        ) as deploy:
            await main._run_auto_deploy_sequence(7, {}, [], delay_seconds=0)

        deploy.assert_awaited_once_with(7, config={})
        assert 7 in main._EARNAPP_AUTO_DEPLOY_DONE

    asyncio.run(run())


def test_auto_deploy_one_uses_server_deploy_endpoint():
    async def run():
        with patch.object(main, "api_deploy", AsyncMock(return_value={"status": "deployed"})) as deploy:
            await main._auto_deploy_one(9, "demo-provider")
        args, kwargs = deploy.await_args
        assert args[1] == "demo-provider"
        assert isinstance(args[2], main.DeployRequest)
        assert kwargs["worker_id"] == 9

    asyncio.run(run())


def test_auto_deploy_sequence_runs_nkn_catalog_and_earnapp_ubuntu_lanes():
    async def run():
        calls: list[str] = []
        main._NKN_AUTO_DEPLOY_DONE.discard(7)
        main._EARNAPP_AUTO_DEPLOY_DONE.discard(7)

        async def nkn(*_args, **_kwargs):
            calls.append("nkn")
            return {"slots": 1, "failed": []}

        async def generic(_worker_id, slug):
            calls.append(slug)

        with (
            patch.object(main, "_deploy_nkn_slots", side_effect=nkn),
            patch.object(main, "_auto_deploy_one", side_effect=generic),
            patch.object(
                main,
                "_deploy_earnapp_nodes",
                AsyncMock(
                    return_value={
                        "deployed": [],
                        "verified": [],
                        "skipped": ["no_capacity"],
                        "pending": [],
                        "failed": [],
                    }
                ),
            ) as earnapp,
        ):
            await main._run_auto_deploy_sequence(
                7,
                {"nkn_beneficiary_address": "beneficiary"},
                ["earnfm", "iproyal"],
                delay_seconds=0,
            )

        assert calls == ["nkn", "earnfm", "iproyal"]
        earnapp.assert_awaited_once()
        assert 7 in main._NKN_AUTO_DEPLOY_DONE
        assert 7 in main._EARNAPP_AUTO_DEPLOY_DONE

    asyncio.run(run())


def test_heartbeat_auto_deploy_does_not_skip_provider_deployed_on_another_worker():
    async def run():
        main._WORKER_HEARTBEAT_STREAKS.clear()
        main._NKN_AUTO_DEPLOY_DONE.add(7)
        main._EARNAPP_AUTO_DEPLOY_DONE.add(7)
        services = [
            {
                "slug": "earnfm",
                "status": "active",
                "docker": {"image": "earnfm/earnfm-client"},
                "deploy": {},
            }
        ]
        with (
            patch.object(
                main.database,
                "get_config",
                AsyncMock(
                    return_value={
                        "cashpilot_auto_deploy_enabled": "true",
                        "cashpilot_autodeploy_round_generation": "1",
                        "cashpilot_autodeploy_worker_ids": "7",
                    }
                ),
            ),
            patch.object(
                main.database,
                "get_worker",
                AsyncMock(return_value={"id": 7, "name": "azure-worker", "key_confirmed": 1}),
            ),
            patch.object(main.database, "list_provider_instances", AsyncMock(return_value=[])),
            patch.object(main.catalog, "get_services", return_value=services),
            patch.object(main.database, "claim_rollout_round", AsyncMock(return_value="run-1")),
            patch.object(main, "_spawn") as spawn,
        ):
            await main._maybe_auto_deploy_after_heartbeat(7)
            await main._maybe_auto_deploy_after_heartbeat(7)
            await main._maybe_auto_deploy_after_heartbeat(7)

        spawn.assert_called_once()
        coroutine = spawn.call_args.args[0]
        coroutine.close()
        assert coroutine.cr_frame is None

    asyncio.run(run())


def test_heartbeat_auto_deploy_skips_unconfirmed_worker_key():
    async def run():
        main._WORKER_HEARTBEAT_STREAKS.clear()
        with (
            patch.object(
                main.database, "get_config", AsyncMock(return_value={"cashpilot_auto_deploy_enabled": "true"})
            ),
            patch.object(
                main.database, "get_worker", AsyncMock(return_value={"id": 7, "status": "online", "key_confirmed": 0})
            ),
            patch.object(main, "_spawn") as spawn,
        ):
            for _ in range(3):
                await main._maybe_auto_deploy_after_heartbeat(7)
        spawn.assert_not_called()


def test_heartbeat_auto_deploy_does_not_redeploy_authenticated_runtime_missing_from_db():
    async def run():
        main._WORKER_HEARTBEAT_STREAKS.clear()
        main._NKN_AUTO_DEPLOY_DONE.add(7)
        main._EARNAPP_AUTO_DEPLOY_DONE.add(7)
        services = [
            {
                "slug": "wipter",
                "status": "active",
                "docker": {"image": "wipter/image"},
                "deploy": {},
            }
        ]
        worker = {
            "id": 7,
            "name": "azure-worker",
            "status": "online",
            "key_confirmed": 1,
            "containers": json.dumps([{"slug": "wipter", "instance_slug": "wipter-proxy", "status": "running"}]),
        }
        with (
            patch.object(
                main.database,
                "get_config",
                AsyncMock(return_value={"cashpilot_auto_deploy_enabled": "true"}),
            ),
            patch.object(main.database, "get_worker", AsyncMock(return_value=worker)),
            patch.object(main.database, "list_provider_instances", AsyncMock(return_value=[])),
            patch.object(main.catalog, "get_services", return_value=services),
            patch.object(main, "_spawn") as spawn,
        ):
            for _ in range(3):
                await main._maybe_auto_deploy_after_heartbeat(7)
        spawn.assert_not_called()

    asyncio.run(run())


def test_verified_worker_url_rejects_unconfirmed_worker(monkeypatch):
    async def run():
        with pytest.raises(main.HTTPException) as exc:
            await main._get_verified_worker_url(
                {"status": "online", "url": "http://worker.example", "client_id": "w", "key_confirmed": 0}
            )
        assert exc.value.status_code == 409

    asyncio.run(run())
