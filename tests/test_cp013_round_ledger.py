"""CP-013 diagnostic rounds are one-shot, durable, and redacted."""

import asyncio
from unittest.mock import AsyncMock, patch

from app import database, main


def test_round_claim_is_atomic_and_survives_restart(tmp_path):
    async def run():
        with patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"), patch.object(database, "DB_DIR", tmp_path):
            await database.init_db()
            worker_id = await database.upsert_worker("round-worker", "round-worker", "http://worker")
            await database.confirm_worker_key("round-worker")
            claims = await asyncio.gather(
                *[database.claim_rollout_round(worker_id, 1, ["nkn", "earnfm", "earnapp"]) for _ in range(5)]
            )
            run_id = next(value for value in claims if value)
            assert sum(value is not None for value in claims) == 1
            await database.record_rollout_outcome(run_id, "earnfm", "attempted")
            await database.record_rollout_outcome(run_id, "earnfm", "failed", "RuntimeError")
            await database.finish_rollout_round(run_id)
            await database.close_shared()
            assert await database.claim_rollout_round(worker_id, 1, ["earnfm"]) is None
            saved = await database.get_rollout_round(run_id)
            assert saved["generation"] == 1
            assert saved["status"] == "completed"
            assert saved["desired_count"] == 3
            assert saved["failed_count"] == 1
            assert saved["attempted_count"] == 1
            assert [(row["slug"], row["status"]) for row in saved["events"]] == [
                ("nkn", "planned"),
                ("earnfm", "planned"),
                ("earnapp", "planned"),
                ("earnfm", "attempted"),
                ("earnfm", "failed"),
            ]
            assert await database.claim_rollout_round(worker_id, 2, ["earnfm"]) != run_id
            await database.close_shared()

    asyncio.run(run())


def test_round_outcome_is_single_attempt_and_single_terminal_result(tmp_path):
    async def run():
        import pytest

        with patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"), patch.object(database, "DB_DIR", tmp_path):
            await database.init_db()
            worker_id = await database.upsert_worker("round-worker", "round-worker", "http://worker")
            run_id = await database.claim_rollout_round(worker_id, 1, ["earnfm"])
            await database.record_rollout_outcome(run_id, "earnfm", "attempted")
            with pytest.raises(ValueError, match="not active or slug was not planned"):
                await database.record_rollout_outcome(run_id, "earnfm", "attempted")
            await database.record_rollout_outcome(run_id, "earnfm", "failed", "RuntimeError")
            with pytest.raises(ValueError, match="not active or slug was not planned"):
                await database.record_rollout_outcome(run_id, "earnfm", "failed", "RuntimeError")
            await database.close_shared()

    asyncio.run(run())


def test_incomplete_round_blocks_same_and_new_generation_after_restart(tmp_path):
    async def run():
        with patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"), patch.object(database, "DB_DIR", tmp_path):
            await database.init_db()
            worker_id = await database.upsert_worker("round-worker", "round-worker", "http://worker")
            run_id = await database.claim_rollout_round(worker_id, 1, ["earnfm"])
            await database.record_rollout_outcome(run_id, "earnfm", "attempted")
            await database.close_shared()

            # A process restart must leave the incomplete round visible and fenced.
            assert await database.claim_rollout_round(worker_id, 1, ["earnfm"]) is None
            assert await database.claim_rollout_round(worker_id, 2, ["earnfm"]) is None
            saved = await database.get_rollout_round(run_id)
            assert saved["status"] == "running"
            assert saved["attempted_count"] == 1
            await database.close_shared()

    asyncio.run(run())


def test_heartbeat_requires_generation_and_does_not_retry_failed_round(tmp_path):
    async def run():
        with patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"), patch.object(database, "DB_DIR", tmp_path):
            await database.init_db()
            worker_id = await database.upsert_worker("round-worker", "round-worker", "http://worker")
            await database.confirm_worker_key("round-worker")
            main._WORKER_HEARTBEAT_STREAKS.clear()
            main._NKN_AUTO_DEPLOY_DONE.add(worker_id)
            main._EARNAPP_AUTO_DEPLOY_DONE.add(worker_id)
            calls = []

            async def deploy(_worker_id, slug):
                calls.append(slug)
                if slug == "bad":
                    raise RuntimeError("token=never-store-this")

            config = {
                "cashpilot_auto_deploy_enabled": "true",
                "cashpilot_autodeploy_round_generation": "1",
                "cashpilot_autodeploy_worker_ids": str(worker_id),
            }
            services = [
                {"slug": slug, "status": "active", "docker": {"image": "fixture"}, "deploy": {}}
                for slug in ("bad", "next")
            ]
            spawned = []
            with (
                patch.object(database, "get_config", AsyncMock(return_value=config)),
                patch.object(
                    database,
                    "get_worker",
                    AsyncMock(return_value={"id": worker_id, "name": "round-worker", "key_confirmed": 1}),
                ),
                patch.object(main.catalog, "get_services", return_value=services),
                patch.object(main, "_auto_deploy_credentials_ready", return_value=True),
                patch.object(main, "_auto_deploy_one", side_effect=deploy),
                patch.object(main, "_spawn", side_effect=spawned.append),
            ):
                for _ in range(3):
                    await main._maybe_auto_deploy_after_heartbeat(worker_id)
                assert len(spawned) == 1
                await spawned.pop()
                main._WORKER_HEARTBEAT_STREAKS.clear()  # Simulate process restart.
                for _ in range(3):
                    await main._maybe_auto_deploy_after_heartbeat(worker_id)
                assert spawned == []
                config["cashpilot_autodeploy_round_generation"] = "2"
                await main._maybe_auto_deploy_after_heartbeat(worker_id)
                assert len(spawned) == 1
                await spawned.pop()
            assert calls == ["bad", "next", "bad", "next"]
            db = await database._get_db()
            try:
                rows = await (await db.execute("SELECT run_id FROM rollout_runs ORDER BY generation")).fetchall()
            finally:
                await db.close()
            assert len(rows) == 2
            first = await database.get_rollout_round(rows[0]["run_id"])
            assert first["failure_count"] == 1
            bad_events = [row["status"] for row in first["events"] if row["slug"] == "bad"]
            assert bad_events == ["planned", "attempted", "failed"]
            assert "never-store-this" not in str(first)
            await database.close_shared()

    asyncio.run(run())


