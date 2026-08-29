from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app import main


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


def test_auto_deploy_skips_server_worker_by_default():
    assert (
        main._worker_allowed_for_auto_deploy(
            {"id": 1, "name": "cashpilot"}, {"cashpilot_autodeploy_include_server": ""}
        )
        is False
    )
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


def test_earnapp_auto_deploy_is_disabled_without_calling_the_runtime_lane():
    async def run():
        main._NKN_AUTO_DEPLOY_DONE.add(7)
        main._EARNAPP_AUTO_DEPLOY_DONE.discard(7)

        with patch.object(main, "_deploy_earnapp_nodes", AsyncMock()) as deploy:
            await main._run_auto_deploy_sequence(7, {}, [], delay_seconds=0)

        deploy.assert_not_awaited()
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


def test_auto_deploy_sequence_runs_nkn_and_catalog_providers_without_earnapp_runtime():
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
            patch.object(main, "_deploy_earnapp_nodes", AsyncMock()) as earnapp,
        ):
            await main._run_auto_deploy_sequence(
                7,
                {"nkn_beneficiary_address": "beneficiary"},
                ["earnfm", "iproyal"],
                delay_seconds=0,
            )

        assert calls == ["nkn", "earnfm", "iproyal"]
        earnapp.assert_not_awaited()
        assert 7 in main._NKN_AUTO_DEPLOY_DONE
        assert 7 in main._EARNAPP_AUTO_DEPLOY_DONE

    asyncio.run(run())
