from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app import nkn_chaindb
from scripts import nkn_chaindb_publisher, nkn_chaindb_restore


def test_publisher_steps_stop_archive_start_before_upload():
    steps = nkn_chaindb_publisher.build_steps(
        container="cashpilot-nkn",
        data_dir="/opt/nkn",
        archive="/var/lib/cashpilot/snapshot.tar.zst",
    )
    rendered = [step[0] for step in steps]
    assert rendered.index("stop") < rendered.index("archive") < rendered.index("start") < rendered.index("upload")
    assert all("wallet.json" not in str(step) and "wallet.pswd" not in str(step) for step in steps)
    upload = next(step for name, step in steps if name == "upload")
    assert upload[0] == "aws"
    assert "--metadata" in upload
    archive = next(step for name, step in steps if name == "archive")
    assert "-3" in archive
    assert "-19" not in archive


def test_publisher_phase_timeout_fits_inside_the_six_hour_service_budget():
    assert nkn_chaindb_publisher.PUBLISH_OPERATION_TIMEOUT == 2 * 60 * 60
    assert nkn_chaindb_publisher.PUBLISH_UPLOAD_TIMEOUT == 3 * 60 * 60
    assert nkn_chaindb_publisher.PUBLISH_OPERATION_TIMEOUT + nkn_chaindb_publisher.PUBLISH_UPLOAD_TIMEOUT < 6 * 60 * 60


def test_restore_command_uses_staging_and_preserves_identity_files():
    command = nkn_chaindb_restore.restore_plan("/opt/nkn", "/tmp/snapshot.tar.zst")
    assert command["staging"].endswith("ChainDB.new")
    assert command["backup"].startswith("/opt/nkn/ChainDB.backup-")
    assert command["preserve"] == ["config.json", "wallet.json", "wallet.pswd", "ChainDB.config"]


def test_restore_phase_timeout_fits_inside_the_six_hour_worker_budget():
    assert nkn_chaindb_restore.SNAPSHOT_OPERATION_TIMEOUT == 90 * 60
    assert nkn_chaindb_restore.SNAPSHOT_OPERATION_TIMEOUT * 3 < 6 * 60 * 60


def test_restore_member_listing_uses_archive_entry_safety_contract(monkeypatch):
    class FakeArchive:
        def __iter__(self):
            return iter(
                [
                    type(
                        "Entry",
                        (),
                        {
                            "name": "ChainDB/link",
                            "linkname": "../../wallet.json",
                            "issym": lambda _: True,
                            "islnk": lambda _: False,
                            "isdev": lambda _: False,
                            "isfifo": lambda _: False,
                        },
                    )()
                ]
            )

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(nkn_chaindb_restore.tarfile, "open", lambda **kwargs: FakeArchive())
    monkeypatch.setattr(
        nkn_chaindb_restore.subprocess,
        "Popen",
        lambda *args, **kwargs: type(
            "Proc",
            (),
            {"stdout": __import__("io").BytesIO(), "wait": lambda self, timeout: 0, "kill": lambda self: None},
        )(),
    )
    with pytest.raises(ValueError, match="link"):
        nkn_chaindb_restore.list_members("/tmp/snapshot.tar.zst")


def test_restore_rejects_non_nkn_data_dir():
    try:
        nkn_chaindb_restore.restore_plan("/", "/tmp/x")
    except ValueError:
        pass
    else:
        raise AssertionError("root data directory must be rejected")