def test_ledger_write_failure_stops_sequential_dispatch(tmp_path):
    async def run():
        with patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"), patch.object(database, "DB_DIR", tmp_path):
            await database.init_db()
            worker_id = await database.upsert_worker("round-worker", "round-worker", "http://worker")
            run_id = await database.claim_rollout_round(worker_id, 1, ["first", "second"])
            main._NKN_AUTO_DEPLOY_DONE.add(worker_id)
            main._EARNAPP_AUTO_DEPLOY_DONE.add(worker_id)
            calls = []

            async def deploy(_worker_id, slug):
                calls.append(slug)

            with (
                patch.object(main, "_auto_deploy_one", side_effect=deploy),
                patch.object(database, "record_rollout_outcome", AsyncMock(side_effect=OSError("db unavailable"))),
            ):
                try:
                    await main._run_auto_deploy_sequence(
                        worker_id, {}, ["first", "second"], delay_seconds=0, run_id=run_id
                    )
                except OSError:
                    pass
                else:
                    raise AssertionError("ledger failure must stop dispatch")
            assert calls == []
            assert (await database.get_rollout_round(run_id))["status"] == "running"
            await database.close_shared()

    asyncio.run(run())


def test_round_requires_explicit_single_worker_scope_and_confirmed_key(tmp_path):
    async def run():
        with patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"), patch.object(database, "DB_DIR", tmp_path):
            await database.init_db()
            worker_id = await database.upsert_worker("round-worker", "round-worker", "http://worker")
            main._WORKER_HEARTBEAT_STREAKS.clear()
            main._NKN_AUTO_DEPLOY_DONE.add(worker_id)
            main._EARNAPP_AUTO_DEPLOY_DONE.add(worker_id)
            config = {
                "cashpilot_auto_deploy_enabled": "true",
                "cashpilot_autodeploy_round_generation": "1",
            }
            services = [{"slug": "earnfm", "status": "active", "docker": {"image": "fixture"}}]
            with (
                patch.object(database, "get_config", AsyncMock(return_value=config)),
                patch.object(
                    database,
                    "get_worker",
                    AsyncMock(return_value={"id": worker_id, "name": "round-worker", "key_confirmed": 0}),
                ),
                patch.object(main.catalog, "get_services", return_value=services),
                patch.object(main, "_auto_deploy_credentials_ready", return_value=True),
                patch.object(database, "claim_rollout_round", AsyncMock(side_effect=["run-1", None, None])),
                patch.object(main, "_spawn") as spawn,
            ):
                for _ in range(3):
                    await main._maybe_auto_deploy_after_heartbeat(worker_id)
                spawn.assert_not_called()
                config["cashpilot_autodeploy_worker_ids"] = f"{worker_id},{worker_id + 1}"
                with patch.object(
                    database,
                    "get_worker",
                    AsyncMock(return_value={"id": worker_id, "name": "round-worker", "key_confirmed": 1}),
                ):
                    for _ in range(3):
                        await main._maybe_auto_deploy_after_heartbeat(worker_id)
                spawn.assert_not_called()
                config["cashpilot_autodeploy_worker_ids"] = str(worker_id)
                await main._maybe_auto_deploy_after_heartbeat(worker_id)
                spawn.assert_not_called()
                with patch.object(
                    database,
                    "get_worker",
                    AsyncMock(return_value={"id": worker_id, "name": "round-worker", "key_confirmed": 1}),
                ):
                    for _ in range(3):
                        await main._maybe_auto_deploy_after_heartbeat(worker_id)
                spawn.assert_called_once()
                spawn.call_args.args[0].close()
            await database.close_shared()

    asyncio.run(run())


def test_round_config_validation_rejects_invalid_generation_or_scope():
    import pytest

    with pytest.raises(ValueError, match="cashpilot_autodeploy_round_generation"):
        main._validate_config_update({"cashpilot_autodeploy_round_generation": "0"})
    with pytest.raises(ValueError, match="cashpilot_autodeploy_round_generation"):
        main._validate_config_update({"cashpilot_autodeploy_round_generation": "²"})
    with pytest.raises(ValueError, match="cashpilot_autodeploy_round_generation"):
        main._validate_config_update({"cashpilot_autodeploy_round_generation": "9" * 5000})
    with pytest.raises(ValueError, match="cashpilot_autodeploy_worker_ids"):
        main._validate_config_update({"cashpilot_autodeploy_worker_ids": "7,not-an-id"})
    with pytest.raises(ValueError, match="cashpilot_autodeploy_worker_ids"):
        main._validate_config_update({"cashpilot_autodeploy_worker_ids": "7,007"})
