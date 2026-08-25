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


def test_locked_account_deletion_releases_its_local_node_proxy_lease(tmp_path):
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
                    }
                ],
            )
            await database.update_proxy_endpoint_intelligence(
                proxy_id,
                {"ip_type": "residential", "ip_type_source": "test", "ip_type_confidence": "high"},
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
            assert await earnapp_accounts.delete_account(account_id)

            assert await database.get_active_provider_proxy_lease("earnapp", worker_id, "earnapp-node-delete") is None
            retired = await database.get_earnapp_logical_node("earnapp-node-delete")
            assert retired is not None
            assert retired["state"] == "RETIRED"
            assert retired["current_proxy_id"] is None

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
                    {"ip_type": "residential", "ip_type_source": "test", "ip_type_confidence": "high"},
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