def test_publisher_uses_multipart_capable_aws_cli_and_publishes_manifest_last(tmp_path, monkeypatch):
    archive = tmp_path / "snapshot.tar.zst"
    archive.write_bytes(b"archive")
    manifest = {
        "archive_key": "nkn/chaindb/snapshots/1-20260823T120000Z-" + "a" * 64 + ".tar.zst",
        "sha256": "a" * 64,
        "size_bytes": len(b"archive"),
    }
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs.get("env", {})))
        from subprocess import CompletedProcess

        if "head-object" in args:
            if args[args.index("--key") + 1].endswith("latest.json"):
                manifest_path = next(
                    command[command.index("cp") + 1]
                    for command, _ in calls
                    if "s3" in command and "cp" in command and command[command.index("cp") + 1].endswith(".json")
                )
                return CompletedProcess(args, 0, f'{{"ContentLength": {os.path.getsize(manifest_path)}}}'.encode(), b"")
            return CompletedProcess(
                args,
                0,
                f'{{"ContentLength": {len(b"archive")}, "Metadata": {{"sha256": "{manifest["sha256"]}"}}}}'.encode(),
                b"",
            )
        if "list-objects-v2" in args:
            return CompletedProcess(args, 0, b'{"Contents": []}', b"")
        return CompletedProcess(args, 0, b"{}", b"")

    monkeypatch.setattr(nkn_chaindb_publisher, "_run", run)
    result = nkn_chaindb_publisher.upload_snapshot(
        {
            "endpoint": "https://acct.r2.cloudflarestorage.com",
            "bucket": "private-bucket",
            "access_key_id": "access-key",
            "secret_access_key": "secret-key",
            "prefix": "nkn/chaindb",
            "retention": 2,
        },
        archive,
        manifest,
    )

    commands = [entry[0] for entry in calls]
    snapshot_cp = next(i for i, command in enumerate(commands) if "s3" in command and "cp" in command)
    manifest_cp = max(i for i, command in enumerate(commands) if "s3" in command and "cp" in command)
    assert snapshot_cp < manifest_cp
    assert any("head-object" in command for command in commands[snapshot_cp + 1 : manifest_cp])
    assert all("secret-key" not in " ".join(command) for command in commands)
    assert any(env.get("AWS_SECRET_ACCESS_KEY") == "secret-key" for _, env in calls)
    assert result["archive_key"] == manifest["archive_key"]


def test_publisher_rejects_remote_digest_metadata_mismatch(tmp_path, monkeypatch):
    archive = tmp_path / "snapshot.tar.zst"
    archive.write_bytes(b"archive")
    manifest = {
        "archive_key": "nkn/chaindb/snapshots/1-20260823T120000Z-" + "a" * 64 + ".tar.zst",
        "sha256": "a" * 64,
        "size_bytes": len(b"archive"),
    }

    def run(args, **kwargs):
        from subprocess import CompletedProcess

        if "head-object" in args:
            return CompletedProcess(
                args,
                0,
                b'{"ContentLength": 7, "Metadata": {"sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}}',
                b"",
            )
        return CompletedProcess(args, 0, b'{"Contents": []}', b"")

    monkeypatch.setattr(nkn_chaindb_publisher, "_run", run)
    with pytest.raises(RuntimeError, match="digest metadata"):
        nkn_chaindb_publisher.upload_snapshot(
            {
                "endpoint": "https://acct.r2.cloudflarestorage.com",
                "bucket": "private-bucket",
                "access_key_id": "access-key",
                "secret_access_key": "secret-key",
                "prefix": "nkn/chaindb",
                "retention": 2,
            },
            archive,
            manifest,
        )


