#!/usr/bin/env python3
"""Safely restore an NKN ChainDB archive into a new/staged data directory."""

from __future__ import annotations

import argparse
import contextlib
import json
import secrets
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from app.nkn_chaindb import validate_archive_entries, validate_manifest, verify_file  # noqa: E402
except ModuleNotFoundError:  # Installed consumer keeps the contract beside this script.
    from nkn_chaindb import (  # type: ignore[no-redef]  # noqa: E402
        validate_archive_entries,
        validate_manifest,
        verify_file,
    )

PRESERVE_FILES = ["config.json", "wallet.json", "wallet.pswd", "ChainDB.config"]
SNAPSHOT_OPERATION_TIMEOUT = 90 * 60


def _run(args: list[str], *, input_data: bytes | None = None, timeout: int = 900) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(args, input=input_data, capture_output=True, check=False, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"command failed: {args[0]}")
    return result


def _safe_data_dir(data_dir: str | Path) -> PurePosixPath:
    path = PurePosixPath(str(data_dir))
    if not path.is_absolute() or path == PurePosixPath("/") or path.name != "nkn":
        raise ValueError("NKN data directory must be an absolute /.../nkn directory")
    return path


def restore_plan(data_dir: str | Path, archive_path: str | Path) -> dict[str, Any]:
    data = _safe_data_dir(data_dir)
    archive = PurePosixPath(str(archive_path))
    if not archive.is_absolute() or archive.name in {"", ".", ".."}:
        raise ValueError("archive path must be absolute")
    token = secrets.token_hex(8)
    return {
        "data_dir": str(data),
        "archive": str(archive),
        "staging": str(data / "ChainDB.new"),
        "backup": str(data / f"ChainDB.backup-{int(time.time())}-{token}"),
        "preserve": list(PRESERVE_FILES),
    }


