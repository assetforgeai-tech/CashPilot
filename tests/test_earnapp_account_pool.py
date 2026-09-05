from __future__ import annotations

import asyncio
import base64
import json
from unittest.mock import patch

import pytest

from app import database, earnapp_accounts, earnapp_recovery


def _jwt(exp: int) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"{header}.{payload}.signature"


def _payload(
    profile_key: str,
    email: str,
    *,
    auth_method: str = "google",
    token_exp: int = 1_900_000_000,
    cookie_exp: float = 1_900_000_100.0,
) -> dict[str, object]:
    return {
        "profile_key": profile_key,
        "account_name": email,
        "email": email,
        "auth_method": auth_method,
        "cookies": {
            "auth": {"value": "1"},
            "auth-method": {"value": auth_method},
            "oauth-refresh-token": {"value": _jwt(token_exp), "expiration_date": cookie_exp},
            "xsrf-token": {"value": f"xsrf-{profile_key}", "expiration_date": cookie_exp + 100},
        },
    }


async def _seed_proxy_for_account_delete(database_module, provider_id: int, suffix: int = 20) -> int:
    (proxy_id,) = await database_module.upsert_proxy_endpoints_returning_ids(
        provider_id,
        [
            {
                "provider_proxy_id": f"runtime-proxy-{suffix}",
                "endpoint": f"proxy-{suffix}.example:1080",
                "host": f"proxy-{suffix}.example",
                "port": 1080,
                "protocol": "socks5",
                "status": "alive",
                "exit_ip": f"198.51.100.{suffix}",
                "ip_type": "residential",
                "country_code": "VN",
            }
        ],
    )
    await database_module.update_proxy_endpoint_intelligence(
        proxy_id,
        {
            "ip_type": "residential",
            "ip_type_source": "test",
            "ip_type_confidence": "high",
            "country_code": "VN",
            "country_name": "Vietnam",
            "geo_source": "test",
            "geo_confidence": "high",
        },
    )
    await database_module.save_proxy_probe_result(
        proxy_id,
        profile="earnapp_wss",
        probe_status="alive",
        verdict="CID_SET",
        eligibility="eligible",
        reason="",
        exit_ip=f"198.51.100.{suffix}",
        latency_ms=10,
        probe_version="test",
    )
    return proxy_id


