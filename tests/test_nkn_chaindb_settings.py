from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from starlette.requests import Request

from app import database, main

PUBLISHER_FINGERPRINT = "SHA256:" + "A" * 43


def test_nkn_chaindb_settings_defaults_are_disabled_and_bounded():
    settings = main._nkn_chaindb_settings({})
    assert settings["enabled"] is False
    assert settings["max_age_seconds"] == 48 * 60 * 60
    assert settings["url_ttl_seconds"] == 6 * 60 * 60
    assert settings["retention"] == 2
    assert settings["publisher_host_key_sha256"] == ""


@pytest.mark.parametrize(
    "config",
    [
        {"nkn_chaindb_max_age_hours": "0"},
        {"nkn_chaindb_max_age_hours": "721"},
        {"nkn_chaindb_url_ttl_seconds": "0"},
        {"nkn_chaindb_url_ttl_seconds": "604801"},
        {"nkn_chaindb_retention": "0"},
        {"nkn_chaindb_retention": "11"},
    ],
)
def test_nkn_chaindb_settings_reject_invalid_bounds(config):
    with pytest.raises(ValueError):
        main._nkn_chaindb_settings(config)


def test_nkn_chaindb_settings_upgrades_legacy_short_ttl_to_safe_floor():
    assert main._nkn_chaindb_settings({"nkn_chaindb_url_ttl_seconds": "300"})["url_ttl_seconds"] == 6 * 60 * 60


def test_partial_chaindb_config_update_is_validated_against_stored_settings():
    async def run():
        stored = {
            "nkn_chaindb_enabled": "true",
            "nkn_chaindb_endpoint": "https://acct.r2.cloudflarestorage.com",
            "nkn_chaindb_bucket": "private-bucket",
            "nkn_chaindb_prefix": "nkn/chaindb",
            "nkn_chaindb_publisher_host": "203.0.113.10",
            "nkn_chaindb_publisher_port": "26266",
            "nkn_chaindb_publisher_user": "root",
            "nkn_chaindb_publisher_host_key_sha256": PUBLISHER_FINGERPRINT,
        }
        with (
            patch.object(
                database, "get_config", AsyncMock(side_effect=[stored, {**stored, "nkn_chaindb_enabled": "false"}])
            ),
            patch.object(database, "set_config_bulk", AsyncMock()) as save,
            patch.object(main, "_sync_runtime_assets_from_config", AsyncMock()),
            patch.object(main, "_mark_redeploy_needed_for_config_change", AsyncMock()),
            patch.object(main, "_service_tracking_ready", return_value=False),
        ):
            result = await main.api_set_config(
                Request({"type": "http"}),
                main.ConfigUpdate(data={"nkn_chaindb_enabled": "false"}),
                {"uid": 1},
            )
        assert result == {"status": "saved"}
        save.assert_awaited_once_with({"nkn_chaindb_enabled": "false"})

    asyncio.run(run())


def test_nkn_chaindb_secret_config_keys_are_encrypted_and_masked(tmp_path):
    async def run():
        with (
            patch.object(database, "DB_DIR", tmp_path),
            patch.object(database, "DB_PATH", tmp_path / "settings.db"),
            patch.object(database, "_FERNET_KEY_FILE", tmp_path / ".fernet_key"),
        ):
            await database.init_db()
            await database.set_config_bulk(
                {
                    "nkn_chaindb_r2_access_key": "access-secret",
                    "nkn_chaindb_r2_secret_key": "secret-secret",
                    "nkn_chaindb_publisher_password": "ssh-secret",
                    "nkn_chaindb_publisher_private_key": "key-secret",
                    "nkn_chaindb_bucket": "private-bucket",
                }
            )
            masked = await database.get_config_masked()
            raw = await database.get_config()
            assert masked["_secrets"]["nkn_chaindb_r2_access_key"] is True
            assert masked["_secrets"]["nkn_chaindb_r2_secret_key"] is True
            assert masked["_secrets"]["nkn_chaindb_publisher_private_key"] is True
            assert "access-secret" not in str(masked)
            assert raw["nkn_chaindb_r2_access_key"] == "access-secret"

    asyncio.run(run())


