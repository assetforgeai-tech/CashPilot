import asyncio
from unittest.mock import patch

import pytest

from app import database


def test_probe_state_migration_preserves_existing_proxy_lease_and_index(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
            await database.init_db()
            db = await database._get_db()
            await db.execute(
                "INSERT INTO proxy_endpoints(id, endpoint, host, port, protocol, status, exit_ip) VALUES "
                "(1, 'http://p:1', 'p', 1, 'http', 'dead', '203.0.113.1'), "
                "(2, 'http://p:2', 'p', 2, 'http', 'alive', '203.0.113.2')"
            )
            await db.commit()
            await database.init_db()
            assert (await (await db.execute("SELECT id FROM proxy_endpoints WHERE id=1")).fetchone())["id"] == 1
            for table in ("proxy_probe_state", "proxy_rotation_requests"):
                assert await (
                    await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
                ).fetchone()
            assert await (
                await db.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_provider_proxy_leases_active_proxy'"
                )
            ).fetchone()
            await db.close()
            await database.close_shared()

    asyncio.run(run())


def test_rotation_request_binding_fence_migration_preserves_history_safely(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
            await database.init_db()
            db = await database._get_db()
            await db.execute("INSERT INTO workers(id, client_id) VALUES (1, 'worker-1')")
            await db.execute(
                "INSERT INTO proxy_endpoints(id, endpoint, host, port, protocol) VALUES (1, 'http://p:1', 'p', 1, 'http')"
            )
            await db.execute("DROP INDEX IF EXISTS idx_proxy_rotation_requests_claim")
            await db.execute("DROP TABLE proxy_rotation_requests")
            await db.execute(
                """
                CREATE TABLE proxy_rotation_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    proxy_id INTEGER NOT NULL,
                    probe_generation INTEGER NOT NULL,
                    provider_slug TEXT NOT NULL,
                    worker_id INTEGER NOT NULL,
                    instance_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at TEXT NOT NULL,
                    lease_token TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            await db.execute(
                """
                INSERT INTO proxy_rotation_requests
                    (id, proxy_id, probe_generation, provider_slug, worker_id, instance_id,
                     state, available_at, created_at, updated_at)
                VALUES (9, 1, 3, 'earnfm', 1, 'node-1', 'pending',
                        datetime('now'), datetime('now'), datetime('now'))
                """
            )
            await db.commit()
            await db.close()
            await database.close_shared()
            await database.init_db()
            db = await database._get_db()
            columns = {
                row["name"] for row in await (await db.execute("PRAGMA table_info(proxy_rotation_requests)")).fetchall()
            }
            assert {"lease_id", "assignment_version"} <= columns
            row = await (await db.execute("SELECT state, reason FROM proxy_rotation_requests WHERE id=9")).fetchone()
            assert row["state"] == "cancelled" and row["reason"] == "migration_fence"
            assert await (
                await db.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_proxy_rotation_requests_claim'"
                )
            ).fetchone()
            await db.close()
            await database.close_shared()

    asyncio.run(run())


def test_only_generic_probe_controls_liveness_and_never_overwrites_confirmed_egress(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
            await database.init_db()
            db = await database._get_db()
            await db.execute(
                "INSERT INTO proxy_endpoints(id, endpoint, host, port, protocol, status, exit_ip) "
                "VALUES (1, 'http://p:1', 'p', 1, 'http', 'alive', '203.0.113.1')"
            )
            await db.commit()
            with pytest.raises(ValueError, match="generic"):
                await database.record_proxy_probe_transition(
                    1, {"status": "failed", "profile": "earnapp_wss"}, generation=1
                )
            with pytest.raises(ValueError, match="reason"):
                await database.record_proxy_probe_transition(
                    1, {"status": "failed", "reason": "password: secret"}, generation=1
                )
            result = await database.record_proxy_probe_transition(
                1, {"status": "alive", "exit_ip": "198.51.100.9", "evidence": {"password": "secret"}}, generation=1
            )
            assert result["state"] == "unknown"  # egress mismatch is not proof of a safe route
            assert (await (await db.execute("SELECT exit_ip FROM proxy_endpoints WHERE id=1")).fetchone())[
                "exit_ip"
            ] == "203.0.113.1"
            evidence = await (
                await db.execute("SELECT evidence_json FROM proxy_probe_results WHERE proxy_id=1")
            ).fetchone()
            assert "secret" not in evidence["evidence_json"]
            await db.close()
            await database.close_shared()

    asyncio.run(run())


def test_recovered_or_released_proxy_request_is_cancelled_before_claim(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
            await database.init_db()
            db = await database._get_db()
            await db.execute("INSERT INTO workers(id, client_id) VALUES (1, 'worker-1')")
            await db.execute(
                "INSERT INTO proxy_endpoints(id, endpoint, host, port, protocol) VALUES (1, 'http://p:1', 'p', 1, 'http')"
            )
            await db.execute(
                "INSERT INTO provider_proxy_leases(provider_slug, worker_id, instance_id, proxy_id) VALUES ('earnfm', 1, 'node-1', 1)"
            )
            await db.commit()
            for generation in (1, 2, 3):
                await database.record_proxy_probe_transition(1, {"status": "failed"}, generation=generation)
            assert await database.enqueue_proxy_rotation_requests(1, 3) == 1
            await database.record_proxy_probe_transition(1, {"status": "alive"}, generation=4)
            assert await database.claim_proxy_rotation_request("2099-01-01 00:00:00") is None
            row = await (await db.execute("SELECT state FROM proxy_rotation_requests WHERE proxy_id=1")).fetchone()
            assert row["state"] == "cancelled"
            await db.close()
            await database.close_shared()

    asyncio.run(run())


def test_probe_transition_deduplicates_generation_and_requires_three_cycles(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
            await database.init_db()
            db = await database._get_db()
            await db.execute(
                "INSERT INTO proxy_endpoints(id, endpoint, host, port, protocol, status, exit_ip) VALUES (1, 'http://p:1', 'p', 1, 'http', 'alive', '203.0.113.1')"
            )
            await db.commit()
            result = {"status": "failed", "reason": "timeout"}
            first = await database.record_proxy_probe_transition(1, result, generation=1)
            assert first["state"] == "suspect" and first["consecutive_failures"] == 1
            duplicate = await database.record_proxy_probe_transition(1, result, generation=1)
            assert duplicate["deduplicated"] is True
            assert duplicate["state"] == first["state"]
            assert duplicate["consecutive_failures"] == first["consecutive_failures"]
            second = await database.record_proxy_probe_transition(1, result, generation=2)
            assert second["state"] == "suspect" and second["consecutive_failures"] == 2
            inconclusive = await database.record_proxy_probe_transition(1, {"status": "inconclusive"}, generation=3)
            assert inconclusive["consecutive_failures"] == 2
            third = await database.record_proxy_probe_transition(1, result, generation=4)
            assert third["state"] == "dead" and third["consecutive_failures"] == 3
            proxy = await (await db.execute("SELECT status, exit_ip FROM proxy_endpoints WHERE id=1")).fetchone()
            assert proxy["status"] == "dead" and proxy["exit_ip"] == "203.0.113.1"
            recovered = await database.record_proxy_probe_transition(1, {"status": "alive"}, generation=5)
            assert recovered["state"] == "alive" and recovered["consecutive_failures"] == 0
            assert (
                await (await db.execute("SELECT COUNT(*) AS n FROM proxy_probe_results WHERE proxy_id=1")).fetchone()
            )["n"] == 5
            await db.close()
            await database.close_shared()

    asyncio.run(run())


def test_shared_probe_outage_is_inconclusive_not_upstream_failure(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
            await database.init_db()
            db = await database._get_db()
            await db.execute(
                "INSERT INTO proxy_endpoints(id, endpoint, host, port, protocol) VALUES (1, 'http://p:1', 'p', 1, 'http')"
            )
            await db.commit()
            result = await database.record_proxy_probe_transition(
                1, {"status": "failed", "reason": "control_plane_unavailable"}, generation=1
            )
            assert result["state"] == "unknown" and result["consecutive_failures"] == 0
            result = await database.record_proxy_probe_transition(
                1, {"status": "failed", "reason": "shared_dns_outage"}, generation=2
            )
            assert result["consecutive_failures"] == 0
            await db.close()
            await database.close_shared()

    asyncio.run(run())


def test_rotation_requests_dedupe_active_instance_and_legacy_assignment_without_release(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
            await database.init_db()
            db = await database._get_db()
            await db.execute("INSERT INTO workers(id, client_id) VALUES (1, 'worker-1'), (2, 'worker-2')")
            await db.execute(
                "INSERT INTO proxy_endpoints(id, endpoint, host, port, protocol, status, exit_ip) VALUES (1, 'http://p:1', 'p', 1, 'http', 'alive', '203.0.113.1')"
            )
            await db.execute(
                "INSERT INTO provider_proxy_leases(provider_slug, worker_id, instance_id, proxy_id, exit_ip) VALUES ('earnfm', 1, 'node-1', 1, '203.0.113.1')"
            )
            await db.execute(
                "INSERT INTO proxy_assignments(worker_id, proxy_id, mode, assignment_version) VALUES (2, 1, 'proxy', 4)"
            )
            await db.commit()
            for generation in (1, 2, 3):
                await database.record_proxy_probe_transition(
                    1, {"status": "failed", "reason": "timeout"}, generation=generation
                )
            assert await database.enqueue_proxy_rotation_requests(1, 3) == 2
            assert await database.enqueue_proxy_rotation_requests(1, 3) == 0
            assert await database.enqueue_proxy_rotation_requests(1, 2) == 0
            lease = await (
                await db.execute("SELECT released_at, proxy_id FROM provider_proxy_leases WHERE instance_id='node-1'")
            ).fetchone()
            assert lease["released_at"] is None and lease["proxy_id"] == 1
            rows = await (
                await db.execute(
                    "SELECT provider_slug, instance_id, state FROM proxy_rotation_requests ORDER BY worker_id"
                )
            ).fetchall()
            assert [(row["provider_slug"], row["instance_id"], row["state"]) for row in rows] == [
                ("earnfm", "node-1", "pending"),
                ("legacy", "legacy-worker-2", "pending"),
            ]
            await db.close()
            await database.close_shared()

    asyncio.run(run())


def test_rotation_claim_recovery_and_fenced_completion(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
            await database.init_db()
            db = await database._get_db()
            await db.execute("INSERT INTO workers(id, client_id) VALUES (1, 'worker-1')")
            await db.execute(
                "INSERT INTO proxy_endpoints(id, endpoint, host, port, protocol) VALUES (1, 'http://p:1', 'p', 1, 'http')"
            )
            await db.execute(
                "INSERT INTO provider_proxy_leases(provider_slug, worker_id, instance_id, proxy_id) VALUES ('earnfm', 1, 'node-1', 1)"
            )
            await db.commit()
            for generation in (1, 2, 3):
                await database.record_proxy_probe_transition(
                    1, {"status": "failed", "reason": "timeout"}, generation=generation
                )
            assert await database.enqueue_proxy_rotation_requests(1, 3) == 1
            first = await database.claim_proxy_rotation_request("2026-09-24 00:00:00")
            assert first["state"] == "running" and first["lease_token"]
            assert await database.claim_proxy_rotation_request("2026-09-24 00:00:01") is None
            recovered = await database.claim_proxy_rotation_request("2026-09-24 00:02:00")
            assert recovered["id"] == first["id"] and recovered["lease_token"] != first["lease_token"]
            assert not await database.complete_proxy_rotation_request(
                first["id"], "succeeded", lease_token=first["lease_token"]
            )
            assert await database.complete_proxy_rotation_request(
                recovered["id"], "failed", error="apply_failed", lease_token=recovered["lease_token"]
            )
            row = await (
                await db.execute("SELECT state, attempts FROM proxy_rotation_requests WHERE id=?", (first["id"],))
            ).fetchone()
            assert row["state"] == "pending" and row["attempts"] == 1
            lease = await (
                await db.execute("SELECT released_at, proxy_id FROM provider_proxy_leases WHERE instance_id='node-1'")
            ).fetchone()
            assert lease["released_at"] is None and lease["proxy_id"] == 1
            await db.close()
            await database.close_shared()

    asyncio.run(run())


def test_rotation_request_fences_probe_generation_and_reacquired_lease(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
            await database.init_db()
            db = await database._get_db()
            await db.execute("INSERT INTO workers(id, client_id) VALUES (1, 'worker-1')")
            await db.execute(
                "INSERT INTO proxy_endpoints(id, endpoint, host, port, protocol) VALUES (1, 'http://p:1', 'p', 1, 'http')"
            )
            await db.execute(
                "INSERT INTO provider_proxy_leases(id, provider_slug, worker_id, instance_id, proxy_id) "
                "VALUES (10, 'earnfm', 1, 'node-1', 1)"
            )
            await db.commit()
            for generation in (1, 2, 3):
                await database.record_proxy_probe_transition(1, {"status": "failed"}, generation=generation)
            assert await database.enqueue_proxy_rotation_requests(1, 3) == 1

            await database.record_proxy_probe_transition(1, {"status": "failed"}, generation=4)
            # A newer probe generation fences the old request before claim.
            assert await database.claim_proxy_rotation_request("2099-01-01 00:00:00") is None
            row = await (await db.execute("SELECT state, reason FROM proxy_rotation_requests WHERE id=1")).fetchone()
            assert row["state"] == "cancelled" and row["reason"] == "stale_binding"
            await database.record_proxy_probe_transition(1, {"status": "alive"}, generation=5)

            await db.execute("UPDATE provider_proxy_leases SET released_at = datetime('now') WHERE id = 10")
            await db.execute(
                "INSERT INTO provider_proxy_leases(provider_slug, worker_id, instance_id, proxy_id) "
                "VALUES ('earnfm', 1, 'node-1', 1)"
            )
            await db.commit()
            for generation in (6, 7, 8):
                await database.record_proxy_probe_transition(1, {"status": "failed"}, generation=generation)
            assert await database.enqueue_proxy_rotation_requests(1, 8) == 1
            request = await database.claim_proxy_rotation_request("2099-01-01 00:00:00")
            assert request is not None
            assert request["lease_id"] != 10
            assert request["probe_generation"] == 8
            await db.close()
            await database.close_shared()

    asyncio.run(run())


def test_rotation_claim_serializes_all_requests_for_one_worker(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
            await database.init_db()
            db = await database._get_db()
            await db.execute("INSERT INTO workers(id, client_id) VALUES (1, 'worker-1')")
            await db.execute(
                "INSERT INTO proxy_endpoints(id, endpoint, host, port, protocol) VALUES "
                "(1, 'http://p1:1', 'p1', 1, 'http'), (2, 'http://p2:2', 'p2', 2, 'http')"
            )
            await db.execute(
                "INSERT INTO provider_proxy_leases(provider_slug, worker_id, instance_id, proxy_id) VALUES "
                "('earnfm', 1, 'node-1', 1), ('repocket', 1, 'node-2', 2)"
            )
            await db.commit()
            for proxy in (1, 2):
                for generation in (1, 2, 3):
                    await database.record_proxy_probe_transition(proxy, {"status": "failed"}, generation=generation)
                assert await database.enqueue_proxy_rotation_requests(proxy, 3) == 1
            first = await database.claim_proxy_rotation_request("2026-09-24 00:00:00")
            assert first is not None
            assert await database.claim_proxy_rotation_request("2026-09-24 00:00:01") is None
            await db.close()
            await database.close_shared()

    asyncio.run(run())


def test_probe_transition_rejects_secret_like_fields_and_invalid_measurements(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
            await database.init_db()
            db = await database._get_db()
            await db.execute(
                "INSERT INTO proxy_endpoints(id, endpoint, host, port, protocol) VALUES (1, 'http://p:1', 'p', 1, 'http')"
            )
            await db.commit()
            for field in ("verdict", "eligibility", "probe_version"):
                with pytest.raises(ValueError, match="credentials"):
                    await database.record_proxy_probe_transition(
                        1, {"status": "failed", field: "token=secret"}, generation=1
                    )
            with pytest.raises(ValueError, match="IP"):
                await database.record_proxy_probe_transition(
                    1, {"status": "alive", "exit_ip": "not-an-ip"}, generation=2
                )
            with pytest.raises(ValueError, match="latency"):
                await database.record_proxy_probe_transition(1, {"status": "alive", "latency_ms": -1}, generation=3)
            with pytest.raises(ValueError, match="reason"):
                await database.record_proxy_probe_transition(
                    1, {"status": "failed", "reason": "http://user:pass@proxy.invalid"}, generation=4
                )
            await db.close()
            await database.close_shared()

    asyncio.run(run())


def test_rotation_request_rejects_rebound_lease_and_legacy_assignment(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
            await database.init_db()
            db = await database._get_db()
            await db.execute("INSERT INTO workers(id, client_id) VALUES (1, 'worker-1'), (2, 'worker-2')")
            await db.execute(
                "INSERT INTO proxy_endpoints(id, endpoint, host, port, protocol) VALUES (1, 'http://p:1', 'p', 1, 'http')"
            )
            await db.execute(
                "INSERT INTO provider_proxy_leases(provider_slug, worker_id, instance_id, proxy_id) VALUES ('earnfm', 1, 'node-1', 1)"
            )
            await db.execute("INSERT INTO proxy_assignments(worker_id, proxy_id, assignment_version) VALUES (2, 1, 3)")
            await db.commit()
            for generation in (1, 2, 3):
                await database.record_proxy_probe_transition(1, {"status": "failed"}, generation=generation)
            assert await database.enqueue_proxy_rotation_requests(1, 3) == 2
            await db.execute(
                "UPDATE provider_proxy_leases SET released_at = datetime('now') WHERE instance_id = 'node-1'"
            )
            await db.execute(
                "INSERT INTO provider_proxy_leases(provider_slug, worker_id, instance_id, proxy_id) VALUES ('earnfm', 1, 'node-1', 1)"
            )
            await db.execute("UPDATE proxy_assignments SET assignment_version = 4 WHERE worker_id = 2")
            await db.commit()
            assert await database.claim_proxy_rotation_request("2099-01-01 00:00:00") is None
            rows = await (await db.execute("SELECT state, reason FROM proxy_rotation_requests ORDER BY id")).fetchall()
            assert all(row["state"] == "cancelled" and row["reason"] == "stale_binding" for row in rows)
            await db.close()
            await database.close_shared()

    asyncio.run(run())


def test_rotation_completion_requires_cas_replacement_not_only_a_token(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
            await database.init_db()
            db = await database._get_db()
            await db.execute("INSERT INTO workers(id, client_id) VALUES (1, 'worker-1')")
            await db.execute(
                "INSERT INTO proxy_endpoints(id, endpoint, host, port, protocol, status, exit_ip) VALUES "
                "(1, 'http://p:1', 'p', 1, 'http', 'dead', '203.0.113.1'), "
                "(2, 'http://p:2', 'p', 2, 'http', 'alive', '203.0.113.2')"
            )
            await db.execute(
                "INSERT INTO provider_proxy_leases(provider_slug, worker_id, instance_id, proxy_id) VALUES ('earnfm', 1, 'node-1', 1)"
            )
            await db.commit()
            for generation in (1, 2, 3):
                await database.record_proxy_probe_transition(1, {"status": "failed"}, generation=generation)
            await database.enqueue_proxy_rotation_requests(1, 3)
            request = await database.claim_proxy_rotation_request("2026-09-24 00:00:00")
            assert not await database.complete_proxy_rotation_request(
                request["id"], "succeeded", lease_token=request["lease_token"]
            )
            await db.execute(
                "UPDATE provider_proxy_leases SET proxy_id=2, exit_ip='203.0.113.2' WHERE id=?",
                (request["lease_id"],),
            )
            await db.commit()
            assert await database.complete_proxy_rotation_request(
                request["id"],
                "succeeded",
                lease_token=request["lease_token"],
                replacement_committed=True,
            )
            row = await (
                await db.execute("SELECT state FROM proxy_rotation_requests WHERE id=?", (request["id"],))
            ).fetchone()
            assert row["state"] == "succeeded"
            await db.close()
            await database.close_shared()

    asyncio.run(run())


def test_new_probe_generation_fences_running_rotation_completion(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
            await database.init_db()
            db = await database._get_db()
            await db.execute("INSERT INTO workers(id, client_id) VALUES (1, 'worker-1')")
            await db.execute(
                "INSERT INTO proxy_endpoints(id, endpoint, host, port, protocol) VALUES (1, 'http://p:1', 'p', 1, 'http')"
            )
            await db.execute(
                "INSERT INTO provider_proxy_leases(provider_slug, worker_id, instance_id, proxy_id) "
                "VALUES ('earnfm', 1, 'node-1', 1)"
            )
            await db.commit()
            for generation in (1, 2, 3):
                await database.record_proxy_probe_transition(1, {"status": "failed"}, generation=generation)
            await database.enqueue_proxy_rotation_requests(1, 3)
            request = await database.claim_proxy_rotation_request("2026-09-24 00:00:00")
            await database.record_proxy_probe_transition(1, {"status": "failed"}, generation=4)
            assert not await database.complete_proxy_rotation_request(
                request["id"], "failed", error="apply_failed", lease_token=request["lease_token"]
            )
            await db.close()
            await database.close_shared()

    asyncio.run(run())
