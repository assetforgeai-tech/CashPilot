import asyncio
from unittest.mock import patch

from app import database


def test_reclaim_worker_resources_releases_all_worker_authority_once(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "reclaim.db"):
            await database.init_db()
            worker_id = await database.upsert_worker("lost-worker", "lost-worker", "http://worker")
            provider_id = await database.upsert_proxy_provider("Pool", "residential")
            proxy_id = (
                await database.upsert_proxy_endpoints_returning_ids(
                    provider_id,
                    [
                        {
                            "provider_proxy_id": "p1",
                            "host": "1.1.1.1",
                            "port": 80,
                            "status": "alive",
                            "exit_ip": "198.51.100.1",
                        }
                    ],
                )
            )[0]
            await database.save_provider_instance(
                "packetstream",
                "packet-1",
                worker_id=worker_id,
                mode="proxy",
                capacity_slot="proxy-01",
                proxy_id=proxy_id,
            )
            assert await database.lease_proxy_for_provider_instance("packetstream", worker_id, "packet-1")
            db = await database._get_db()
            try:
                await db.execute("UPDATE provider_instances SET status='running' WHERE instance_id='packet-1'")
                await db.execute(
                    "INSERT INTO nkn_wallets (wallet_fingerprint, folder_name, wallet_json_enc, wallet_pswd_enc, state, leased_to_worker_id, leased_to_client_id, wallet_assignment_version) VALUES ('nkn-1', 'nkn-1', '', '', 'LEASED', ?, 'nkn-slot-1', 1)",
                    (worker_id,),
                )
                await db.execute(
                    "INSERT INTO myst_wallets (wallet_fingerprint, raw_wallet_enc, state, leased_to_worker_id, leased_to_client_id, wallet_assignment_version) VALUES ('myst-1', '', 'LEASED', ?, 'myst-slot-1', 1)",
                    (worker_id,),
                )
                await db.commit()
            finally:
                await db.close()

            first = await database.reclaim_worker_resources(worker_id, "worker_lost", "token-1")
            second = await database.reclaim_worker_resources(worker_id, "worker_lost", "token-1")
            assert first["already_reclaimed"] is False
            assert second["already_reclaimed"] is True
            assert first["generation"] == 2
            assert (await database.list_provider_proxy_leases(provider_slug="packetstream"))[0]["released_at"]
            instance = await database.get_provider_instance("packet-1")
            assert instance["status"] == "retired"
            assert instance["worker_id"] is None
            assert instance["proxy_id"] is None
            assert instance["capacity_slot"] == ""
            db = await database._get_db()
            try:
                nkn = await (
                    await db.execute(
                        "SELECT state, leased_to_worker_id FROM nkn_wallets WHERE wallet_fingerprint='nkn-1'"
                    )
                ).fetchone()
                myst = await (
                    await db.execute(
                        "SELECT state, leased_to_worker_id FROM myst_wallets WHERE wallet_fingerprint='myst-1'"
                    )
                ).fetchone()
                assert dict(nkn) == {"state": "AVAILABLE", "leased_to_worker_id": None}
                assert dict(myst) == {"state": "AVAILABLE", "leased_to_worker_id": None}
            finally:
                await db.close()

    asyncio.run(run())


def test_reclaim_requires_non_empty_idempotency_token(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "reclaim.db"):
            await database.init_db()
            worker_id = await database.upsert_worker("worker", "worker", "http://worker")
            assert await database.reclaim_worker_resources(worker_id, "worker_lost", "") == {
                "reclaimed": False,
                "reason": "missing_token",
            }

    asyncio.run(run())