def test_settings_template_exposes_snapshot_controls_without_secret_values():
    from pathlib import Path

    text = (Path(__file__).parents[1] / "app" / "templates" / "settings.html").read_text(encoding="utf-8")
    for key in (
        "nkn_chaindb_enabled",
        "nkn_chaindb_endpoint",
        "nkn_chaindb_bucket",
        "nkn_chaindb_prefix",
        "nkn_chaindb_r2_access_key",
        "nkn_chaindb_r2_secret_key",
        "nkn_chaindb_publisher_host",
        "nkn_chaindb_publisher_host_key_sha256",
    ):
        assert f'data-config="{key}"' in text
    assert "access-secret" not in text


def test_snapshot_status_endpoint_returns_masked_state_only():
    async def run():
        with (
            patch.object(main, "_require_owner", lambda request: {"uid": 1}),
            patch.object(
                database,
                "get_config_masked",
                AsyncMock(
                    return_value={
                        "nkn_chaindb_enabled": "true",
                        "_secrets": {"nkn_chaindb_r2_secret_key": True},
                    }
                ),
            ),
        ):
            result = await main.api_nkn_chaindb_status(Request({"type": "http"}))
        assert result["config"]["_secrets"]["nkn_chaindb_r2_secret_key"] is True
        assert "secret-secret" not in str(result)

    asyncio.run(run())


def test_snapshot_status_endpoint_includes_validated_latest_manifest_metadata():
    async def run():
        manifest = {
            "schema_version": 1,
            "provider": "nkn",
            "network": "mainnet",
            "archive_key": "nkn/chaindb/snapshots/42-20260823T120000Z-" + "a" * 64 + ".tar.zst",
            "sha256": "a" * 64,
            "size_bytes": 123,
            "block_height": 42,
            "created_at": "2026-08-23T12:00:00Z",
            "image": "nknorg/nkn@sha256:" + "b" * 64,
            "chain_db_root": "ChainDB",
        }
        with (
            patch.object(main, "_require_owner", lambda request: {"uid": 1}),
            patch.object(
                database,
                "get_config_masked",
                AsyncMock(
                    return_value={
                        "nkn_chaindb_enabled": "true",
                        "_secrets": {"nkn_chaindb_r2_secret_key": True},
                    }
                ),
            ),
            patch.object(database, "get_config", AsyncMock(return_value={"nkn_chaindb_enabled": "true"})),
            patch.object(main, "_nkn_chaindb_latest_manifest", AsyncMock(return_value=manifest)) as latest,
        ):
            result = await main.api_nkn_chaindb_status(Request({"type": "http"}))
        latest.assert_awaited_once()
        assert result["snapshot_status"] == "ready"
        assert result["latest_manifest"] == manifest
        assert "archive_url" not in str(result)

    asyncio.run(run())


def test_publisher_deploy_endpoint_uses_stored_settings_and_returns_redacted_result():
    async def run():
        config = {
            "nkn_chaindb_enabled": "true",
            "nkn_chaindb_endpoint": "https://acct.r2.cloudflarestorage.com",
            "nkn_chaindb_bucket": "private-bucket",
            "nkn_chaindb_prefix": "nkn/chaindb",
            "nkn_chaindb_r2_access_key": "access-secret",
            "nkn_chaindb_r2_secret_key": "secret-secret",
            "nkn_chaindb_publisher_host": "203.0.113.10",
            "nkn_chaindb_publisher_port": "22",
            "nkn_chaindb_publisher_user": "root",
            "nkn_chaindb_publisher_password": "ssh-secret",
            "nkn_chaindb_publisher_host_key_sha256": PUBLISHER_FINGERPRINT,
            "nkn_beneficiary_address": "NKNBeneficiaryAddress",
        }
        with (
            patch.object(main, "_require_owner", lambda request: {"uid": 1}),
            patch.object(database, "get_config", AsyncMock(return_value=config)),
            patch.object(
                database,
                "reserve_nkn_publisher_wallet",
                AsyncMock(
                    return_value={
                        "id": 9,
                        "wallet_json": '{"Address":"NKNPublisherAddress"}',
                        "wallet_pswd": "publisher-password",
                    }
                ),
            ) as reserve,
            patch.object(
                main, "_deploy_nkn_chaindb_publisher", AsyncMock(return_value={"status": "deployed"})
            ) as deploy,
        ):
            result = await main.api_deploy_nkn_chaindb_publisher(Request({"type": "http"}))
        assert result == {"status": "deployed"}
        reserve.assert_awaited_once_with(public_ip="203.0.113.10")
        assert deploy.await_args.args[0]["publisher_password"] == "ssh-secret"
        assert deploy.await_args.args[0]["publisher_wallet"]["id"] == 9
        assert "ssh-secret" not in str(result)

    asyncio.run(run())


