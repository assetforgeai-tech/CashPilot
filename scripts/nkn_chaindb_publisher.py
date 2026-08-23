#!/usr/bin/env python3
"""Daily cold publisher for an NKN ChainDB snapshot.

The default invocation is intentionally ``--verify-only`` friendly: operators
can validate disk, Docker, and R2 configuration before the first destructive
(clean stop/start) snapshot operation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from app.nkn_chaindb import build_manifest, retained_snapshot_keys  # noqa: E402
except ModuleNotFoundError:  # Installed publisher keeps the contract beside this script.
    from nkn_chaindb import build_manifest, retained_snapshot_keys  # type: ignore[no-redef]  # noqa: E402

PUBLISH_OPERATION_TIMEOUT = 2 * 60 * 60
PUBLISH_UPLOAD_TIMEOUT = 3 * 60 * 60


def build_steps(*, container: str, data_dir: str, archive: str) -> list[tuple[str, list[str]]]:
    data = str(Path(data_dir).resolve())
    archive_path = str(Path(archive).resolve())
    if Path(data).name != "nkn" or data == "/":
        raise ValueError("publisher data_dir must be an NKN data directory")
    return [
        ("verify", ["docker", "inspect", container]),
        ("stop", ["docker", "stop", "--time", "120", container]),
        ("archive", ["tar", "-C", data, "-cf", "-", "ChainDB", "|", "zstd", "-T0", "-3", "-o", archive_path]),
        ("start", ["docker", "start", container]),
        (
            "upload",
            [
                "aws",
                "s3",
                "cp",
                archive_path,
                "s3://<bucket>/<immutable-key>",
                "--metadata",
                "sha256=<digest>",
            ],
        ),
        ("publish", ["aws", "s3", "cp", "<manifest>", "s3://<bucket>/<latest-key>"]),
    ]


def _run(
    args: list[str],
    *,
    timeout: int = 900,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(args, capture_output=True, check=False, timeout=timeout, env=env)
    if check and result.returncode != 0:
        raise RuntimeError(f"command failed: {args[0]}")
    return result


def _aws_env(config: dict[str, Any]) -> dict[str, str]:
    access_key = str(config.get("access_key_id") or "").strip()
    secret_key = str(config.get("secret_access_key") or "").strip()
    if not access_key or not secret_key:
        raise ValueError("R2 credentials are required")
    env = os.environ.copy()
    env.update(
        {
            "AWS_ACCESS_KEY_ID": access_key,
            "AWS_SECRET_ACCESS_KEY": secret_key,
            "AWS_DEFAULT_REGION": "auto",
            "AWS_EC2_METADATA_DISABLED": "true",
        }
    )
    return env


def _aws_args(config: dict[str, Any]) -> list[str]:
    endpoint = str(config.get("endpoint") or "").strip().rstrip("/")
    if not endpoint.startswith("https://") or "?" in endpoint or "#" in endpoint:
        raise ValueError("R2 endpoint must be HTTPS without a query")
    return ["aws", "--endpoint-url", endpoint]


def _s3_target(bucket: str, key: str) -> str:
    bucket = str(bucket or "").strip()
    key = str(key or "").strip().lstrip("/")
    if not bucket or not key or ".." in key.split("/"):
        raise ValueError("R2 object target is invalid")
    return f"s3://{bucket}/{key}"


def _head_object(config: dict[str, Any], key: str, *, env: dict[str, str]) -> dict[str, Any]:
    result = _run(
        [*_aws_args(config), "s3api", "head-object", "--bucket", str(config["bucket"]), "--key", key],
        timeout=120,
        env=env,
    )
    try:
        value = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("R2 HEAD returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError("R2 HEAD returned an invalid object")
    return value


def upload_snapshot(config: dict[str, Any], archive: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Use AWS CLI multipart upload and publish the mutable manifest last."""
    env = _aws_env(config)
    bucket = str(config["bucket"])
    archive_key = str(manifest["archive_key"])
    _run(
        [
            *_aws_args(config),
            "s3",
            "cp",
            str(archive),
            _s3_target(bucket, archive_key),
            "--only-show-errors",
            "--content-type",
            "application/zstd",
            "--metadata",
            f"sha256={manifest['sha256']}",
        ],
        timeout=PUBLISH_UPLOAD_TIMEOUT,
        env=env,
    )
    head = _head_object(config, archive_key, env=env)
    if int(head.get("ContentLength") or 0) != int(manifest["size_bytes"]):
        raise RuntimeError("R2 archive size differs from manifest")
    metadata = head.get("Metadata") if isinstance(head.get("Metadata"), dict) else {}
    if str(metadata.get("sha256") or "").lower() != str(manifest["sha256"]):
        raise RuntimeError("R2 archive digest metadata differs from manifest")

    prefix = str(config.get("prefix") or "nkn/chaindb").strip("/")
    manifest_key = f"{prefix}/manifests/latest.json"
    manifest_file = archive.with_suffix(".latest.json")
    manifest_file.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    manifest_size = manifest_file.stat().st_size
    try:
        _run(
            [
                *_aws_args(config),
                "s3",
                "cp",
                str(manifest_file),
                _s3_target(bucket, manifest_key),
                "--only-show-errors",
                "--content-type",
                "application/json",
            ],
            timeout=120,
            env=env,
        )
        manifest_head = _head_object(config, manifest_key, env=env)
        if int(manifest_head.get("ContentLength") or 0) != manifest_size:
            raise RuntimeError("R2 manifest size differs from local latest.json")
    finally:
        manifest_file.unlink(missing_ok=True)

    # Cleanup happens only after latest.json is durable. Failure here leaves a
    # harmless extra immutable object rather than invalidating the publication.
    try:
        listed = _run(
            [*_aws_args(config), "s3api", "list-objects-v2", "--bucket", bucket, "--prefix", f"{prefix}/snapshots/"],
            timeout=120,
            env=env,
        )
        payload = json.loads(listed.stdout.decode("utf-8"))
        keys = [str(item.get("Key") or "") for item in (payload.get("Contents") or []) if isinstance(item, dict)]
        keep = set(retained_snapshot_keys(keys, keep=int(config.get("retention") or 2)))
        for key in keys:
            if key and key not in keep:
                _run(
                    [*_aws_args(config), "s3api", "delete-object", "--bucket", bucket, "--key", key],
                    timeout=120,
                    env=env,
                )
    except Exception as exc:
        print(f"warning: R2 retention cleanup skipped ({type(exc).__name__})", file=sys.stderr)
    return {
        "archive_key": archive_key,
        "manifest_key": manifest_key,
        "sha256": str(manifest["sha256"]),
        "size_bytes": int(manifest["size_bytes"]),
    }


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _node_state(container: str) -> dict[str, Any]:
    request = '{"jsonrpc":"2.0","method":"getnodestate","params":{},"id":1}'
    result = _run(
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
        timeout=20,
        check=False,
    )
    if result.returncode != 0:
        return {}
    try:
        payload = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload.get("result") if isinstance(payload, dict) and isinstance(payload.get("result"), dict) else {}