def test_publish_once_forces_archive_overwrite_and_cleans_after_upload_failure(tmp_path, monkeypatch):
    data_dir = tmp_path / "nkn"
    chain_db = data_dir / "ChainDB"
    chain_db.mkdir(parents=True)
    (chain_db / "CURRENT").write_bytes(b"chain-data")
    archive_dir = tmp_path / "archives"
    archive_dir.mkdir()
    stale_archive = archive_dir / "chaindb.tar.zst"
    stale_archive.write_bytes(b"stale")
    zstd_calls = []

    class FakeTar:
        stdout = io.BytesIO(b"tar-stream")

        @staticmethod
        def wait(timeout):
            return 0

    def run_process(args, **kwargs):
        zstd_calls.append(args)
        output = Path(args[args.index("-o") + 1])
        output.write_bytes(b"new-archive")
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(
        nkn_chaindb_publisher.shutil, "disk_usage", lambda path: shutil._ntuple_diskusage(10**12, 0, 10**12)
    )
    monkeypatch.setattr(
        nkn_chaindb_publisher,
        "_node_state",
        lambda container: {"syncState": "PERSIST_FINISHED", "height": 42},
    )
    monkeypatch.setattr(
        nkn_chaindb_publisher,
        "_run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, b"", b""),
    )
    monkeypatch.setattr(
        nkn_chaindb_publisher,
        "_resolved_image",
        lambda container, configured_image="nknorg/nkn:latest": "nknorg/nkn@sha256:" + "b" * 64,
    )
    monkeypatch.setattr(nkn_chaindb_publisher.subprocess, "Popen", lambda *args, **kwargs: FakeTar())
    monkeypatch.setattr(nkn_chaindb_publisher.subprocess, "run", run_process)
    monkeypatch.setattr(
        nkn_chaindb_publisher,
        "upload_snapshot",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("upload failed")),
    )

    with pytest.raises(RuntimeError, match="upload failed"):
        nkn_chaindb_publisher.publish_once(
            {
                "endpoint": "https://acct.r2.cloudflarestorage.com",
                "bucket": "private-bucket",
                "access_key_id": "access-key",
                "secret_access_key": "secret-key",
                "prefix": "nkn/chaindb",
                "retention": 2,
                "data_dir": str(data_dir),
                "archive_dir": str(archive_dir),
                "container": "cashpilot-nkn",
                "image": "nknorg/nkn:latest",
            }
        )
    assert "-f" in zstd_calls[0]
    assert not stale_archive.exists()