def test_publisher_deploy_requires_snapshot_mode_to_be_enabled():
    async def run():
        config = {
            "nkn_chaindb_enabled": "false",
            "nkn_chaindb_publisher_host": "203.0.113.10",
        }
        with (
            patch.object(main, "_require_owner", lambda request: {"uid": 1}),
            patch.object(database, "get_config", AsyncMock(return_value=config)),
            patch.object(database, "reserve_nkn_publisher_wallet", AsyncMock()) as reserve,
            pytest.raises(main.HTTPException) as exc,
        ):
            await main.api_deploy_nkn_chaindb_publisher(Request({"type": "http"}))
        assert exc.value.status_code == 400
        reserve.assert_not_awaited()

    asyncio.run(run())


def test_publisher_deploy_validates_complete_settings_before_reserving_wallet():
    async def run():
        config = {
            "nkn_chaindb_enabled": "true",
            "nkn_chaindb_publisher_host": "203.0.113.10",
        }
        with (
            patch.object(main, "_require_owner", lambda request: {"uid": 1}),
            patch.object(database, "get_config", AsyncMock(return_value=config)),
            patch.object(database, "reserve_nkn_publisher_wallet", AsyncMock()) as reserve,
            pytest.raises(main.HTTPException) as exc,
        ):
            await main.api_deploy_nkn_chaindb_publisher(Request({"type": "http"}))
        assert exc.value.status_code == 400
        reserve.assert_not_awaited()

    asyncio.run(run())


def test_publisher_deploy_keeps_new_reservation_when_install_fails():
    async def run():
        config = {
            "nkn_chaindb_enabled": "true",
            "nkn_chaindb_endpoint": "https://acct.r2.cloudflarestorage.com",
            "nkn_chaindb_bucket": "private-bucket",
            "nkn_chaindb_prefix": "nkn/chaindb",
            "nkn_chaindb_r2_access_key": "access-secret",
            "nkn_chaindb_r2_secret_key": "secret-secret",
            "nkn_chaindb_publisher_host": "203.0.113.10",
            "nkn_chaindb_publisher_port": "22",
            "nkn_chaindb_publisher_user": "root",
            "nkn_chaindb_publisher_password": "ssh-secret",
            "nkn_chaindb_publisher_host_key_sha256": PUBLISHER_FINGERPRINT,
            "nkn_beneficiary_address": "NKNBeneficiaryAddress",
        }
        wallet = {
            "id": 9,
            "wallet_json": '{"Address":"NKNPublisherAddress"}',
            "wallet_pswd": "publisher-password",
            "reservation_created": True,
        }
        with (
            patch.object(main, "_require_owner", lambda request: {"uid": 1}),
            patch.object(database, "get_config", AsyncMock(return_value=config)),
            patch.object(database, "reserve_nkn_publisher_wallet", AsyncMock(return_value=wallet)),
            patch.object(database, "release_nkn_publisher_wallet", AsyncMock(return_value=True)) as release,
            patch.object(main, "_deploy_nkn_chaindb_publisher", AsyncMock(side_effect=RuntimeError("install failed"))),
            pytest.raises(RuntimeError, match="install failed"),
        ):
            await main.api_deploy_nkn_chaindb_publisher(Request({"type": "http"}))
        release.assert_not_awaited()

    asyncio.run(run())