def _resolved_image(container: str, configured_image: str = "nknorg/nkn:latest") -> str:
    """Record the immutable digest of the official image used by the node."""
    configured = str(configured_image or "").strip()
    if not re.fullmatch(r"nknorg/nkn(?::[A-Za-z0-9._-]+|@sha256:[0-9a-f]{64})", configured):
        raise RuntimeError("publisher container is not using an official NKN image")
    inspected = _run(["docker", "inspect", "--format", "{{.Image}}", container], timeout=20)
    image_id = inspected.stdout.decode("utf-8", errors="strict").strip().lower()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise RuntimeError("publisher NKN image digest is unavailable")

    repo_digests = _run(
        ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image_id], timeout=20, check=False
    )
    if repo_digests.returncode == 0:
        try:
            values = json.loads(repo_digests.stdout.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            values = []
        if isinstance(values, list):
            for value in values:
                candidate = str(value or "").strip().lower()
                if re.fullmatch(r"nknorg/nkn@sha256:[0-9a-f]{64}", candidate):
                    return candidate
    raise RuntimeError("publisher NKN image has no official repository digest")


def _config(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("publisher config must be an object")
    required = ("endpoint", "bucket", "access_key_id", "secret_access_key", "prefix", "data_dir", "container")
    if any(not str(data.get(key) or "").strip() for key in required):
        raise ValueError("publisher config is incomplete")
    return data


def publish_once(config: dict[str, Any]) -> dict[str, Any]:
    data = _config(Path(config["config_path"])) if "config_path" in config else config
    data_dir = Path(str(data["data_dir"])).resolve()
    chain_db = data_dir / "ChainDB"
    if not chain_db.is_dir():
        raise RuntimeError("NKN ChainDB directory is missing")
    archive_dir = Path(str(data.get("archive_dir") or "/var/lib/cashpilot/nkn-chaindb")).resolve()
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive = archive_dir / "chaindb.tar.zst"
    required_bytes = sum(path.stat().st_size for path in chain_db.rglob("*") if path.is_file())
    free_bytes = shutil.disk_usage(archive_dir).free
    if required_bytes <= 0 or free_bytes < max(required_bytes + 2 * 1024**3, int(required_bytes * 1.25)):
        raise RuntimeError("publisher disk does not have enough headroom for a ChainDB archive")
    archive.unlink(missing_ok=True)
    try:
        state = _node_state(str(data["container"]))
        sync_state = str(state.get("syncState") or state.get("sync_state") or "")
        if sync_state != "PERSIST_FINISHED":
            raise RuntimeError("NKN node is not fully synchronized")
        height = int(state.get("height") or state.get("blockHeight") or state.get("heightOnDHT") or 0)
        if height < 0:
            raise RuntimeError("invalid NKN block height")
        _run(["docker", "inspect", str(data["container"])], timeout=20)
        image = _resolved_image(str(data["container"]), str(data.get("image") or "nknorg/nkn:latest"))
        start_result: subprocess.CompletedProcess[bytes] | None = None
        try:
            _run(["docker", "stop", "--time", "120", str(data["container"])], timeout=180)
            tar = subprocess.Popen(
                ["tar", "-C", str(data_dir), "-cf", "-", "ChainDB"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert tar.stdout is not None
            zstd = subprocess.run(
                ["zstd", "-T0", "-3", "-q", "-f", "-o", str(archive)],
                stdin=tar.stdout,
                capture_output=True,
                check=False,
                timeout=PUBLISH_OPERATION_TIMEOUT,
            )
            tar.stdout.close()
            tar_rc = tar.wait(timeout=30)
            if tar_rc != 0 or zstd.returncode != 0:
                raise RuntimeError("ChainDB archive failed")
        finally:
            start_result = _run(["docker", "start", str(data["container"])], timeout=180, check=False)
        if start_result is None or start_result.returncode != 0:
            raise RuntimeError("NKN node failed to restart after snapshot")

        digest, size = _sha256(archive)
        created = datetime.now(UTC).replace(microsecond=0)
        manifest = build_manifest(
            prefix=str(data["prefix"]),
            sha256=digest,
            size_bytes=size,
            block_height=height,
            created_at=created,
            image=image,
            network=str(data.get("network") or "mainnet"),
        )
        uploaded = upload_snapshot(data, archive, manifest)
        return {
            "status": "published",
            "archive_key": uploaded["archive_key"],
            "manifest_key": uploaded["manifest_key"],
            "sha256": digest,
            "size_bytes": size,
            "block_height": height,
            "created_at": manifest["created_at"],
            "image": image,
        }
    finally:
        archive.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    config = _config(Path(args.config))
    if args.verify_only:
        _run(["docker", "inspect", str(config["container"])], timeout=20)
        env = _aws_env(config)
        _run(
            [*_aws_args(config), "s3api", "head-bucket", "--bucket", str(config["bucket"])],
            timeout=120,
            env=env,
        )
        chaindb_ready = Path(str(config["data_dir"])).joinpath("ChainDB").is_dir()
        print(json.dumps({"status": "ready" if chaindb_ready else "installed_syncing", "chaindb_ready": chaindb_ready}))
        return 0
    print(json.dumps(publish_once(config), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