def test_import_encrypts_credentials_and_lists_only_masked_metadata(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account_id = await earnapp_accounts.import_account(_payload("profile-40", "owner@example.com"))

            db = await database._get_db()
            row = await (await db.execute("SELECT * FROM earnapp_accounts WHERE id = ?", (account_id,))).fetchone()
            assert row["credentials_enc"].startswith("enc:")
            assert "xsrf-profile-40" not in row["credentials_enc"]

            public = await earnapp_accounts.list_accounts()
            assert public == [
                {
                    "id": account_id,
                    "profile_key": "profile-40",
                    "account_name": "owner@example.com",
                    "email": "owner@example.com",
                    "auth_method": "google",
                    "state": "ACTIVE",
                    "token_expires_at": "2030-03-17T17:46:40+00:00",
                    "cookie_expires_at": "2030-03-17T17:48:20+00:00",
                    "assigned_nodes": 0,
                    "credentials_present": {
                        "auth": True,
                        "auth-method": True,
                        "oauth-refresh-token": True,
                        "xsrf-token": True,
                    },
                    "created_at": public[0]["created_at"],
                    "updated_at": public[0]["updated_at"],
                }
            ]
            serialized = json.dumps(public)
            assert "xsrf-profile-40" not in serialized
            assert 'oauth-refresh-token": "ey' not in serialized
            assert "credentials_enc" not in serialized

            private = await earnapp_accounts.get_account_credentials(account_id)
            assert private is not None
            assert private["cookies"]["xsrf-token"] == "xsrf-profile-40"

    asyncio.run(run())


async def _seed_legacy_earnapp_schema(
    db,
    accounts: list[dict[str, object]],
    leases: list[dict[str, object]] | None = None,
    *,
    include_current_children: bool = False,
) -> None:
    await db.executescript(
        """
        CREATE TABLE earnapp_accounts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            account_name TEXT NOT NULL UNIQUE,
            cookies_enc  TEXT NOT NULL,
            state        TEXT NOT NULL DEFAULT 'VALID',
            created_at   TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE earnapp_account_leases (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id        INTEGER NOT NULL,
            worker_id         INTEGER NOT NULL,
            instance_id       TEXT NOT NULL,
            state             TEXT NOT NULL DEFAULT 'ACTIVE',
            leased_at         TEXT NOT NULL DEFAULT (datetime('now')),
            last_heartbeat_at TEXT,
            released_at       TEXT,
            release_reason    TEXT NOT NULL DEFAULT '',
            UNIQUE(worker_id, instance_id),
            FOREIGN KEY(account_id) REFERENCES earnapp_accounts(id) ON DELETE CASCADE
        );
        """
    )
    if include_current_children:
        await db.executescript(
            """
            CREATE TABLE workers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'online',
                containers TEXT NOT NULL DEFAULT '[]',
                apps TEXT NOT NULL DEFAULT '[]',
                system_info TEXT NOT NULL DEFAULT '{}',
                last_heartbeat TEXT,
                api_key_enc TEXT,
                key_confirmed INTEGER NOT NULL DEFAULT 0,
                key_issued_at TEXT,
                registered_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE earnapp_logical_nodes (
                logical_node_id    TEXT PRIMARY KEY,
                account_id         INTEGER NOT NULL,
                state              TEXT NOT NULL DEFAULT 'PLANNED',
                generation         INTEGER NOT NULL DEFAULT 1,
                assigned_worker_id INTEGER,
                last_worker_id     INTEGER,
                device_id          TEXT NOT NULL DEFAULT '',
                current_proxy_id   INTEGER,
                preferred_proxy_id INTEGER,
                last_heartbeat_at  TEXT,
                recovery_started_at TEXT,
                recovery_hold_until TEXT,
                created_at         TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at         TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(account_id) REFERENCES earnapp_accounts(id) ON DELETE RESTRICT
            );
            CREATE TABLE earnapp_account_control_routes (
                account_id INTEGER PRIMARY KEY,
                proxy_id INTEGER NOT NULL,
                state TEXT NOT NULL DEFAULT 'ACTIVE',
                assigned_logical_node_id TEXT NOT NULL DEFAULT '',
                leased_at TEXT NOT NULL DEFAULT (datetime('now')),
                released_at TEXT,
                release_reason TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(account_id) REFERENCES earnapp_accounts(id) ON DELETE CASCADE
            );
            CREATE TABLE earnapp_account_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                money_balance REAL NOT NULL DEFAULT 0,
                money_total REAL NOT NULL DEFAULT 0,
                online_nodes INTEGER NOT NULL DEFAULT 0,
                offline_nodes INTEGER NOT NULL DEFAULT 0,
                devices_json TEXT NOT NULL DEFAULT '[]',
                collected_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(account_id) REFERENCES earnapp_accounts(id) ON DELETE CASCADE
            );
            CREATE TABLE earnapp_replacement_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                logical_node_id TEXT NOT NULL,
                target_worker_id INTEGER NOT NULL,
                generation INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                used_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(logical_node_id) REFERENCES earnapp_logical_nodes(logical_node_id) ON DELETE CASCADE
            );
            """
        )
        await db.execute("INSERT INTO workers (id, client_id, name) VALUES (99, 'worker-99', 'worker-99')")
    for account in accounts:
        await db.execute(
            """
            INSERT INTO earnapp_accounts
                (id, account_name, cookies_enc, state, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                account["id"],
                account["account_name"],
                account["cookies_enc"],
                account.get("state", "VALID"),
                account.get("created_at", "2026-08-18 08:13:08"),
                account.get("updated_at", "2026-08-18 08:13:17"),
            ),
        )
    for lease in leases or []:
        await db.execute(
            """
            INSERT INTO earnapp_account_leases
                (id, account_id, worker_id, instance_id, state, leased_at,
                 last_heartbeat_at, released_at, release_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lease["id"],
                lease["account_id"],
                lease["worker_id"],
                lease["instance_id"],
                lease.get("state", "ACTIVE"),
                lease.get("leased_at", "2026-08-18 08:29:27"),
                lease.get("last_heartbeat_at", "2026-08-18 08:29:27"),
                lease.get("released_at"),
                lease.get("release_reason", ""),
            ),
        )
    await db.commit()


def _valid_legacy_credentials(email: str = "owner@example.com") -> dict[str, str]:
    return {
        "email": email,
        "oauth_refresh_token": "legacy-refresh-secret",
        "xsrf_token": "legacy-xsrf-secret",
    }


def test_init_db_migrates_legacy_earnapp_accounts_without_exposing_or_losing_credentials(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await db.execute("PRAGMA foreign_keys=ON")
            await _seed_legacy_earnapp_schema(
                db,
                [
                    {
                        "id": 1,
                        "account_name": "owner@example.com",
                        "cookies_enc": database.encrypt_value(json.dumps(_valid_legacy_credentials(), sort_keys=True)),
                    }
                ],
                [{"id": 1, "account_id": 1, "worker_id": 25883, "instance_id": "earnapp-proxy"}],
            )

            await database.init_db()

            columns = {
                row["name"] for row in await (await db.execute("PRAGMA table_info(earnapp_accounts)")).fetchall()
            }
            assert {
                "profile_key",
                "account_name",
                "email",
                "auth_method",
                "credentials_enc",
                "credential_keys_json",
                "token_expires_at",
                "cookie_expires_at",
            } <= columns
            public = await earnapp_accounts.list_accounts()
            assert public == [
                {
                    "id": 1,
                    "profile_key": "legacy-account-1",
                    "account_name": "owner@example.com",
                    "email": "owner@example.com",
                    "auth_method": "google",
                    "state": "DISABLED",
                    "token_expires_at": None,
                    "cookie_expires_at": None,
                    "assigned_nodes": 1,
                    "credentials_present": {
                        "oauth-refresh-token": True,
                        "xsrf-token": True,
                    },
                    "created_at": "2026-08-18 08:13:08",
                    "updated_at": "2026-08-18 08:13:17",
                }
            ]
            private = await earnapp_accounts.get_account_credentials(1)
            assert private is not None
            assert private["cookies"] == {
                "oauth-refresh-token": "legacy-refresh-secret",
                "xsrf-token": "legacy-xsrf-secret",
            }
            archived_account = await (
                await db.execute(
                    "SELECT account_name, cookies_enc, state FROM earnapp_accounts_legacy_v18 WHERE id = 1"
                )
            ).fetchone()
            assert archived_account["account_name"] == "owner@example.com"
            assert archived_account["cookies_enc"].startswith("enc:")
            assert json.loads(database.decrypt_value(archived_account["cookies_enc"])) == _valid_legacy_credentials()
            assert archived_account["state"] == "VALID"
            archived_lease = await (
                await db.execute("SELECT * FROM earnapp_account_leases_legacy_v18 WHERE id = 1")
            ).fetchone()
            assert archived_lease["account_id"] == 1
            assert archived_lease["worker_id"] == 25883
            assert archived_lease["instance_id"] == "earnapp-proxy"

            node = await (
                await db.execute("SELECT * FROM earnapp_logical_nodes WHERE logical_node_id = 'legacy-earnapp-lease-1'")
            ).fetchone()
            assert node["account_id"] == 1
            assert node["state"] == "RECOVERABLE"
            assert node["assigned_worker_id"] is None
            assert node["last_worker_id"] == 25883
            assert node["last_heartbeat_at"] == "2026-08-18 08:29:27"
            assert await (await db.execute("PRAGMA foreign_key_check")).fetchall() == []
            assert (await (await db.execute("PRAGMA foreign_keys")).fetchone())[0] == 1

            await database.init_db()
            assert await earnapp_accounts.list_accounts() == public
            assert (await (await db.execute("SELECT COUNT(*) AS count FROM earnapp_accounts")).fetchone())["count"] == 1
            assert (await (await db.execute("SELECT COUNT(*) AS count FROM earnapp_logical_nodes")).fetchone())[
                "count"
            ] == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    ("legacy_state", "expected_state"),
    [
        ("VALID", "DISABLED"),
        ("DISABLED", "DISABLED"),
        ("EXPIRED", "EXPIRED"),
        ("AUTH_FAILED", "AUTH_FAILED"),
        ("DELETED", "DELETED"),
    ],
)
def test_legacy_earnapp_account_state_is_never_reactivated(tmp_path, legacy_state, expected_state):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await _seed_legacy_earnapp_schema(
                db,
                [
                    {
                        "id": 1,
                        "account_name": "owner@example.com",
                        "cookies_enc": database.encrypt_value(json.dumps(_valid_legacy_credentials(), sort_keys=True)),
                        "state": legacy_state,
                    }
                ],
            )

            await database.init_db()

            row = await (
                await db.execute("SELECT state, credential_keys_json FROM earnapp_accounts WHERE id = 1")
            ).fetchone()
            assert row["state"] == expected_state
            assert json.loads(row["credential_keys_json"]) == ["oauth-refresh-token", "xsrf-token"]

    asyncio.run(run())


@pytest.mark.parametrize("broken_ciphertext", ["enc:not-a-fernet-token", "not-json"])
def test_legacy_earnapp_credentials_fail_closed_and_archive_original_ciphertext(tmp_path, broken_ciphertext):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await _seed_legacy_earnapp_schema(
                db,
                [{"id": 1, "account_name": "broken@example.com", "cookies_enc": broken_ciphertext}],
            )

            await database.init_db()

            archived = await (
                await db.execute("SELECT cookies_enc FROM earnapp_accounts_legacy_v18 WHERE id = 1")
            ).fetchone()
            migrated = await (
                await db.execute(
                    "SELECT state, credentials_enc, credential_keys_json FROM earnapp_accounts WHERE id = 1"
                )
            ).fetchone()
            assert archived["cookies_enc"] == broken_ciphertext
            assert migrated["state"] == "DISABLED"
            assert migrated["credentials_enc"] == ""
            assert json.loads(migrated["credential_keys_json"]) == []
            assert await earnapp_accounts.get_account_credentials(1) == {
                "id": 1,
                "profile_key": "legacy-account-1",
                "account_name": "broken@example.com",
                "email": "broken@example.com",
                "auth_method": "google",
                "state": "DISABLED",
                "token_expires_at": None,
                "cookie_expires_at": None,
                "cookies": {},
            }

    asyncio.run(run())


def test_legacy_earnapp_migration_resumes_from_archived_tables_idempotently(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await _seed_legacy_earnapp_schema(
                db,
                [
                    {
                        "id": 7,
                        "account_name": "resume@example.com",
                        "cookies_enc": database.encrypt_value(
                            json.dumps(_valid_legacy_credentials("resume@example.com"), sort_keys=True)
                        ),
                    }
                ],
                [{"id": 9, "account_id": 7, "worker_id": 99, "instance_id": "earnapp-direct"}],
            )
            await db.execute("ALTER TABLE earnapp_accounts RENAME TO earnapp_accounts_legacy_v18")
            await db.execute("ALTER TABLE earnapp_account_leases RENAME TO earnapp_account_leases_legacy_v18")
            await db.commit()

            await database.init_db()
            await database.init_db()

            account = await (await db.execute("SELECT * FROM earnapp_accounts WHERE id = 7")).fetchone()
            node = await (
                await db.execute("SELECT * FROM earnapp_logical_nodes WHERE logical_node_id = 'legacy-earnapp-lease-9'")
            ).fetchone()
            assert account["state"] == "DISABLED"
            assert node["account_id"] == 7
            assert node["last_worker_id"] == 99
            assert (await (await db.execute("SELECT COUNT(*) AS count FROM earnapp_accounts_legacy_v18")).fetchone())[
                "count"
            ] == 1
            assert (
                await (await db.execute("SELECT COUNT(*) AS count FROM earnapp_account_leases_legacy_v18")).fetchone()
            )["count"] == 1
            assert await (await db.execute("PRAGMA foreign_key_check")).fetchall() == []

    asyncio.run(run())


def test_legacy_earnapp_migration_rehearses_live_shape_with_three_orphan_leases(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await _seed_legacy_earnapp_schema(
                db,
                [{"id": 1, "account_name": "live@example.com", "cookies_enc": "not-json"}],
                [
                    {"id": 11, "account_id": 1, "worker_id": 101, "instance_id": "earnapp-1"},
                    {"id": 12, "account_id": 1, "worker_id": 102, "instance_id": "earnapp-2"},
                    {"id": 13, "account_id": 1, "worker_id": 103, "instance_id": "earnapp-3"},
                ],
            )

            await database.init_db()
            await database.init_db()

            counts = {}
            for table in (
                "earnapp_accounts",
                "earnapp_accounts_legacy_v18",
                "earnapp_account_leases_legacy_v18",
                "earnapp_logical_nodes",
            ):
                row = await (await db.execute(f"SELECT COUNT(*) AS count FROM {table}")).fetchone()
                counts[table] = row["count"]
            assert counts == {
                "earnapp_accounts": 1,
                "earnapp_accounts_legacy_v18": 1,
                "earnapp_account_leases_legacy_v18": 3,
                "earnapp_logical_nodes": 3,
            }
            states = await (
                await db.execute("SELECT state, assigned_worker_id FROM earnapp_logical_nodes ORDER BY logical_node_id")
            ).fetchall()
            assert [(row["state"], row["assigned_worker_id"]) for row in states] == [
                ("RECOVERABLE", None),
                ("RECOVERABLE", None),
                ("RECOVERABLE", None),
            ]
            assert await database._earnapp_migration_marker(db) == "complete"
            assert await (await db.execute("PRAGMA foreign_key_check")).fetchall() == []

    asyncio.run(run())


def test_legacy_earnapp_migration_rebinds_live_shape_foreign_keys_to_current_accounts(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await _seed_legacy_earnapp_schema(
                db,
                [
                    {
                        "id": 1,
                        "account_name": "owner@example.com",
                        "cookies_enc": database.encrypt_value(json.dumps(_valid_legacy_credentials(), sort_keys=True)),
                    }
                ],
                [{"id": 1, "account_id": 1, "worker_id": 25883, "instance_id": "earnapp-proxy"}],
                include_current_children=True,
            )
            await db.execute(
                "INSERT INTO earnapp_logical_nodes (logical_node_id, account_id, state) VALUES ('existing-node', 1, 'PLANNED')"
            )
            await db.execute("INSERT INTO earnapp_account_snapshots (account_id, money_balance) VALUES (1, 10.5)")
            await db.execute(
                """
                INSERT INTO earnapp_replacement_tickets
                    (logical_node_id, target_worker_id, generation, token_hash, expires_at)
                VALUES ('existing-node', 99, 1, 'hash-existing', '2099-01-01')
                """
            )
            await db.commit()

            await database.init_db()

            for table in (
                "earnapp_logical_nodes",
                "earnapp_account_control_routes",
                "earnapp_account_snapshots",
            ):
                foreign_keys = await (await db.execute(f"PRAGMA foreign_key_list({table})")).fetchall()
                account_targets = [row["table"] for row in foreign_keys if row["from"] == "account_id"]
                assert account_targets == ["earnapp_accounts"]
            ticket_targets = await (await db.execute("PRAGMA foreign_key_list(earnapp_replacement_tickets)")).fetchall()
            assert [row["table"] for row in ticket_targets if row["from"] == "logical_node_id"] == [
                "earnapp_logical_nodes"
            ]
            lease_targets = await (
                await db.execute("PRAGMA foreign_key_list(earnapp_account_leases_legacy_v18)")
            ).fetchall()
            assert [row["table"] for row in lease_targets if row["from"] == "account_id"] == [
                "earnapp_accounts_legacy_v18"
            ]
            assert await (await db.execute("PRAGMA foreign_key_check")).fetchall() == []
            assert (await (await db.execute("SELECT COUNT(*) AS count FROM earnapp_logical_nodes")).fetchone())[
                "count"
            ] == 2
            assert (await (await db.execute("SELECT COUNT(*) AS count FROM earnapp_account_snapshots")).fetchone())[
                "count"
            ] == 1
            assert (await (await db.execute("SELECT COUNT(*) AS count FROM earnapp_replacement_tickets")).fetchone())[
                "count"
            ] == 1

    asyncio.run(run())


def test_legacy_earnapp_migration_preserves_child_indexes_and_triggers(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await _seed_legacy_earnapp_schema(
                db,
                [{"id": 1, "account_name": "legacy@example.com", "cookies_enc": "not-json"}],
                include_current_children=True,
            )
            await db.executescript(
                """
                CREATE TABLE earnapp_snapshot_audit (
                    snapshot_id INTEGER NOT NULL,
                    account_id INTEGER NOT NULL
                );
                CREATE INDEX idx_earnapp_snapshots_balance
                    ON earnapp_account_snapshots(account_id, money_balance);
                CREATE TRIGGER trg_earnapp_snapshot_audit
                    AFTER INSERT ON earnapp_account_snapshots
                    BEGIN
                        INSERT INTO earnapp_snapshot_audit (snapshot_id, account_id)
                        VALUES (NEW.id, NEW.account_id);
                    END;
                """
            )
            await db.execute("INSERT INTO earnapp_account_snapshots (account_id, money_balance) VALUES (1, 10.5)")
            await db.commit()

            await database.init_db()

            objects = await (
                await db.execute(
                    """
                    SELECT type, name
                    FROM sqlite_master
                    WHERE tbl_name = 'earnapp_account_snapshots'
                      AND name IN ('idx_earnapp_snapshots_balance', 'trg_earnapp_snapshot_audit')
                    ORDER BY type, name
                    """
                )
            ).fetchall()
            assert [tuple(row) for row in objects] == [
                ("index", "idx_earnapp_snapshots_balance"),
                ("trigger", "trg_earnapp_snapshot_audit"),
            ]
            index_names = [
                row["name"]
                for row in await (await db.execute("PRAGMA index_list(earnapp_account_snapshots)")).fetchall()
            ]
            assert "idx_earnapp_account_snapshots_latest" in index_names

            await db.execute("INSERT INTO earnapp_account_snapshots (account_id, money_balance) VALUES (1, 20.5)")
            await db.commit()
            audit_rows = await (
                await db.execute("SELECT account_id FROM earnapp_snapshot_audit ORDER BY snapshot_id")
            ).fetchall()
            assert [row["account_id"] for row in audit_rows] == [1, 1]

    asyncio.run(run())


def test_legacy_migration_fails_closed_for_unknown_account_child_table(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await _seed_legacy_earnapp_schema(
                db,
                [{"id": 1, "account_name": "legacy@example.com", "cookies_enc": "not-json"}],
            )
            await db.executescript(
                """
                CREATE TABLE earnapp_unknown_child (
                    id INTEGER PRIMARY KEY,
                    account_id INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY(account_id) REFERENCES earnapp_accounts(id) ON DELETE CASCADE
                );
                INSERT INTO earnapp_unknown_child (id, account_id, payload)
                VALUES (1, 1, 'must-preserve');
                """
            )
            await db.commit()

            with pytest.raises(RuntimeError, match="unknown EarnApp account child"):
                await database.init_db()

            row = await (await db.execute("SELECT payload FROM earnapp_unknown_child WHERE id = 1")).fetchone()
            assert row["payload"] == "must-preserve"
            assert await database._table_exists(db, "earnapp_accounts")
            assert not await database._table_exists(db, "earnapp_accounts_legacy_v18")

    asyncio.run(run())


def test_legacy_migration_fails_closed_for_external_trigger_referencing_legacy_account_table(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await _seed_legacy_earnapp_schema(
                db,
                [{"id": 1, "account_name": "legacy@example.com", "cookies_enc": "not-json"}],
            )
            await db.executescript(
                """
                CREATE TABLE earnapp_account_audit (account_id INTEGER NOT NULL);
                CREATE TRIGGER trg_external_account_audit
                    AFTER INSERT ON earnapp_account_audit
                    BEGIN
                        UPDATE earnapp_accounts SET state = 'DISABLED' WHERE id = NEW.account_id;
                    END;
                """
            )
            await db.commit()

            with pytest.raises(RuntimeError, match="external trigger references EarnApp child table"):
                await database.init_db()

            assert await database._table_exists(db, "earnapp_accounts")
            assert not await database._table_exists(db, "earnapp_accounts_legacy_v18")

    asyncio.run(run())


def test_legacy_migration_fails_closed_for_unknown_logical_node_child(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await _seed_legacy_earnapp_schema(
                db,
                [{"id": 1, "account_name": "legacy@example.com", "cookies_enc": "not-json"}],
                include_current_children=True,
            )
            await db.executescript(
                """
                INSERT INTO earnapp_logical_nodes (logical_node_id, account_id)
                VALUES ('existing-node', 1);
                CREATE TABLE earnapp_unknown_logical_child (
                    id INTEGER PRIMARY KEY,
                    logical_node_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY(logical_node_id) REFERENCES earnapp_logical_nodes(logical_node_id) ON DELETE CASCADE
                );
                INSERT INTO earnapp_unknown_logical_child (id, logical_node_id, payload)
                VALUES (1, 'existing-node', 'must-preserve');
                """
            )
            await db.commit()

            with pytest.raises(RuntimeError, match="unknown EarnApp logical-node child"):
                await database.init_db()

            row = await (await db.execute("SELECT payload FROM earnapp_unknown_logical_child WHERE id = 1")).fetchone()
            assert row["payload"] == "must-preserve"
            assert await database._table_exists(db, "earnapp_accounts")
            assert not await database._table_exists(db, "earnapp_accounts_legacy_v18")
            assert not await database._table_exists(db, "earnapp_logical_nodes_legacy_fk_v19")

    asyncio.run(run())


def test_legacy_migration_fails_closed_for_external_trigger_referencing_rebuilt_child(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await _seed_legacy_earnapp_schema(
                db,
                [{"id": 1, "account_name": "legacy@example.com", "cookies_enc": "not-json"}],
                include_current_children=True,
            )
            await db.executescript(
                """
                CREATE TABLE earnapp_snapshot_audit (snapshot_id INTEGER NOT NULL);
                CREATE TRIGGER trg_external_snapshot_audit
                    AFTER INSERT ON earnapp_snapshot_audit
                    BEGIN
                        INSERT INTO earnapp_account_snapshots (account_id, money_balance)
                        VALUES (1, 99);
                    END;
                """
            )
            await db.commit()

            with pytest.raises(RuntimeError, match="external trigger references EarnApp child table"):
                await database.init_db()

            assert await database._table_exists(db, "earnapp_accounts")
            assert not await database._table_exists(db, "earnapp_accounts_legacy_v18")
            trigger = await (
                await db.execute(
                    "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = 'trg_external_snapshot_audit'"
                )
            ).fetchone()
            assert "INSERT INTO earnapp_account_snapshots" in trigger["sql"]

    asyncio.run(run())


def test_legacy_earnapp_migration_recovers_stranded_pr41_v19_rows(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await db.executescript(
                """
                CREATE TABLE earnapp_accounts_v19 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_key TEXT NOT NULL UNIQUE,
                    account_name TEXT NOT NULL,
                    email TEXT NOT NULL DEFAULT '',
                    auth_method TEXT NOT NULL,
                    credentials_enc TEXT NOT NULL,
                    credential_keys_json TEXT NOT NULL DEFAULT '[]',
                    token_expires_at TEXT,
                    cookie_expires_at TEXT,
                    state TEXT NOT NULL DEFAULT 'ACTIVE',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                """
            )
            credentials_enc = database.encrypt_value(
                json.dumps(
                    {
                        "cookies": {
                            "oauth-refresh-token": "stranded-refresh",
                            "xsrf-token": "stranded-xsrf",
                        }
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            await db.execute(
                """
                INSERT INTO earnapp_accounts_v19
                    (id, profile_key, account_name, email, auth_method, credentials_enc,
                     credential_keys_json, state, created_at, updated_at)
                VALUES (3, 'legacy-account-3', 'stranded@example.com', 'stranded@example.com',
                        'google', ?, '["oauth-refresh-token","xsrf-token"]', 'ACTIVE',
                        '2026-08-18 08:13:08', '2026-08-18 08:13:17')
                """,
                (credentials_enc,),
            )
            await db.commit()

            await database.init_db()

            row = await (await db.execute("SELECT * FROM earnapp_accounts WHERE id = 3")).fetchone()
            assert row["profile_key"] == "legacy-account-3"
            assert row["state"] == "DISABLED"
            assert row["credentials_enc"] == credentials_enc
            assert not await database._table_exists(db, "earnapp_accounts_v19")
            assert await database._table_exists(db, "earnapp_accounts_v19_legacy")

    asyncio.run(run())


def test_stranded_v19_recovery_accepts_equivalent_fernet_plaintext(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await db.executescript(database._SCHEMA)
            await database._create_earnapp_current_schema(db)
            plaintext = json.dumps(
                {"cookies": {"oauth-refresh-token": "refresh", "xsrf-token": "xsrf"}},
                sort_keys=True,
                separators=(",", ":"),
            )
            current_ciphertext = database.encrypt_value(plaintext)
            source_ciphertext = database.encrypt_value(plaintext)
            assert current_ciphertext != source_ciphertext
            await db.execute(
                """
                INSERT INTO earnapp_accounts
                    (id, profile_key, account_name, email, auth_method, credentials_enc,
                     credential_keys_json, state, created_at, updated_at)
                VALUES (3, 'legacy-account-3', 'stranded@example.com', 'stranded@example.com',
                        'google', ?, '["oauth-refresh-token","xsrf-token"]', 'DISABLED',
                        '2026-08-18 08:13:08', '2026-08-18 08:13:17')
                """,
                (current_ciphertext,),
            )
            await db.executescript(
                """
                CREATE TABLE earnapp_accounts_v19 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_key TEXT NOT NULL UNIQUE,
                    account_name TEXT NOT NULL,
                    email TEXT NOT NULL DEFAULT '',
                    auth_method TEXT NOT NULL CHECK(auth_method IN ('google', 'apple')),
                    credentials_enc TEXT NOT NULL,
                    credential_keys_json TEXT NOT NULL DEFAULT '[]',
                    token_expires_at TEXT,
                    cookie_expires_at TEXT,
                    state TEXT NOT NULL DEFAULT 'ACTIVE',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                """
            )
            await db.execute(
                """
                INSERT INTO earnapp_accounts_v19
                    (id, profile_key, account_name, email, auth_method, credentials_enc,
                     credential_keys_json, state, created_at, updated_at)
                VALUES (3, 'legacy-account-3', 'stranded@example.com', 'stranded@example.com',
                        'google', ?, '["oauth-refresh-token","xsrf-token"]', 'ACTIVE',
                        '2026-08-18 08:13:08', '2026-08-18 08:13:17')
                """,
                (source_ciphertext,),
            )
            await db.commit()

            await database.init_db()

            row = await (
                await db.execute("SELECT credentials_enc, state FROM earnapp_accounts WHERE id = 3")
            ).fetchone()
            assert row["credentials_enc"] == current_ciphertext
            assert row["state"] == "DISABLED"
            assert await database._table_exists(db, "earnapp_accounts_v19_legacy")

    asyncio.run(run())


def test_stranded_v19_recovery_rejects_malformed_ciphertext_against_valid_source(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await db.executescript(database._SCHEMA)
            await database._create_earnapp_current_schema(db)
            await db.execute(
                """
                INSERT INTO earnapp_accounts
                    (id, profile_key, account_name, email, auth_method, credentials_enc,
                     credential_keys_json, state, created_at, updated_at)
                VALUES (3, 'legacy-account-3', 'stranded@example.com', 'stranded@example.com',
                        'google', 'enc:malformed', '["oauth-refresh-token","xsrf-token"]', 'DISABLED',
                        '2026-08-18 08:13:08', '2026-08-18 08:13:17')
                """
            )
            await db.executescript(
                """
                CREATE TABLE earnapp_accounts_v19 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_key TEXT NOT NULL UNIQUE,
                    account_name TEXT NOT NULL,
                    email TEXT NOT NULL DEFAULT '',
                    auth_method TEXT NOT NULL CHECK(auth_method IN ('google', 'apple')),
                    credentials_enc TEXT NOT NULL,
                    credential_keys_json TEXT NOT NULL DEFAULT '[]',
                    token_expires_at TEXT,
                    cookie_expires_at TEXT,
                    state TEXT NOT NULL DEFAULT 'ACTIVE',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                """
            )
            source_ciphertext = database.encrypt_value(
                json.dumps({"cookies": {"oauth-refresh-token": "refresh", "xsrf-token": "xsrf"}})
            )
            await db.execute(
                """
                INSERT INTO earnapp_accounts_v19
                    (id, profile_key, account_name, email, auth_method, credentials_enc,
                     credential_keys_json, state, created_at, updated_at)
                VALUES (3, 'legacy-account-3', 'stranded@example.com', 'stranded@example.com',
                        'google', ?, '["oauth-refresh-token","xsrf-token"]', 'ACTIVE',
                        '2026-08-18 08:13:08', '2026-08-18 08:13:17')
                """,
                (source_ciphertext,),
            )
            await db.commit()

            with pytest.raises(RuntimeError, match="Conflicting partial EarnApp account row 3"):
                await database.init_db()

            assert not await database._table_exists(db, "earnapp_accounts_v19_legacy")
            current = await (await db.execute("SELECT credentials_enc FROM earnapp_accounts WHERE id = 3")).fetchone()
            source = await (
                await db.execute("SELECT credentials_enc FROM earnapp_accounts_v19 WHERE id = 3")
            ).fetchone()
            assert current["credentials_enc"] == "enc:malformed"
            assert source["credentials_enc"] == source_ciphertext

    asyncio.run(run())


def test_stranded_v19_recovery_fails_closed_for_unknown_child_table(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await db.executescript(database._SCHEMA)
            await db.executescript(
                """
                CREATE TABLE earnapp_accounts_v19 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_key TEXT NOT NULL UNIQUE,
                    account_name TEXT NOT NULL,
                    email TEXT NOT NULL DEFAULT '',
                    auth_method TEXT NOT NULL,
                    credentials_enc TEXT NOT NULL,
                    credential_keys_json TEXT NOT NULL DEFAULT '[]',
                    token_expires_at TEXT,
                    cookie_expires_at TEXT,
                    state TEXT NOT NULL DEFAULT 'ACTIVE',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE earnapp_unknown_v19_child (
                    id INTEGER PRIMARY KEY,
                    account_id INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY(account_id) REFERENCES earnapp_accounts_v19(id) ON DELETE CASCADE
                );
                INSERT INTO earnapp_accounts_v19
                    (id, profile_key, account_name, email, auth_method, credentials_enc)
                VALUES (1, 'legacy-account-1', 'legacy@example.com', 'legacy@example.com', 'google', '');
                INSERT INTO earnapp_unknown_v19_child (id, account_id, payload)
                VALUES (1, 1, 'must-preserve');
                """
            )

            with pytest.raises(RuntimeError, match="unknown EarnApp account child"):
                await database.init_db()

            row = await (await db.execute("SELECT payload FROM earnapp_unknown_v19_child WHERE id = 1")).fetchone()
            assert row["payload"] == "must-preserve"
            assert await database._table_exists(db, "earnapp_accounts_v19")
            assert not await database._table_exists(db, "earnapp_accounts_v19_legacy")

    asyncio.run(run())


def test_legacy_migration_rejects_overlapping_v18_and_stranded_v19_archives(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            credentials = _valid_legacy_credentials("overlap@example.com")
            await _seed_legacy_earnapp_schema(
                db,
                [
                    {
                        "id": 1,
                        "account_name": "overlap@example.com",
                        "cookies_enc": database.encrypt_value(json.dumps(credentials, sort_keys=True)),
                    }
                ],
            )
            await db.execute("ALTER TABLE earnapp_accounts RENAME TO earnapp_accounts_legacy_v18")
            await db.execute("ALTER TABLE earnapp_account_leases RENAME TO earnapp_account_leases_legacy_v18")
            await db.executescript(
                """
                CREATE TABLE earnapp_accounts_v19 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_key TEXT NOT NULL UNIQUE,
                    account_name TEXT NOT NULL,
                    email TEXT NOT NULL DEFAULT '',
                    auth_method TEXT NOT NULL,
                    credentials_enc TEXT NOT NULL,
                    credential_keys_json TEXT NOT NULL DEFAULT '[]',
                    token_expires_at TEXT,
                    cookie_expires_at TEXT,
                    state TEXT NOT NULL DEFAULT 'ACTIVE',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                """
            )
            normalized = {
                "cookies": {
                    "oauth-refresh-token": "legacy-refresh-secret",
                    "xsrf-token": "legacy-xsrf-secret",
                }
            }
            await db.execute(
                """
                INSERT INTO earnapp_accounts_v19
                    (id, profile_key, account_name, email, auth_method, credentials_enc,
                     credential_keys_json, state, created_at, updated_at)
                VALUES (1, 'legacy-account-1', 'overlap@example.com', 'overlap@example.com',
                        'google', ?, '["oauth-refresh-token","xsrf-token"]', 'ACTIVE',
                        '2026-08-18 08:13:08', '2026-08-18 08:13:17')
                """,
                (database.encrypt_value(json.dumps(normalized, sort_keys=True, separators=(",", ":"))),),
            )
            await db.commit()

            with pytest.raises(RuntimeError, match="duplicate account IDs"):
                await database.init_db()

            assert await database._table_exists(db, "earnapp_accounts_legacy_v18")
            assert await database._table_exists(db, "earnapp_accounts_v19")
            assert not await database._table_exists(db, "earnapp_accounts_v19_legacy")

    asyncio.run(run())


def test_legacy_earnapp_migration_rejects_conflicting_canonical_account_and_rolls_back(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await _seed_legacy_earnapp_schema(
                db,
                [{"id": 1, "account_name": "legacy@example.com", "cookies_enc": "not-json"}],
            )
            await db.execute("ALTER TABLE earnapp_accounts RENAME TO earnapp_accounts_legacy_v18")
            await db.execute("ALTER TABLE earnapp_account_leases RENAME TO earnapp_account_leases_legacy_v18")
            await db.executescript(database._SCHEMA)
            await database._create_earnapp_current_schema(db)
            await db.execute(
                """
                INSERT INTO earnapp_accounts
                    (id, profile_key, account_name, email, auth_method, credentials_enc,
                     credential_keys_json, state, created_at, updated_at)
                VALUES (1, 'canonical-profile', 'canonical@example.com', 'canonical@example.com',
                        'google', '', '[]', 'DISABLED', '2026-08-18 08:13:08', '2026-08-18 08:13:17')
                """
            )
            await db.commit()

            with pytest.raises(RuntimeError, match="Conflicting canonical EarnApp account row 1"):
                await database.init_db()

            row = await (
                await db.execute("SELECT profile_key, account_name FROM earnapp_accounts WHERE id = 1")
            ).fetchone()
            assert dict(row) == {"profile_key": "canonical-profile", "account_name": "canonical@example.com"}
            assert await database._table_exists(db, "earnapp_accounts_legacy_v18")

    asyncio.run(run())


def test_legacy_earnapp_migration_does_not_equate_failed_decryption_with_empty_credentials(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await _seed_legacy_earnapp_schema(
                db,
                [
                    {
                        "id": 1,
                        "account_name": "same@example.com",
                        "cookies_enc": "not-json",
                    }
                ],
            )
            await db.execute("ALTER TABLE earnapp_accounts RENAME TO earnapp_accounts_legacy_v18")
            await db.execute("ALTER TABLE earnapp_account_leases RENAME TO earnapp_account_leases_legacy_v18")
            await db.executescript(database._SCHEMA)
            await database._create_earnapp_current_schema(db)
            await db.execute(
                """
                INSERT INTO earnapp_accounts
                    (id, profile_key, account_name, email, auth_method, credentials_enc,
                     credential_keys_json, state, created_at, updated_at)
                VALUES (1, 'legacy-account-1', 'same@example.com', 'same@example.com',
                        'google', 'enc:wrong-key-ciphertext', '[]', 'DISABLED',
                        '2026-08-18 08:13:08', '2026-08-18 08:13:17')
                """
            )
            await db.commit()

            with pytest.raises(RuntimeError, match="Conflicting canonical EarnApp account row 1"):
                await database.init_db()

    asyncio.run(run())


def test_legacy_earnapp_migration_writes_marker_on_old_config_schema(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await db.executescript(
                """
                CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                """
            )
            await _seed_legacy_earnapp_schema(
                db,
                [{"id": 1, "account_name": "old-config@example.com", "cookies_enc": "not-json"}],
            )

            await database.init_db()

            assert await database._earnapp_migration_marker(db) == "complete"
            config_columns = await database._table_columns(db, "config")
            assert "updated_at" in config_columns

    asyncio.run(run())


def test_legacy_earnapp_migration_rejects_conflicting_logical_node_and_rolls_back(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await _seed_legacy_earnapp_schema(
                db,
                [
                    {
                        "id": 1,
                        "account_name": "legacy@example.com",
                        "cookies_enc": "not-json",
                    }
                ],
                [{"id": 9, "account_id": 1, "worker_id": 99, "instance_id": "earnapp-proxy"}],
            )
            await db.execute("ALTER TABLE earnapp_accounts RENAME TO earnapp_accounts_legacy_v18")
            await db.execute("ALTER TABLE earnapp_account_leases RENAME TO earnapp_account_leases_legacy_v18")
            await db.executescript(database._SCHEMA)
            await database._create_earnapp_current_schema(db)
            await db.execute(
                """
                INSERT INTO earnapp_accounts
                    (id, profile_key, account_name, email, auth_method, credentials_enc,
                     credential_keys_json, state, created_at, updated_at)
                VALUES (1, 'legacy-account-1', 'legacy@example.com', 'legacy@example.com',
                        'google', '', '[]', 'DISABLED', '2026-08-18 08:13:08', '2026-08-18 08:13:17')
                """
            )
            await db.execute(
                """
                INSERT INTO earnapp_logical_nodes
                    (logical_node_id, account_id, state, assigned_worker_id, last_worker_id,
                     last_heartbeat_at, created_at, updated_at)
                VALUES ('legacy-earnapp-lease-9', 1, 'PLANNED', NULL, 123,
                        '2026-08-18 08:29:27', '2026-08-18 08:29:27', '2026-08-18 08:29:27')
                """
            )
            await db.commit()

            with pytest.raises(RuntimeError, match="Conflicting logical EarnApp node legacy-earnapp-lease-9"):
                await database.init_db()

            row = await (
                await db.execute(
                    "SELECT state, last_worker_id FROM earnapp_logical_nodes WHERE logical_node_id = ?",
                    ("legacy-earnapp-lease-9",),
                )
            ).fetchone()
            assert dict(row) == {"state": "PLANNED", "last_worker_id": 123}
            assert await database._table_exists(db, "earnapp_account_leases_legacy_v18")

    asyncio.run(run())


def test_legacy_earnapp_migration_rejects_archive_name_collision_without_dropping_rows(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await _seed_legacy_earnapp_schema(
                db,
                [{"id": 1, "account_name": "live@example.com", "cookies_enc": "not-json"}],
            )
            await db.execute("ALTER TABLE earnapp_accounts RENAME TO earnapp_accounts_legacy_v18")
            await db.execute(
                """
                CREATE TABLE earnapp_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_name TEXT NOT NULL UNIQUE,
                    cookies_enc TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'VALID',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            await db.execute(
                "INSERT INTO earnapp_accounts (id, account_name, cookies_enc) VALUES (2, 'second@example.com', 'not-json')"
            )
            await db.commit()

            with pytest.raises(RuntimeError, match="Both live and archived legacy earnapp_accounts tables exist"):
                await database.init_db()

            assert (await (await db.execute("SELECT COUNT(*) AS count FROM earnapp_accounts_legacy_v18")).fetchone())[
                "count"
            ] == 1
            assert (await (await db.execute("SELECT COUNT(*) AS count FROM earnapp_accounts")).fetchone())["count"] == 1

    asyncio.run(run())


def test_archived_stranded_v19_without_marker_fails_closed(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await db.executescript(database._SCHEMA)
            await db.executescript(
                """
                CREATE TABLE earnapp_accounts_v19 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_key TEXT NOT NULL UNIQUE,
                    account_name TEXT NOT NULL,
                    email TEXT NOT NULL DEFAULT '',
                    auth_method TEXT NOT NULL,
                    credentials_enc TEXT NOT NULL,
                    credential_keys_json TEXT NOT NULL DEFAULT '[]',
                    token_expires_at TEXT,
                    cookie_expires_at TEXT,
                    state TEXT NOT NULL DEFAULT 'ACTIVE',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                """
            )
            await db.execute(
                """
                INSERT INTO earnapp_accounts_v19
                    (id, profile_key, account_name, email, auth_method, credentials_enc, state)
                VALUES (8, 'legacy-account-8', 'archived@example.com', 'archived@example.com',
                        'google', '', 'ACTIVE')
                """
            )
            await db.execute("ALTER TABLE earnapp_accounts_v19 RENAME TO earnapp_accounts_v19_legacy")
            await db.commit()

            with pytest.raises(RuntimeError, match="archived EarnApp v19 source requires recovery review"):
                await database.init_db()

            assert await database._earnapp_migration_marker(db) == ""
            assert await database._table_exists(db, "earnapp_accounts_v19_legacy")
            assert not await database._table_exists(db, "earnapp_accounts")

    asyncio.run(run())


def test_completed_marker_rejects_canonical_schema_without_required_constraints(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await db.executescript(database._SCHEMA)
            await db.executescript(
                """
                CREATE TABLE earnapp_accounts (
                    id INTEGER,
                    profile_key TEXT,
                    account_name TEXT,
                    email TEXT,
                    auth_method TEXT,
                    credentials_enc TEXT,
                    credential_keys_json TEXT,
                    token_expires_at TEXT,
                    cookie_expires_at TEXT,
                    state TEXT,
                    created_at TEXT,
                    updated_at TEXT
                );
                CREATE TABLE earnapp_accounts_legacy_v18 (
                    id INTEGER PRIMARY KEY,
                    account_name TEXT NOT NULL,
                    cookies_enc TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO earnapp_accounts_legacy_v18
                    (id, account_name, cookies_enc, state, created_at, updated_at)
                VALUES (1, 'legacy@example.com', '', 'DISABLED', '2026-08-18', '2026-08-18');
                INSERT INTO earnapp_accounts
                    (id, profile_key, account_name, email, auth_method, credentials_enc,
                     credential_keys_json, state, created_at, updated_at)
                VALUES (1, 'profile-1', 'legacy@example.com', 'legacy@example.com',
                        'google', '', '[]', 'DISABLED', '2026-08-18', '2026-08-18');
                INSERT INTO config (key, value)
                VALUES ('migration.earnapp_accounts.legacy_v19', 'complete');
                """
            )
            await db.commit()

            with pytest.raises(RuntimeError, match="canonical schema constraints"):
                await database.init_db()

            assert await database._earnapp_migration_marker(db) == "complete"

    asyncio.run(run())


def test_completed_marker_rejects_child_schema_with_wrong_foreign_key(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await db.executescript(database._SCHEMA)
            await database._create_earnapp_current_schema(db)
            await db.execute(
                """
                INSERT INTO earnapp_accounts
                    (profile_key, account_name, email, auth_method, credentials_enc, credential_keys_json, state)
                VALUES ('profile-1', 'legacy@example.com', 'legacy@example.com', 'google', '', '[]', 'DISABLED')
                """
            )
            await db.execute(
                """
                CREATE TABLE earnapp_accounts_legacy_v18 (
                    id INTEGER PRIMARY KEY,
                    account_name TEXT NOT NULL,
                    cookies_enc TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            await db.execute(
                """
                INSERT INTO earnapp_accounts_legacy_v18
                    (id, account_name, cookies_enc, state, created_at, updated_at)
                VALUES (1, 'legacy@example.com', '', 'DISABLED', '2026-08-18', '2026-08-18')
                """
            )
            await db.execute("PRAGMA writable_schema = ON")
            await db.execute(
                """
                UPDATE sqlite_master
                SET sql = replace(
                    sql,
                    'REFERENCES earnapp_accounts(id) ON DELETE RESTRICT',
                    'REFERENCES earnapp_accounts_legacy_v18(id) ON DELETE RESTRICT'
                )
                WHERE type = 'table' AND name = 'earnapp_logical_nodes'
                """
            )
            await db.execute("PRAGMA writable_schema = OFF")
            schema_version = int((await (await db.execute("PRAGMA schema_version")).fetchone())[0] or 0)
            await db.execute(f"PRAGMA schema_version = {schema_version + 1}")
            await db.execute(
                "INSERT INTO config (key, value) VALUES (?, 'complete')",
                (database._EARNAPP_LEGACY_MIGRATION_KEY,),
            )
            await db.commit()
            await db.close()
            await database.close_shared()

            with pytest.raises(RuntimeError, match="canonical child schema foreign-key mismatch"):
                await database.init_db()

            check = await database._get_db()
            assert await database._earnapp_migration_marker(check) == "complete"
            await check.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "corrupt_index_sql",
    [
        """
        DROP INDEX idx_earnapp_logical_nodes_account_state;
        CREATE INDEX idx_earnapp_logical_nodes_account_state
            ON earnapp_logical_nodes(state, account_id);
        """,
        """
        DROP INDEX idx_earnapp_logical_nodes_device_id_unique;
        CREATE UNIQUE INDEX idx_earnapp_logical_nodes_device_id_unique
            ON earnapp_logical_nodes(device_id);
        """,
    ],
)
def test_completed_marker_rejects_child_index_with_wrong_definition(tmp_path, corrupt_index_sql):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await db.executescript(database._SCHEMA)
            await database._create_earnapp_current_schema(db)
            await db.executescript(
                """
                CREATE TABLE earnapp_accounts_legacy_v18 (
                    id INTEGER PRIMARY KEY,
                    account_name TEXT NOT NULL,
                    cookies_enc TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO config (key, value)
                VALUES ('migration.earnapp_accounts.legacy_v19', 'complete');
                """
            )
            await db.executescript(corrupt_index_sql)
            await db.commit()

            with pytest.raises(RuntimeError, match="canonical child schema index mismatch"):
                await database.init_db()

            assert await database._earnapp_migration_marker(db) == "complete"

    asyncio.run(run())


def test_completed_marker_rejects_partial_profile_key_uniqueness(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await db.executescript(database._SCHEMA)
            await db.execute(
                """
                CREATE TABLE earnapp_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_key TEXT NOT NULL,
                    account_name TEXT NOT NULL,
                    email TEXT NOT NULL DEFAULT '',
                    auth_method TEXT NOT NULL CHECK(auth_method IN ('google', 'apple')),
                    credentials_enc TEXT NOT NULL,
                    credential_keys_json TEXT NOT NULL DEFAULT '[]',
                    token_expires_at TEXT,
                    cookie_expires_at TEXT,
                    state TEXT NOT NULL DEFAULT 'ACTIVE',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            await db.execute(
                "CREATE UNIQUE INDEX idx_earnapp_accounts_profile_key_partial "
                "ON earnapp_accounts(profile_key) WHERE profile_key != ''"
            )
            await database._create_earnapp_current_schema(db)
            await db.executescript(
                """
                CREATE TABLE earnapp_accounts_legacy_v18 (
                    id INTEGER PRIMARY KEY,
                    account_name TEXT NOT NULL,
                    cookies_enc TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO config (key, value)
                VALUES ('migration.earnapp_accounts.legacy_v19', 'complete');
                """
            )
            await db.commit()

            with pytest.raises(RuntimeError, match="canonical schema constraints"):
                await database.init_db()

            assert await database._earnapp_migration_marker(db) == "complete"

    asyncio.run(run())


def test_completed_v19_marker_adds_v21_proxy_reservations_without_rewriting_nodes(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await db.executescript(database._SCHEMA)
            await database._create_earnapp_current_schema(db)
            await db.executescript(
                """
                CREATE TABLE earnapp_accounts_legacy_v18 (
                    id INTEGER PRIMARY KEY,
                    account_name TEXT NOT NULL,
                    cookies_enc TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO earnapp_accounts
                    (id, profile_key, account_name, email, auth_method, credentials_enc,
                     credential_keys_json, state, created_at, updated_at)
                VALUES (1, 'profile-v19', 'v19@example.com', 'v19@example.com',
                        'google', '', '[]', 'ACTIVE', '2026-08-18', '2026-08-18');
                INSERT INTO earnapp_logical_nodes
                    (logical_node_id, account_id, platform, state, generation, device_id,
                     proxy_health, observed_egress_ip, expected_egress_ip, proxy_health_reason)
                VALUES ('earnapp-v19-node', 1, 'macos', 'ACTIVE', 7, 'sdk-mac-preserved-v19',
                        'healthy', '203.0.113.10', '203.0.113.10', 'probe-ok');
                INSERT INTO config (key, value)
                VALUES ('migration.earnapp_accounts.legacy_v19', 'complete');
                DROP TABLE earnapp_proxy_reservations;
                PRAGMA user_version = 19;
                """
            )
            await db.commit()

            assert not await database._table_exists(db, "earnapp_proxy_reservations")

            await database.init_db()

            assert await database._table_exists(db, "earnapp_proxy_reservations")
            assert database._EARNAPP_CHILD_INDEXES["earnapp_proxy_reservations"] <= await database._table_index_names(
                db, "earnapp_proxy_reservations"
            )
            node = await (
                await db.execute(
                    """
                    SELECT platform, state, generation, device_id, proxy_health,
                           observed_egress_ip, expected_egress_ip, proxy_health_reason
                    FROM earnapp_logical_nodes
                    WHERE logical_node_id = 'earnapp-v19-node'
                    """
                )
            ).fetchone()
            assert dict(node) == {
                "platform": "macos",
                "state": "ACTIVE",
                "generation": 7,
                "device_id": "sdk-mac-preserved-v19",
                "proxy_health": "healthy",
                "observed_egress_ip": "203.0.113.10",
                "expected_egress_ip": "203.0.113.10",
                "proxy_health_reason": "probe-ok",
            }
            assert int((await (await db.execute("PRAGMA user_version")).fetchone())[0]) == database.SCHEMA_VERSION

    asyncio.run(run())


def test_completed_marker_rejects_invalid_schema_before_adding_v21_reservations(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await db.executescript(database._SCHEMA)
            await database._create_earnapp_current_schema(db)
            await db.executescript(
                """
                CREATE TABLE earnapp_accounts_legacy_v18 (
                    id INTEGER PRIMARY KEY,
                    account_name TEXT NOT NULL,
                    cookies_enc TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO config (key, value)
                VALUES ('migration.earnapp_accounts.legacy_v19', 'complete');
                DROP TABLE earnapp_proxy_reservations;
                DROP INDEX idx_earnapp_logical_nodes_account_state;
                CREATE INDEX idx_earnapp_logical_nodes_account_state
                    ON earnapp_logical_nodes(state, account_id);
                PRAGMA user_version = 19;
                """
            )
            await db.commit()

            with pytest.raises(RuntimeError, match="canonical child schema index mismatch"):
                await database.init_db()

            assert not await database._table_exists(db, "earnapp_proxy_reservations")
            assert int((await (await db.execute("PRAGMA user_version")).fetchone())[0]) == 19

    asyncio.run(run())


def test_completed_marker_rejects_missing_canonical_schema(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await db.executescript(database._SCHEMA)
            await db.execute(
                "INSERT INTO config (key, value) VALUES (?, 'complete')",
                (database._EARNAPP_LEGACY_MIGRATION_KEY,),
            )
            await db.execute(
                """
                CREATE TABLE earnapp_accounts_legacy_v18 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_name TEXT NOT NULL UNIQUE,
                    cookies_enc TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'VALID',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            await db.commit()

            with pytest.raises(RuntimeError, match="completion marker requires canonical schema"):
                await database.init_db()

            assert await database._table_exists(db, "earnapp_accounts_legacy_v18")
            assert not await database._table_exists(db, "earnapp_accounts")

    asyncio.run(run())


def test_completed_marker_rejects_missing_canonical_without_archive(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await db.executescript(database._SCHEMA)
            await db.execute(
                "INSERT INTO config (key, value) VALUES (?, 'complete')",
                (database._EARNAPP_LEGACY_MIGRATION_KEY,),
            )
            await db.commit()

            with pytest.raises(RuntimeError, match="completion marker requires canonical schema"):
                await database.init_db()

            assert not await database._table_exists(db, "earnapp_accounts")

    asyncio.run(run())


def test_completed_marker_rejects_partial_canonical_schema(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await db.executescript(database._SCHEMA)
            await db.execute(
                "INSERT INTO config (key, value) VALUES (?, 'complete')",
                (database._EARNAPP_LEGACY_MIGRATION_KEY,),
            )
            await db.execute("CREATE TABLE earnapp_accounts (id INTEGER PRIMARY KEY, profile_key TEXT NOT NULL UNIQUE)")
            await db.commit()

            with pytest.raises(RuntimeError, match="canonical schema missing columns"):
                await database.init_db()

            assert await database._table_columns(db, "earnapp_accounts") == {"id", "profile_key"}

    asyncio.run(run())


def test_partial_canonical_schema_without_marker_fails_closed(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await db.executescript(database._SCHEMA)
            await db.execute("CREATE TABLE earnapp_accounts (id INTEGER PRIMARY KEY, profile_key TEXT NOT NULL UNIQUE)")
            await db.commit()

            with pytest.raises(RuntimeError, match="canonical schema missing columns"):
                await database.init_db()

            assert await database._earnapp_migration_marker(db) == ""
            assert await database._table_columns(db, "earnapp_accounts") == {"id", "profile_key"}

    asyncio.run(run())


def test_completed_marker_rejects_missing_canonical_archive_row(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await _seed_legacy_earnapp_schema(
                db,
                [
                    {
                        "id": 1,
                        "account_name": "archived@example.com",
                        "cookies_enc": database.encrypt_value(
                            json.dumps(_valid_legacy_credentials("archived@example.com"), sort_keys=True)
                        ),
                    }
                ],
            )
            await db.execute("ALTER TABLE earnapp_accounts RENAME TO earnapp_accounts_legacy_v18")
            await db.executescript(database._SCHEMA)
            await database._create_earnapp_current_schema(db)
            await db.execute(
                """
                INSERT INTO earnapp_accounts
                    (id, profile_key, account_name, email, auth_method, credentials_enc,
                     credential_keys_json, state, created_at, updated_at)
                VALUES (1, 'legacy-account-1', 'tampered@example.com', 'tampered@example.com',
                        'google', '', '[]', 'DISABLED', '2026-08-18 08:13:08', '2026-08-18 08:13:17')
                """
            )
            await db.execute("DELETE FROM earnapp_accounts WHERE id = 1")
            await db.execute(
                "INSERT INTO config (key, value) VALUES (?, 'complete')",
                (database._EARNAPP_LEGACY_MIGRATION_KEY,),
            )
            await db.commit()

            with pytest.raises(RuntimeError, match="canonical/archive parity"):
                await database.init_db()

            assert await (await db.execute("SELECT id FROM earnapp_accounts WHERE id = 1")).fetchone() is None

    asyncio.run(run())


def test_completed_marker_allows_post_migration_account_refresh(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await _seed_legacy_earnapp_schema(
                db,
                [
                    {
                        "id": 1,
                        "account_name": "legacy@example.com",
                        "cookies_enc": database.encrypt_value(
                            json.dumps(_valid_legacy_credentials("legacy@example.com"), sort_keys=True)
                        ),
                    }
                ],
            )
            await database.init_db()
            await earnapp_accounts.import_account(_payload("profile-new", "legacy@example.com"))

            await database.init_db()

            row = await (await db.execute("SELECT id, account_name FROM earnapp_accounts WHERE id = 1")).fetchone()
            assert dict(row) == {"id": 1, "account_name": "legacy@example.com"}

    asyncio.run(run())


def test_completed_marker_allows_empty_legacy_archive_and_new_canonical_accounts(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await _seed_legacy_earnapp_schema(db, [])
            await database.init_db()
            await earnapp_accounts.import_account(_payload("new-profile", "new@example.com"))

            await database.init_db()

            assert await database._earnapp_migration_marker(db) == "complete"
            assert await database._table_exists(db, "earnapp_accounts_legacy_v18")
            assert (await (await db.execute("SELECT COUNT(*) AS count FROM earnapp_accounts_legacy_v18")).fetchone())[
                "count"
            ] == 0
            assert (await (await db.execute("SELECT COUNT(*) AS count FROM earnapp_accounts")).fetchone())["count"] == 1

    asyncio.run(run())


def test_legacy_earnapp_migration_rolls_back_marker_and_schema_on_failure_then_retries(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await _seed_legacy_earnapp_schema(
                db,
                [{"id": 1, "account_name": "retry@example.com", "cookies_enc": "not-json"}],
            )
            original = database._mark_earnapp_migration_complete

            async def fail_before_marker(_db):
                raise RuntimeError("simulated migration interruption")

            with (
                patch.object(database, "_mark_earnapp_migration_complete", side_effect=fail_before_marker),
                pytest.raises(RuntimeError, match="simulated migration interruption"),
            ):
                await database.init_db()

            assert await database._earnapp_migration_marker(db) == ""
            assert "profile_key" not in await database._table_columns(db, "earnapp_accounts")
            assert not await database._table_exists(db, "earnapp_accounts_legacy_v18")
            assert not await database._table_exists(db, "earnapp_logical_nodes")

            with patch.object(database, "_mark_earnapp_migration_complete", side_effect=original):
                await database.init_db()

            assert await database._earnapp_migration_marker(db) == "complete"
            row = await (await db.execute("SELECT profile_key, state FROM earnapp_accounts WHERE id = 1")).fetchone()
            assert dict(row) == {"profile_key": "legacy-account-1", "state": "DISABLED"}

    asyncio.run(run())


def test_chrome_import_adopts_matching_legacy_account_without_creating_duplicate(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await _seed_legacy_earnapp_schema(
                db,
                [
                    {
                        "id": 1,
                        "account_name": "owner@example.com",
                        "cookies_enc": database.encrypt_value(json.dumps(_valid_legacy_credentials(), sort_keys=True)),
                    }
                ],
            )
            await database.init_db()

            account_id = await earnapp_accounts.import_account(_payload("profile-40", "owner@example.com"))

            assert account_id == 1
            assert (await (await db.execute("SELECT COUNT(*) AS count FROM earnapp_accounts")).fetchone())["count"] == 1
            row = await (await db.execute("SELECT profile_key, state FROM earnapp_accounts WHERE id = 1")).fetchone()
            assert dict(row) == {"profile_key": "profile-40", "state": "ACTIVE"}

    asyncio.run(run())


def test_chrome_import_with_same_email_refreshes_existing_account_and_preserves_profile_key(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            db = await database._get_db()
            await db.execute(
                """
                INSERT INTO earnapp_accounts
                    (profile_key, account_name, email, auth_method, credentials_enc,
                     credential_keys_json, state)
                VALUES ('bound-profile', 'owner@example.com', 'owner@example.com',
                        'google', ?, '[\"oauth-refresh-token\",\"xsrf-token\"]', 'ACTIVE')
                """,
                (database.encrypt_value(json.dumps({"cookies": {"oauth-refresh-token": "old", "xsrf-token": "old"}})),),
            )
            await db.commit()

            account_id = await earnapp_accounts.import_account(_payload("new-profile", "owner@example.com"))

            assert account_id == 1
            assert (await (await db.execute("SELECT COUNT(*) AS count FROM earnapp_accounts")).fetchone())["count"] == 1
            row = await (await db.execute("SELECT profile_key, email FROM earnapp_accounts WHERE id = 1")).fetchone()
            assert dict(row) == {"profile_key": "bound-profile", "email": "owner@example.com"}

    asyncio.run(run())


def test_chrome_import_rejects_ambiguous_duplicate_email_without_mutation(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            db = await database._get_db()
            encrypted = database.encrypt_value(
                json.dumps({"cookies": {"oauth-refresh-token": "old", "xsrf-token": "old"}})
            )
            for profile in ("bound-a", "bound-b"):
                await db.execute(
                    """
                    INSERT INTO earnapp_accounts
                        (profile_key, account_name, email, auth_method, credentials_enc,
                         credential_keys_json, state)
                    VALUES (?, 'owner@example.com', 'owner@example.com', 'google', ?,
                            '[\"oauth-refresh-token\",\"xsrf-token\"]', 'ACTIVE')
                    """,
                    (profile, encrypted),
                )
            await db.commit()

            with pytest.raises(ValueError, match="multiple accounts"):
                await earnapp_accounts.import_account(_payload("new-profile", "owner@example.com"))

            assert (await (await db.execute("SELECT COUNT(*) AS count FROM earnapp_accounts")).fetchone())["count"] == 2

    asyncio.run(run())


def test_chrome_import_redirects_zero_node_duplicate_to_populated_canonical_account(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            db = await database._get_db()
            encrypted = database.encrypt_value(
                json.dumps({"cookies": {"oauth-refresh-token": "old", "xsrf-token": "old"}})
            )
            for profile in ("canonical-profile", "duplicate-profile"):
                await db.execute(
                    """
                    INSERT INTO earnapp_accounts
                        (profile_key, account_name, email, auth_method, credentials_enc,
                         credential_keys_json, state)
                    VALUES (?, 'owner@example.com', 'owner@example.com', 'google', ?,
                            '[\"oauth-refresh-token\",\"xsrf-token\"]', 'ACTIVE')
                    """,
                    (profile, encrypted),
                )
            await db.execute(
                """
                INSERT INTO earnapp_logical_nodes (logical_node_id, account_id, platform, state)
                VALUES ('earnapp-live-node', 1, 'ubuntu', 'ACTIVE')
                """
            )
            await db.commit()

            account_id = await earnapp_accounts.import_account(_payload("duplicate-profile", "owner@example.com"))

            assert account_id == 1
            rows = await (
                await db.execute("SELECT id, profile_key, state FROM earnapp_accounts ORDER BY id")
            ).fetchall()
            assert [dict(row) for row in rows] == [
                {"id": 1, "profile_key": "canonical-profile", "state": "ACTIVE"},
                {"id": 2, "profile_key": "duplicate-profile", "state": "ACCOUNT_LOCKED"},
            ]

    asyncio.run(run())


def test_chrome_import_normalizes_trailing_email_punctuation_for_duplicate_guard(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            db = await database._get_db()
            await db.execute(
                """
                INSERT INTO earnapp_accounts
                    (profile_key, account_name, email, auth_method, credentials_enc,
                     credential_keys_json, state)
                VALUES ('bound-profile', 'owner@example.com', 'owner@example.com,',
                        'google', ?, '[\"oauth-refresh-token\",\"xsrf-token\"]', 'ACTIVE')
                """,
                (database.encrypt_value(json.dumps({"cookies": {"oauth-refresh-token": "old", "xsrf-token": "old"}})),),
            )
            await db.commit()

            account_id = await earnapp_accounts.import_account(_payload("new-profile", "owner@example.com"))

            assert account_id == 1
            assert (await (await db.execute("SELECT COUNT(*) AS count FROM earnapp_accounts")).fetchone())["count"] == 1

    asyncio.run(run())


def test_chrome_import_adopts_synthetic_legacy_account_with_authoritative_apple_method(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await _seed_legacy_earnapp_schema(
                db,
                [
                    {
                        "id": 1,
                        "account_name": "apple@example.com",
                        "cookies_enc": database.encrypt_value(
                            json.dumps(_valid_legacy_credentials("apple@example.com"), sort_keys=True)
                        ),
                    }
                ],
            )
            await database.init_db()

            account_id = await earnapp_accounts.import_account(
                _payload("profile-apple-40", "apple@example.com", auth_method="apple")
            )

            assert account_id == 1
            row = await (
                await db.execute("SELECT profile_key, auth_method, state FROM earnapp_accounts WHERE id = 1")
            ).fetchone()
            assert dict(row) == {"profile_key": "profile-apple-40", "auth_method": "apple", "state": "ACTIVE"}

    asyncio.run(run())


def test_completed_unsafe_migration_quarantines_synthetic_active_account(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            db = await database._get_db()
            await db.executescript(database._SCHEMA)
            await db.executescript(database._EARNAPP_ACCOUNTS_SCHEMA)
            await db.execute(
                """
                INSERT INTO earnapp_accounts
                    (profile_key, account_name, email, auth_method, credentials_enc,
                     credential_keys_json, state)
                VALUES ('legacy-account-77', 'legacy@example.com', 'legacy@example.com',
                        'google', '', '[]', 'ACTIVE')
                """
            )
            await db.commit()

            await database.init_db()

            row = await (
                await db.execute("SELECT state FROM earnapp_accounts WHERE profile_key = 'legacy-account-77'")
            ).fetchone()
            assert row["state"] == "DISABLED"

    asyncio.run(run())


@pytest.mark.parametrize("auth_method", ["google", "apple", "Google", "APPLE"])
def test_google_and_apple_auth_methods_are_supported(tmp_path, auth_method):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account_id = await earnapp_accounts.import_account(
                _payload(f"profile-{auth_method}", f"{auth_method}@example.com", auth_method=auth_method)
            )
            private = await earnapp_accounts.get_account_credentials(account_id)
            assert private is not None
            assert private["auth_method"] == auth_method.lower()

    asyncio.run(run())


def test_import_rejects_unknown_auth_method_and_non_allowlisted_cookie(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            with pytest.raises(ValueError, match="Google or Apple"):
                await earnapp_accounts.import_account(_payload("profile-oidc", "oidc@example.com", auth_method="oidc"))

            payload = _payload("profile-google", "google@example.com")
            payload["cookies"]["google-session"] = {"value": "must-never-be-read"}
            account_id = await earnapp_accounts.import_account(payload)
            private = await earnapp_accounts.get_account_credentials(account_id)
            assert private is not None
            assert "google-session" not in private["cookies"]

    asyncio.run(run())


def test_jwt_and_cookie_expiry_metadata_are_recorded_independently(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account_id = await earnapp_accounts.import_account(
                _payload(
                    "profile-expiry",
                    "expiry@example.com",
                    token_exp=1_800_000_000,
                    cookie_exp=1_800_000_500,
                )
            )
            row = (await earnapp_accounts.list_accounts())[0]
            assert row["id"] == account_id
            assert row["token_expires_at"] == "2027-01-15T08:00:00+00:00"
            assert row["cookie_expires_at"] == "2027-01-15T08:08:20+00:00"

    asyncio.run(run())


def test_account_assignment_is_least_assigned_and_recovery_nodes_still_count(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            first_id = await earnapp_accounts.import_account(_payload("profile-a", "a@example.com"))
            second_id = await earnapp_accounts.import_account(_payload("profile-b", "b@example.com"))

            first = await earnapp_accounts.assign_account("earnapp-node-a")
            second = await earnapp_accounts.assign_account("earnapp-node-b")
            assert [first["id"], second["id"]] == [first_id, second_id]

            await database.set_earnapp_logical_node_state("earnapp-node-a", "RECOVERY_HOLD")
            third = await earnapp_accounts.assign_account("earnapp-node-c")
            assert third["id"] == first_id

            retry = await earnapp_accounts.assign_account("earnapp-node-a")
            assert retry["id"] == first_id

    asyncio.run(run())


def test_only_locked_accounts_can_be_deleted_and_credentials_are_removed(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account_id = await earnapp_accounts.import_account(_payload("profile-delete", "locked@example.com"))

            with pytest.raises(earnapp_accounts.AccountDeletionDenied, match="ACCOUNT_LOCKED"):
                await earnapp_accounts.delete_account(account_id)

            assert await database.set_earnapp_account_state(account_id, "ACCOUNT_LOCKED")
            assert await earnapp_accounts.delete_account(account_id)
            assert await earnapp_accounts.get_account_credentials(account_id) is None
            assert await earnapp_accounts.list_accounts() == []

            db = await database._get_db()
            row = await (
                await db.execute(
                    "SELECT state, credentials_enc FROM earnapp_accounts WHERE id = ?",
                    (account_id,),
                )
            ).fetchone()
            assert dict(row) == {"state": "DELETED", "credentials_enc": ""}

    asyncio.run(run())


def test_refresh_does_not_reactivate_locked_or_deleted_accounts(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            payload = _payload("profile-state", "state@example.com")
            account_id = await earnapp_accounts.import_account(payload)
            assert await database.set_earnapp_account_state(account_id, "ACCOUNT_LOCKED")

            assert await earnapp_accounts.import_account(payload) == account_id
            assert (await earnapp_accounts.list_accounts())[0]["state"] == "ACCOUNT_LOCKED"

            assert await earnapp_accounts.delete_account(account_id)
            with pytest.raises(ValueError, match="deleted"):
                await earnapp_accounts.import_account(payload)
            assert await earnapp_accounts.list_accounts() == []

    asyncio.run(run())


def test_deleted_duplicate_profile_stays_deleted_when_imported_against_populated_account(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            canonical_id = await earnapp_accounts.import_account(_payload("profile-canonical", "same@example.com"))
            db = await database._get_db()
            await db.execute(
                "INSERT INTO earnapp_logical_nodes (logical_node_id, account_id, platform, state) VALUES (?, ?, ?, 'ACTIVE')",
                ("canonical-node", canonical_id, "macos"),
            )
            await db.commit()
            duplicate_id = await earnapp_accounts.import_account(_payload("profile-duplicate", "other@example.com"))
            await db.execute("UPDATE earnapp_accounts SET email = ? WHERE id = ?", ("same@example.com", duplicate_id))
            await db.commit()
            await database.set_earnapp_account_state(duplicate_id, "ACCOUNT_LOCKED")
            assert await earnapp_accounts.delete_account(duplicate_id)

            with pytest.raises(ValueError, match="deleted"):
                await earnapp_accounts.import_account(_payload("profile-duplicate", "same@example.com"))

            db = await database._get_db()
            row = await (
                await db.execute("SELECT state FROM earnapp_accounts WHERE id = ?", (duplicate_id,))
            ).fetchone()
            assert row["state"] == "DELETED"
            assert (await earnapp_accounts.list_accounts())[0]["id"] == canonical_id

    asyncio.run(run())


def test_locked_account_deletion_preserves_its_local_node_proxy_lease_while_runtime_is_disabled(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account_id = await earnapp_accounts.import_account(_payload("profile-node-delete", "node@example.com"))
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            (proxy_id,) = await database.upsert_proxy_endpoints_returning_ids(
                provider_id,
                [
                    {
                        "provider_proxy_id": "node-proxy",
                        "endpoint": "proxy.example:1080",
                        "host": "proxy.example",
                        "port": 1080,
                        "protocol": "socks5",
                        "status": "alive",
                        "exit_ip": "198.51.100.10",
                        "ip_type": "residential",
                        "country_code": "VN",
                    }
                ],
            )
            await database.update_proxy_endpoint_intelligence(
                proxy_id,
                {
                    "ip_type": "residential",
                    "ip_type_source": "test",
                    "ip_type_confidence": "high",
                    "country_code": "VN",
                    "country_name": "Vietnam",
                    "geo_source": "test",
                    "geo_confidence": "high",
                },
            )
            await database.save_proxy_probe_result(
                proxy_id,
                profile="earnapp_wss",
                probe_status="alive",
                verdict="CID_SET",
                eligibility="eligible",
                reason="",
                exit_ip="198.51.100.10",
                latency_ms=10,
                probe_version="test",
            )
            worker_id = await database.upsert_worker("worker-delete", "worker-delete", "http://worker")
            node = await earnapp_recovery.provision_node("earnapp-node-delete", worker_id, device_id="device-delete")
            assert node["proxy_id"] == proxy_id

            assert await database.set_earnapp_account_state(account_id, "ACCOUNT_LOCKED")

            async def cleanup(_binding):
                return True

            assert await earnapp_accounts.delete_account(account_id, runtime_cleanup=cleanup)
            assert not await database.get_active_provider_proxy_lease("earnapp", worker_id, "earnapp-node-delete")
            retained = await database.get_earnapp_logical_node("earnapp-node-delete")
            assert retained is not None and retained["state"] == "RETIRED"

    asyncio.run(run())


def test_locked_account_deletion_fails_closed_when_local_runtime_is_not_removed(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account_id = await earnapp_accounts.import_account(_payload("profile-runtime-guard", "guard@example.com"))
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            proxy_id = await _seed_proxy_for_account_delete(database, provider_id)
            worker_id = await database.upsert_worker("worker-runtime-guard", "runtime-guard", "http://worker")
            node = await earnapp_recovery.provision_node(
                "earnapp-runtime-guard", worker_id, device_id="device-runtime-guard"
            )
            assert node["proxy_id"] == proxy_id
            await database.save_provider_instance(
                "earnapp",
                "earnapp-runtime-guard",
                worker_id=worker_id,
                mode="proxy",
                container_id="container-runtime-guard",
                proxy_id=proxy_id,
                status="running",
            )
            assert await database.set_earnapp_account_state(account_id, "ACCOUNT_LOCKED")

            with pytest.raises(earnapp_accounts.AccountDeletionDenied, match="runtime"):
                await earnapp_accounts.delete_account(account_id)

            assert await database.get_active_provider_proxy_lease("earnapp", worker_id, "earnapp-runtime-guard")
            assert await database.get_earnapp_account_credentials(account_id)
            retained = await database.get_earnapp_logical_node("earnapp-runtime-guard")
            assert retained and retained["state"] == "ACTIVE"

    asyncio.run(run())


def test_active_logical_node_without_provider_instance_is_still_a_cleanup_binding(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account_id = await earnapp_accounts.import_account(_payload("profile-orphan", "orphan@example.com"))
            worker_id = await database.upsert_worker("worker-orphan", "orphan", "http://worker")
            await database.assign_earnapp_account("earnapp-orphan")
            db = await database._get_db()
            await db.execute(
                """
                UPDATE earnapp_logical_nodes
                SET state = 'ACTIVE', assigned_worker_id = ?, last_worker_id = ?,
                    device_id = 'device-orphan', current_proxy_id = NULL
                WHERE logical_node_id = 'earnapp-orphan' AND account_id = ?
                """,
                (worker_id, worker_id, account_id),
            )
            await db.commit()

            bindings = await database.list_earnapp_runtime_bindings(account_id)

            assert len(bindings) == 1
            assert bindings[0]["logical_node_id"] == "earnapp-orphan"
            assert bindings[0]["instance_id"] == "earnapp-orphan"
            assert bindings[0]["worker_id"] == worker_id
            assert bindings[0]["runtime_backend"] == ""

    asyncio.run(run())


def test_locked_account_deletion_requires_each_runtime_cleanup_ack_before_releasing_leases(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account_id = await earnapp_accounts.import_account(_payload("profile-runtime-ack", "ack@example.com"))
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            proxy_id = await _seed_proxy_for_account_delete(database, provider_id, suffix=21)
            worker_id = await database.upsert_worker("worker-runtime-ack", "runtime-ack", "http://worker")
            node = await earnapp_recovery.provision_node(
                "earnapp-runtime-ack", worker_id, device_id="device-runtime-ack"
            )
            assert node["proxy_id"] == proxy_id
            await database.save_provider_instance(
                "earnapp",
                "earnapp-runtime-ack",
                worker_id=worker_id,
                mode="proxy",
                container_id="container-runtime-ack",
                proxy_id=proxy_id,
                status="running",
            )
            assert await database.set_earnapp_account_state(account_id, "ACCOUNT_LOCKED")

            async def cleanup(binding):
                assert binding["logical_node_id"] == "earnapp-runtime-ack"
                return False

            with pytest.raises(earnapp_accounts.AccountDeletionDenied, match="not acknowledged"):
                await earnapp_accounts.delete_account(account_id, runtime_cleanup=cleanup)

            assert await database.get_active_provider_proxy_lease("earnapp", worker_id, "earnapp-runtime-ack")
            assert await database.get_earnapp_account_credentials(account_id)

    asyncio.run(run())


def test_locked_account_deletion_does_not_request_runtime_cleanup_while_disabled(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account_id = await earnapp_accounts.import_account(_payload("profile-runtime-ok", "ok@example.com"))
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            proxy_id = await _seed_proxy_for_account_delete(database, provider_id, suffix=22)
            worker_id = await database.upsert_worker("worker-runtime-ok", "runtime-ok", "http://worker")
            node = await earnapp_recovery.provision_node("earnapp-runtime-ok", worker_id, device_id="device-runtime-ok")
            assert node["proxy_id"] == proxy_id
            await database.save_provider_instance(
                "earnapp",
                "earnapp-runtime-ok",
                worker_id=worker_id,
                mode="proxy",
                container_id="container-runtime-ok",
                proxy_id=proxy_id,
                status="running",
            )
            assert await database.set_earnapp_account_state(account_id, "ACCOUNT_LOCKED")
            cleaned: list[str] = []

            async def cleanup(binding):
                cleaned.append(str(binding["instance_id"]))
                return True

            assert await earnapp_accounts.delete_account(account_id, runtime_cleanup=cleanup)
            assert cleaned == ["earnapp-runtime-ok"]
            assert not await database.get_active_provider_proxy_lease("earnapp", worker_id, "earnapp-runtime-ok")
            assert not await database.get_earnapp_account_credentials(account_id)

    asyncio.run(run())


def test_locked_account_deletion_does_not_run_runtime_cleanup_callback_while_disabled(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account_id = await earnapp_accounts.import_account(_payload("profile-race", "race@example.com"))
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            proxy_id = await _seed_proxy_for_account_delete(database, provider_id, suffix=23)
            worker_id = await database.upsert_worker("worker-race", "race", "http://worker")
            node = await earnapp_recovery.provision_node(
                "earnapp-runtime-race", worker_id, device_id="device-runtime-race"
            )
            assert node["proxy_id"] == proxy_id
            await database.save_provider_instance(
                "earnapp",
                "earnapp-runtime-race",
                worker_id=worker_id,
                mode="proxy",
                container_id="container-runtime-race",
                proxy_id=proxy_id,
                status="running",
            )
            assert await database.set_earnapp_account_state(account_id, "ACCOUNT_LOCKED")

            async def cleanup(_binding):
                db = await database._get_db()
                await db.execute(
                    """
                    INSERT INTO earnapp_logical_nodes
                        (logical_node_id, account_id, state, assigned_worker_id, last_worker_id, device_id)
                    VALUES ('earnapp-stranded-race', ?, 'ACTIVE', ?, ?, 'device-stranded-race')
                    """,
                    (account_id, worker_id, worker_id),
                )
                await db.commit()
                return True

            with pytest.raises(earnapp_accounts.AccountDeletionDenied, match="incomplete"):
                await earnapp_accounts.delete_account(account_id, runtime_cleanup=cleanup)

            assert await database.get_earnapp_account_credentials(account_id)
            stranded = await database.get_earnapp_logical_node("earnapp-stranded-race")
            assert stranded is not None and stranded["state"] == "ACTIVE"

    asyncio.run(run())


def test_proxy_capacity_counts_canonical_egress_and_excludes_every_assignment_type(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            account_id = await earnapp_accounts.import_account(_payload("profile-capacity", "capacity@example.com"))
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            proxy_ids = await database.upsert_proxy_endpoints_returning_ids(
                provider_id,
                [
                    {"provider_proxy_id": "legacy", "host": "1.1.1.1", "port": 1000, "ip_type": "residential"},
                    {"provider_proxy_id": "same-egress", "host": "2.2.2.2", "port": 2000, "ip_type": "residential"},
                    {"provider_proxy_id": "scoped", "host": "3.3.3.3", "port": 3000, "ip_type": "residential"},
                    {"provider_proxy_id": "control", "host": "4.4.4.4", "port": 4000, "ip_type": "residential"},
                    {"provider_proxy_id": "free", "host": "5.5.5.5", "port": 5000, "ip_type": "residential"},
                    {
                        "provider_proxy_id": "free-same-egress",
                        "host": "6.6.6.6",
                        "port": 6000,
                        "ip_type": "residential",
                    },
                ],
            )
            for index, proxy_id in enumerate(proxy_ids, start=1):
                if index == 2:
                    exit_ip = "198.51.100.1"
                elif index == 6:
                    exit_ip = "198.51.100.5"
                else:
                    exit_ip = f"198.51.100.{index}"
                await database.update_proxy_endpoint_intelligence(
                    proxy_id,
                    {
                        "ip_type": "residential",
                        "ip_type_source": "test",
                        "ip_type_confidence": "high",
                        "country_code": "VN",
                        "country_name": "Vietnam",
                        "geo_source": "test",
                        "geo_confidence": "high",
                    },
                )
                await database.save_proxy_probe_result(
                    proxy_id,
                    profile="earnapp_wss",
                    probe_status="alive",
                    verdict="CID_SET",
                    eligibility="eligible",
                    reason="cid",
                    exit_ip=exit_ip,
                    latency_ms=10,
                    probe_version="test",
                )
                await database.save_proxy_probe_result(
                    proxy_id,
                    profile="generic",
                    probe_status="alive",
                    verdict="OK",
                    eligibility="eligible",
                    reason="generic",
                    exit_ip=exit_ip,
                    latency_ms=10,
                    probe_version="test",
                )
            legacy_worker = await database.upsert_worker("worker-legacy", "legacy", "http://legacy")
            assert await database.set_worker_proxy_assignment(legacy_worker, proxy_ids[0])
            scoped_worker = await database.upsert_worker("worker-scoped", "scoped", "http://scoped")
            assert await database.lease_proxy_for_provider_instance("other-provider", scoped_worker, "node-1")
            control = await database.lease_earnapp_account_control_proxy(account_id)
            assert control is not None and control["proxy_id"] == proxy_ids[3]

            capacity = await database.get_earnapp_proxy_capacity()

            assert capacity["eligible"] == 4
            assert capacity["leaseable"] == 1
            assert capacity["occupied"] == 1
            assert capacity["control_routes"] == 1

    asyncio.run(run())