def test_publisher_wallet_is_not_leased_to_worker_pool(tmp_path):
    async def run():
        with (
            patch.object(database, "DB_DIR", tmp_path),
            patch.object(database, "DB_PATH", tmp_path / "wallets.db"),
        ):
            await database.init_db()
            await database.import_nkn_wallet_records(
                [
                    {
                        "folder_name": "publisher-wallet",
                        "wallet_json": '{"Address":"NKNPublisherAddress"}',
                        "wallet_pswd": "publisher-password",
                    },
                    {
                        "folder_name": "worker-wallet",
                        "wallet_json": '{"Address":"NKNWorkerAddress"}',
                        "wallet_pswd": "worker-password",
                    },
                ]
            )
            publisher = await database.reserve_nkn_publisher_wallet(public_ip="203.0.113.10")
            worker = await database.lease_nkn_wallet("worker-a:nkn:ipv4-001", worker_id=1, public_ip="8.8.8.8")
            assert publisher["id"] != worker["id"]
            rows = await database.list_nkn_wallets()
            publisher_row = next(row for row in rows if row["id"] == publisher["id"])
            assert publisher_row["state"] == "RESERVED"
            assert publisher_row["leased_to_worker_id"] is None

    asyncio.run(run())


def test_settings_template_wires_publisher_deploy_action():
    from pathlib import Path

    template = (Path(__file__).parents[1] / "app" / "templates" / "settings.html").read_text(encoding="utf-8")
    frontend = (Path(__file__).parents[1] / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert 'data-action="deployNknChaindbPublisher"' in template
    assert "async function deployNknChaindbPublisher()" in frontend
    assert "/api/nkn/chaindb/publisher/deploy" in frontend


def test_nkn_wallet_page_exposes_guarded_publisher_release_action():
    template = (Path(__file__).parents[1] / "app" / "templates" / "nkn_wallet.html").read_text(encoding="utf-8")
    frontend = (Path(__file__).parents[1] / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert '<option value="RESERVED">Reserved</option>' in template
    assert "releaseNknPublisherWallet" in frontend
    assert "/api/nkn/chaindb/publisher/wallet/release" in frontend
    assert "acknowledge_remote_state_unknown" in frontend


def test_ssh_password_uses_environment_not_process_arguments(monkeypatch):
    calls = []

    def run(args, **kwargs):
        from subprocess import CompletedProcess

        calls.append((args, kwargs.get("env", {})))
        return CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(main.subprocess, "run", run)
    settings = {
        "publisher_host": "203.0.113.10",
        "publisher_port": 22,
        "publisher_user": "root",
        "publisher_password": "ssh-secret",
    }
    main._run_publisher_ssh(settings, ["true"])
    main._copy_publisher_file(settings, "local-file", "root@203.0.113.10:/tmp/remote-file")
    assert all("ssh-secret" not in " ".join(args) for args, _ in calls)
    assert all(env.get("SSHPASS") == "ssh-secret" for _, env in calls)
    assert all("UserKnownHostsFile=/data/nkn-chaindb-known-hosts" in args for args, _ in calls)
    assert all("StrictHostKeyChecking=yes" in args for args, _ in calls)
    assert all("StrictHostKeyChecking=accept-new" not in args for args, _ in calls)


def test_publisher_host_key_scan_is_verified_before_known_hosts_is_written(tmp_path, monkeypatch):
    known_hosts = tmp_path / "known-hosts"
    expected = "SHA256:" + "A" * 43
    scanned = b"[203.0.113.10]:26266 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest\n"
    calls = []

    def run(args, **kwargs):
        from subprocess import CompletedProcess

        calls.append((args, kwargs))
        if args[0] == "ssh-keyscan":
            return CompletedProcess(args, 0, scanned, b"")
        if args[0] == "ssh-keygen":
            return CompletedProcess(args, 0, f"255 {expected} publisher (ED25519)\n".encode(), b"")
        raise AssertionError(args)

    monkeypatch.setattr(main, "_NKN_PUBLISHER_KNOWN_HOSTS", known_hosts)
    monkeypatch.setattr(main.subprocess, "run", run)
    settings = {
        "publisher_host": "203.0.113.10",
        "publisher_port": 26266,
        "publisher_host_key_sha256": expected,
    }

    assert main._prepare_publisher_known_hosts(settings) == str(known_hosts)
    assert known_hosts.read_bytes() == scanned
    if os.name != "nt":
        assert known_hosts.stat().st_mode & 0o777 == 0o600
    assert calls[0][0][:4] == ["ssh-keyscan", "-T", "20", "-t"]
    assert calls[1][1]["input"] == scanned


def test_publisher_host_key_mismatch_fails_closed(tmp_path, monkeypatch):
    from subprocess import CompletedProcess

    monkeypatch.setattr(main, "_NKN_PUBLISHER_KNOWN_HOSTS", tmp_path / "known-hosts")

    def run(args, **kwargs):
        if args[0] == "ssh-keyscan":
            return CompletedProcess(args, 0, b"host ssh-ed25519 key\n", b"")
        return CompletedProcess(args, 0, b"255 SHA256:" + b"B" * 43 + b" host (ED25519)\n", b"")

    monkeypatch.setattr(main.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="host key fingerprint mismatch"):
        main._prepare_publisher_known_hosts(
            {
                "publisher_host": "203.0.113.10",
                "publisher_port": 22,
                "publisher_host_key_sha256": "SHA256:" + "A" * 43,
            }
        )


def test_publisher_release_endpoint_requires_exact_reservation_and_acknowledgement():
    async def run():
        request = main.NknPublisherWalletReleaseRequest(
            wallet_id=9,
            publisher_host="203.0.113.10",
            acknowledge_remote_state_unknown=True,
            confirmation="RELEASE",
        )
        with (
            patch.object(main, "_require_owner", lambda request: {"uid": 1}),
            patch.object(
                database,
                "get_nkn_publisher_reservation",
                AsyncMock(return_value={"id": 9, "state": "RESERVED", "public_ip": "203.0.113.10"}),
            ),
            patch.object(database, "release_nkn_publisher_wallet", AsyncMock(return_value=True)) as release,
        ):
            result = await main.api_release_nkn_chaindb_publisher_wallet(Request({"type": "http"}), request)
        assert result == {"status": "released", "wallet_id": 9}
        release.assert_awaited_once_with(wallet_id=9, public_ip="203.0.113.10")

    asyncio.run(run())


def test_publisher_release_endpoint_rejects_missing_remote_state_acknowledgement():
    async def run():
        request = main.NknPublisherWalletReleaseRequest(
            wallet_id=9,
            publisher_host="203.0.113.10",
            acknowledge_remote_state_unknown=False,
            confirmation="RELEASE",
        )
        with (
            patch.object(main, "_require_owner", lambda request: {"uid": 1}),
            patch.object(database, "release_nkn_publisher_wallet", AsyncMock()) as release,
            pytest.raises(main.HTTPException) as exc,
        ):
            await main.api_release_nkn_chaindb_publisher_wallet(Request({"type": "http"}), request)
        assert exc.value.status_code == 400
        release.assert_not_awaited()

    asyncio.run(run())


def test_publisher_bundle_cleanup_runs_when_install_fails(tmp_path, monkeypatch):
    asset = tmp_path / "asset"
    asset.write_text("asset", encoding="utf-8")
    calls = []

    def run_ssh(settings, command, *, key_file=None):
        calls.append(command)
        if command and command[0] == "bash":
            raise RuntimeError("install failed")

    monkeypatch.setattr(main, "_publisher_asset_path", lambda name: str(asset))
    monkeypatch.setattr(main, "_copy_publisher_file", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "_run_publisher_ssh", run_ssh)
    monkeypatch.setattr(main, "_prepare_publisher_known_hosts", lambda settings: "/data/nkn-chaindb-known-hosts")
    settings = {
        "publisher_host": "203.0.113.10",
        "publisher_port": 22,
        "publisher_user": "root",
        "publisher_password": "ssh-secret",
        "publisher_private_key": "",
        "publisher_host_key_sha256": PUBLISHER_FINGERPRINT,
        "beneficiary_address": "NKNBeneficiaryAddress",
        "publisher_wallet": {
            "wallet_json": '{"Address":"NKNPublisherAddress"}',
            "wallet_pswd": "publisher-password",
        },
        "endpoint": "https://acct.r2.cloudflarestorage.com",
        "bucket": "private-bucket",
        "access_key": "access-key",
        "secret_key": "secret-key",
        "prefix": "nkn/chaindb",
        "retention": 2,
    }
    with pytest.raises(RuntimeError, match="install failed"):
        main._deploy_nkn_chaindb_publisher_sync(settings)
    assert ["rm", "-rf", "/tmp/cashpilot-nkn-chaindb-bundle"] in calls


def test_publisher_bundle_carries_the_actual_ssh_port(tmp_path, monkeypatch):
    asset = tmp_path / "asset"
    asset.write_text("asset", encoding="utf-8")
    copied_config = {}

    def copy_file(settings, source, target, *, key_file=None):
        if source.endswith("publisher.json"):
            copied_config.update(__import__("json").loads(Path(source).read_text(encoding="utf-8")))

    monkeypatch.setattr(main, "_publisher_asset_path", lambda name: str(asset))
    monkeypatch.setattr(main, "_copy_publisher_file", copy_file)
    monkeypatch.setattr(main, "_run_publisher_ssh", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "_prepare_publisher_known_hosts", lambda settings: "/data/nkn-chaindb-known-hosts")
    settings = {
        "publisher_host": "203.0.113.10",
        "publisher_port": 26266,
        "publisher_user": "root",
        "publisher_password": "ssh-secret",
        "publisher_private_key": "",
        "publisher_host_key_sha256": PUBLISHER_FINGERPRINT,
        "beneficiary_address": "NKNBeneficiaryAddress",
        "publisher_wallet": {
            "wallet_json": '{"Address":"NKNPublisherAddress"}',
            "wallet_pswd": "publisher-password",
        },
        "endpoint": "https://acct.r2.cloudflarestorage.com",
        "bucket": "private-bucket",
        "access_key": "access-key",
        "secret_key": "secret-key",
        "prefix": "nkn/chaindb",
        "retention": 2,
    }

    main._deploy_nkn_chaindb_publisher_sync(settings)

    assert copied_config["ssh_port"] == 26266


def test_publisher_wallet_reservation_is_exclusive_and_idempotent(tmp_path):
    async def run():
        with (
            patch.object(database, "DB_DIR", tmp_path),
            patch.object(database, "DB_PATH", tmp_path / "wallets.db"),
        ):
            await database.init_db()
            await database.import_nkn_wallet_records(
                [
                    {
                        "folder_name": "publisher-wallet",
                        "wallet_json": '{"Address":"NKNPublisherAddress"}',
                        "wallet_pswd": "publisher-password",
                    },
                    {
                        "folder_name": "worker-wallet",
                        "wallet_json": '{"Address":"NKNWorkerAddress"}',
                        "wallet_pswd": "worker-password",
                    },
                ]
            )
            first = await database.reserve_nkn_publisher_wallet(public_ip="203.0.113.10")
            second = await database.reserve_nkn_publisher_wallet(public_ip="203.0.113.10")
            worker = await database.lease_nkn_wallet("worker-a:nkn:ipv4-001", worker_id=1, public_ip="8.8.8.8")
            rows = await database.list_nkn_wallets()
            assert first["id"] == second["id"]
            assert first["reservation_created"] is True
            assert second["reservation_created"] is False
            assert first["wallet_json"] == '{"Address":"NKNPublisherAddress"}'
            assert worker["id"] != first["id"]
            assert next(row for row in rows if row["id"] == first["id"])["state"] == "RESERVED"

    asyncio.run(run())