def list_members(archive_path: str | Path) -> list[str]:
    """List zstd-compressed tar names through external tools without extraction."""
    decompressor = subprocess.Popen(
        ["zstd", "-q", "-d", "-c", str(archive_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert decompressor.stdout is not None
    try:
        with tarfile.open(fileobj=decompressor.stdout, mode="r|") as archive:
            entries = list(archive)
    except Exception:
        with contextlib.suppress(Exception):
            decompressor.kill()
        raise
    finally:
        decompressor.stdout.close()
    decompressor_return_code = decompressor.wait(timeout=SNAPSHOT_OPERATION_TIMEOUT)
    if decompressor_return_code != 0:
        raise RuntimeError("snapshot archive listing failed")
    validate_archive_entries(entries)
    return [str(entry.name) for entry in entries]


def extract_to_staging(archive_path: str | Path, staging: Path) -> None:
    extract_root = staging.parent / f".chaindb-extract-{secrets.token_hex(8)}"
    extract_root.mkdir(mode=0o700, parents=False, exist_ok=False)
    proc = subprocess.Popen(["zstd", "-q", "-d", "-c", str(archive_path)], stdout=subprocess.PIPE)
    try:
        assert proc.stdout is not None
        extracted = subprocess.run(
            ["tar", "-x", "-f", "-", "--no-same-owner", "--no-same-permissions", "-C", str(extract_root)],
            stdin=proc.stdout,
            capture_output=True,
            check=False,
            timeout=SNAPSHOT_OPERATION_TIMEOUT,
        )
        proc.stdout.close()
        return_code = proc.wait(timeout=30)
    except Exception:
        proc.kill()
        proc.wait(timeout=30)
        with contextlib.suppress(OSError):
            shutil.rmtree(extract_root)
        raise
    if extracted.returncode != 0 or return_code != 0:
        with contextlib.suppress(OSError):
            shutil.rmtree(extract_root)
        raise RuntimeError("snapshot extraction failed")
    extracted_db = extract_root / "ChainDB"
    if not extracted_db.is_dir():
        with contextlib.suppress(OSError):
            shutil.rmtree(extract_root)
        raise RuntimeError("snapshot archive did not contain ChainDB")
    extracted_db.rename(staging)
    extract_root.rmdir()


def restore_archive(
    data_dir: str | Path,
    archive_path: str | Path,
    *,
    expected_sha256: str,
    expected_size: int,
    stop_node: callable,
    start_node: callable,
    verify_node: callable,
) -> dict[str, Any]:
    plan = restore_plan(data_dir, archive_path)
    verify_file(plan["archive"], expected_sha256=expected_sha256, expected_size=expected_size)
    list_members(plan["archive"])
    staging = Path(plan["staging"])
    if staging.exists():
        raise RuntimeError("staging ChainDB already exists")
    extract_to_staging(plan["archive"], staging)
    current = Path(plan["data_dir"]) / "ChainDB"
    backup = Path(plan["backup"])
    start_attempted = False
    try:
        stop_node()
        if current.exists():
            current.rename(backup)
        staging.rename(current)
        start_attempted = True
        start_node()
        evidence = verify_node()
        if not evidence:
            raise RuntimeError("restored NKN node did not provide evidence")
        return {"status": "restored", "backup": str(backup), "evidence": evidence}
    except Exception:
        # Ensure a failed post-swap process cannot keep using the temporary DB
        # while the known-good backup is put back in place.
        if start_attempted:
            with contextlib.suppress(Exception):
                stop_node()
        with contextlib.suppress(OSError):
            if current.exists() and backup.exists():
                current.rename(staging)
        if backup.exists() and not current.exists():
            backup.rename(current)
        with contextlib.suppress(OSError):
            if staging.exists():
                shutil.rmtree(staging)
        with contextlib.suppress(Exception):
            start_node()
        raise


def download_archive(url: str, destination: Path, *, expected_size: int) -> None:
    """Stream a short-lived HTTPS object to disk with a strict size ceiling."""
    from urllib.parse import urlsplit

    parsed = urlsplit(str(url or ""))
    if parsed.scheme != "https" or not parsed.netloc or int(expected_size) <= 0:
        raise ValueError("snapshot archive URL must be HTTPS and have a positive size")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    size = 0
    with (
        urllib.request.urlopen(  # noqa: S310
            str(url), timeout=SNAPSHOT_OPERATION_TIMEOUT
        ) as response,
        destination.open("wb") as output,
    ):
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > int(expected_size):
                raise ValueError("snapshot download exceeds manifest size")
            output.write(chunk)
    if size != int(expected_size):
        raise ValueError("snapshot download size does not match manifest")


def restore_request(request_path: str | Path) -> dict[str, Any]:
    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    if not isinstance(request, dict):
        raise ValueError("snapshot request must be an object")
    manifest = request.get("manifest")
    if not isinstance(manifest, dict):
        raise ValueError("snapshot request manifest is missing")
    raw_max_age = request.get("max_age_seconds", 48 * 60 * 60)
    if isinstance(raw_max_age, bool) or not 1 <= int(raw_max_age) <= 30 * 24 * 60 * 60:
        raise ValueError("snapshot request max_age_seconds is invalid")
    validated = validate_manifest(manifest, max_age_seconds=int(raw_max_age))
    prefix = str(request.get("prefix") or "nkn/chaindb").strip().strip("/")
    if not prefix or ".." in prefix.split("/") or not str(validated["archive_key"]).startswith(f"{prefix}/snapshots/"):
        raise ValueError("snapshot request prefix does not match archive")
    data_dir = _safe_data_dir(str(request.get("data_dir") or ""))
    container = str(request.get("container") or "").strip()
    if container != "cashpilot-nkn":
        raise ValueError("invalid NKN inner container")
    runtime_data_dir = Path(str(data_dir))
    archive = runtime_data_dir / f".chaindb-download-{secrets.token_hex(8)}.tar.zst"
    try:
        download_archive(
            str(request.get("archive_url") or ""),
            Path(str(archive)),
            expected_size=int(validated["size_bytes"]),
        )
        result = restore_archive(
            runtime_data_dir,
            archive,
            expected_sha256=str(validated["sha256"]),
            expected_size=int(validated["size_bytes"]),
            stop_node=lambda: _run(["docker", "stop", "--time", "120", container], timeout=180),
            start_node=lambda: _run(["docker", "start", container], timeout=180),
            verify_node=lambda: wait_for_node(container),
        )
        return {"status": "restored", "backup": result["backup"]}
    finally:
        archive.unlink(missing_ok=True)


def _node_state(container: str) -> dict[str, Any]:
    request = '{"jsonrpc":"2.0","method":"getnodestate","params":{},"id":1}'
    result = subprocess.run(
        [
            "docker",
            "exec",
            container,
            "sh",
            "-lc",
            "if command -v curl >/dev/null 2>&1; then "
            "curl -fsS --max-time 5 -H 'Content-Type: application/json' "
            f"-d '{request}' http://127.0.0.1:30003; "
            "elif command -v wget >/dev/null 2>&1; then "
            f"wget -qO- --timeout=5 --header='Content-Type: application/json' --post-data='{request}' "
            "http://127.0.0.1:30003; else exit 127; fi",
        ],
        capture_output=True,
        check=False,
        timeout=20,
    )
    if result.returncode != 0:
        return {}
    try:
        payload = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    state = payload.get("result") if isinstance(payload, dict) else None
    return state if isinstance(state, dict) else {}


def wait_for_node(container: str, *, timeout: int = 300, interval: int = 5) -> dict[str, Any]:
    deadline = time.monotonic() + int(timeout)
    while time.monotonic() <= deadline:
        state = _node_state(container)
        sync_state = str(state.get("syncState") or state.get("sync_state") or "")
        if sync_state == "PERSIST_FINISHED":
            return state
        time.sleep(max(0, int(interval)))
    raise RuntimeError("restored NKN node did not reach PERSIST_FINISHED")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--size-bytes", required=True, type=int)
    parser.add_argument("--request")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    plan = restore_plan(args.data_dir, args.archive)
    if args.dry_run:
        print(json.dumps(plan, sort_keys=True))
        return 0
    if args.request:
        print(json.dumps(restore_request(args.request), sort_keys=True))
        return 0
    verify_file(args.archive, expected_sha256=args.sha256, expected_size=args.size_bytes)
    list_members(args.archive)
    print(json.dumps({"status": "validated", **plan}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