def test_publisher_resolves_running_official_image_digest(monkeypatch):
    digest = "a" * 64
    image_id = "b" * 64

    def run(args, **kwargs):
        if args[:3] == ["docker", "inspect", "--format"]:
            return subprocess.CompletedProcess(args, 0, f"sha256:{image_id}\n".encode(), b"")
        if args[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(args, 0, json.dumps([f"nknorg/nkn@sha256:{digest}"]).encode(), b"")
        raise AssertionError(args)

    monkeypatch.setattr(nkn_chaindb_publisher, "_run", run)
    assert nkn_chaindb_publisher._resolved_image("cashpilot-nkn") == f"nknorg/nkn@sha256:{digest}"


def test_publisher_refuses_image_without_official_repo_digest(monkeypatch):
    image_id = "b" * 64

    def run(args, **kwargs):
        if args[:3] == ["docker", "inspect", "--format"]:
            return subprocess.CompletedProcess(args, 0, f"sha256:{image_id}\n".encode(), b"")
        if args[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(args, 0, b"[]", b"")
        raise AssertionError(args)

    monkeypatch.setattr(nkn_chaindb_publisher, "_run", run)
    with pytest.raises(RuntimeError, match="official repository digest"):
        nkn_chaindb_publisher._resolved_image("cashpilot-nkn")


def test_verify_only_reports_installed_syncing_before_chaindb_exists(tmp_path, monkeypatch, capsys):
    data_dir = tmp_path / "nkn"
    data_dir.mkdir()
    config_path = tmp_path / "publisher.json"
    config_path.write_text(
        json.dumps(
            {
                "endpoint": "https://acct.r2.cloudflarestorage.com",
                "bucket": "private-bucket",
                "access_key_id": "access-key",
                "secret_access_key": "secret-key",
                "prefix": "nkn/chaindb",
                "data_dir": str(data_dir),
                "container": "cashpilot-nkn",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        nkn_chaindb_publisher,
        "_run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, b"", b""),
    )
    assert nkn_chaindb_publisher.main(["--config", str(config_path), "--verify-only"]) == 0
    assert json.loads(capsys.readouterr().out) == {"chaindb_ready": False, "status": "installed_syncing"}


def test_verify_only_passes_r2_environment_to_head_bucket(tmp_path, monkeypatch, capsys):
    data_dir = tmp_path / "nkn"
    data_dir.mkdir()
    config_path = tmp_path / "publisher.json"
    config_path.write_text(
        json.dumps(
            {
                "endpoint": "https://acct.r2.cloudflarestorage.com",
                "bucket": "private-bucket",
                "access_key_id": "access-key",
                "secret_access_key": "secret-key",
                "prefix": "nkn/chaindb",
                "data_dir": str(data_dir),
                "container": "cashpilot-nkn",
            }
        ),
        encoding="utf-8",
    )
    expected_env = {"AWS_ACCESS_KEY_ID": "access-key", "AWS_SECRET_ACCESS_KEY": "secret-key"}
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(nkn_chaindb_publisher, "_aws_env", lambda config: expected_env)
    monkeypatch.setattr(nkn_chaindb_publisher, "_run", run)

    assert nkn_chaindb_publisher.main(["--config", str(config_path), "--verify-only"]) == 0
    head_call = next(kwargs for args, kwargs in calls if "head-bucket" in args)
    assert head_call["env"] is expected_env


def test_publisher_node_state_supports_wget_when_curl_is_absent(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(
            args,
            0,
            b'{"result":{"syncState":"PERSIST_FINISHED"}}',
            b"",
        )

    monkeypatch.setattr(nkn_chaindb_publisher.subprocess, "run", run)
    assert nkn_chaindb_publisher._node_state("cashpilot-nkn")["syncState"] == "PERSIST_FINISHED"
    command = " ".join(str(value) for value in calls[0])
    assert "wget" in command
    assert "command -v curl" in command


def test_restore_node_state_supports_wget_when_curl_is_absent(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(
            args,
            0,
            b'{"result":{"syncState":"PERSIST_FINISHED"}}',
            b"",
        )

    monkeypatch.setattr(nkn_chaindb_restore.subprocess, "run", run)
    assert nkn_chaindb_restore._node_state("cashpilot-nkn")["syncState"] == "PERSIST_FINISHED"
    command = " ".join(str(value) for value in calls[0])
    assert "wget" in command
    assert "command -v curl" in command


def test_restore_request_honors_explicit_manifest_age(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    manifest = nkn_chaindb.build_manifest(
        prefix="nkn/chaindb",
        sha256="a" * 64,
        size_bytes=7,
        block_height=1,
        created_at=datetime.now(UTC) - timedelta(hours=72),
        image="nknorg/nkn:latest",
    )
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "manifest": manifest,
                "archive_url": "https://example.invalid/archive",
                "data_dir": "/opt/nkn",
                "container": "cashpilot-nkn",
                "prefix": "nkn/chaindb",
                "max_age_seconds": 96 * 60 * 60,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(nkn_chaindb_restore, "download_archive", lambda url, destination, expected_size: None)
    monkeypatch.setattr(
        nkn_chaindb_restore,
        "restore_archive",
        lambda *args, **kwargs: {"status": "restored", "backup": "/opt/nkn/backup"},
    )
    result = nkn_chaindb_restore.restore_request(request_path)
    assert result["status"] == "restored"


def test_wait_for_node_requires_persist_finished(monkeypatch):
    states = [{}, {"syncState": "SYNC_STARTED"}, {"syncState": "PERSIST_FINISHED", "height": 42}]
    monkeypatch.setattr(nkn_chaindb_restore, "_node_state", lambda container: states.pop(0))
    monkeypatch.setattr(nkn_chaindb_restore.time, "sleep", lambda seconds: None)
    evidence = nkn_chaindb_restore.wait_for_node("cashpilot-nkn", timeout=10, interval=0)
    assert evidence["syncState"] == "PERSIST_FINISHED"


def test_wait_for_node_times_out_without_persist_finished(monkeypatch):
    ticks = iter([0, 1, 2, 3])
    monkeypatch.setattr(nkn_chaindb_restore.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(nkn_chaindb_restore.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(nkn_chaindb_restore, "_node_state", lambda container: {"syncState": "SYNC_STARTED"})
    with pytest.raises(RuntimeError, match="PERSIST_FINISHED"):
        nkn_chaindb_restore.wait_for_node("cashpilot-nkn", timeout=2, interval=0)


def test_standalone_tools_import_without_an_app_package(tmp_path):
    source_root = os.path.dirname(os.path.dirname(__file__))
    publisher = tmp_path / "nkn_chaindb_publisher.py"
    restore = tmp_path / "nkn_chaindb_restore.py"
    contract = tmp_path / "nkn_chaindb.py"
    for source, target in (
        (os.path.join(source_root, "scripts", "nkn_chaindb_publisher.py"), publisher),
        (os.path.join(source_root, "scripts", "nkn_chaindb_restore.py"), restore),
        (os.path.join(source_root, "app", "nkn_chaindb.py"), contract),
    ):
        shutil.copyfile(source, target)
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    for tool in (publisher, restore):
        result = subprocess.run(
            [sys.executable, str(tool), "--help"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


def test_restore_failure_cleans_staging_before_restarting_original_node(monkeypatch):
    data_dir = "/opt/nkn"
    archive = "/tmp/snapshot.tar.zst"
    monkeypatch.setattr(nkn_chaindb_restore, "verify_file", lambda *args, **kwargs: {})
    monkeypatch.setattr(nkn_chaindb_restore, "list_members", lambda *args, **kwargs: ["ChainDB/file"])

    existing = {"/opt/nkn/ChainDB"}

    class FakePath:
        def __init__(self, value):
            self.value = str(value)

        def __truediv__(self, name):
            return FakePath(f"{self.value}/{name}")

        def __str__(self):
            return self.value

        def exists(self):
            return self.value in existing

        def is_dir(self):
            return self.exists()

        def rename(self, target):
            target_value = str(target)
            existing.remove(self.value)
            existing.add(target_value)

        def is_absolute(self):
            return self.value.startswith("/")

        @property
        def name(self):
            return self.value.rstrip("/").rsplit("/", 1)[-1]

        def glob(self, pattern):
            prefix = self.value + "/" + pattern.rstrip("*")
            return [FakePath(value) for value in existing if value.startswith(prefix)]

    monkeypatch.setattr(nkn_chaindb_restore, "Path", FakePath)
    monkeypatch.setattr(
        nkn_chaindb_restore.shutil,
        "rmtree",
        lambda path: existing.remove(str(path)),
    )

    def extract(_archive, staging):
        existing.add(str(staging))

    monkeypatch.setattr(nkn_chaindb_restore, "extract_to_staging", extract)
    monkeypatch.setattr(
        nkn_chaindb_restore,
        "restore_plan",
        lambda data_dir, archive_path: {
            "data_dir": "/opt/nkn",
            "archive": "/tmp/snapshot.tar.zst",
            "staging": "/opt/nkn/ChainDB.new",
            "backup": "/opt/nkn/ChainDB.backup-test",
            "preserve": list(nkn_chaindb_restore.PRESERVE_FILES),
        },
    )
    events = []
    with pytest.raises(RuntimeError, match="did not provide evidence"):
        nkn_chaindb_restore.restore_archive(
            data_dir,
            archive,
            expected_sha256="a" * 64,
            expected_size=7,
            stop_node=lambda: events.append("stop"),
            start_node=lambda: events.append("start"),
            verify_node=lambda: {},
        )
    assert "/opt/nkn/ChainDB" in existing
    assert not any(value.startswith("/opt/nkn/ChainDB.new") for value in existing)
    assert not any(value.startswith("/opt/nkn/ChainDB.backup-") for value in existing)
    assert events == ["stop", "start", "stop", "start"]
