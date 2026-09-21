#!/usr/bin/env python3
"""Verify cached runtime artifacts before atomically activating a release."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HEX64 = re.compile(r"^[a-f0-9]{64}$")
SEMVER = re.compile(r"^v\d+\.\d+\.\d+$")
PLATFORMS = {"linux/amd64", "linux/arm64"}
SOURCES = {"github-release", "ghcr"}


def _canonical_unsigned(manifest: dict) -> bytes:
    unsigned = {key: value for key, value in manifest.items() if key != "signature"}
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()


def _validate(manifest: dict) -> list[dict]:
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported schema_version")
    if not SEMVER.fullmatch(str(manifest.get("release", ""))):
        raise ValueError("invalid release")
    if not SEMVER.fullmatch(str(manifest.get("rollback_release", ""))):
        raise ValueError("invalid rollback_release")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("artifacts must be a non-empty list")
    for artifact in artifacts:
        if artifact.get("architecture") not in PLATFORMS or artifact.get("source") not in SOURCES:
            raise ValueError("invalid artifact architecture or source")
        if not HEX64.fullmatch(str(artifact.get("sha256", ""))):
            raise ValueError("invalid artifact sha256")
        path = str(artifact.get("path", ""))
        if not path or Path(path).name != path:
            raise ValueError("artifact path must be a filename")
        reference = str(artifact.get("reference", ""))
        if not re.fullmatch(r"ghcr\.io/.+@sha256:[a-f0-9]{64}", reference):
            raise ValueError("GHCR reference must use an immutable digest")
    return artifacts


def _verify_signature(manifest: dict, key: str | None) -> None:
    signature = manifest.get("signature")
    if signature is None:
        if key:
            raise ValueError("signature required when a verification key is supplied")
        return
    if not key or signature.get("algorithm") != "hmac-sha256":
        raise ValueError("signed manifest requires CASHPILOT_RUNTIME_MANIFEST_KEY")
    expected = hmac.new(key.encode(), _canonical_unsigned(manifest), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, str(signature.get("value", ""))):
        raise ValueError("manifest signature mismatch")


def _pull_ghcr(reference: str) -> None:
    """Pull only immutable GHCR references; tags are rejected by validation."""
    subprocess.run(["docker", "pull", reference], check=True)


def verify(manifest_path: Path, artifact_dir: Path, state_path: Path, key: str | None, pull: bool = False) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = _validate(manifest)
    _verify_signature(manifest, key)
    verified = []
    for artifact in artifacts:
        if pull and artifact["source"] == "ghcr":
            _pull_ghcr(artifact["reference"])
        path = artifact_dir / artifact["path"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if not hmac.compare_digest(digest, artifact["sha256"]):
            raise ValueError(f"SHA-256 mismatch: {artifact['name']}")
        verified.append({"name": artifact["name"], "path": str(path), "sha256": digest})

    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"release": manifest["release"], "rollback_release": manifest["rollback_release"], "artifacts": verified}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=state_path.parent, delete=False) as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, state_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--key-env", default="CASHPILOT_RUNTIME_MANIFEST_KEY")
    parser.add_argument(
        "--pull", action="store_true", help="pull immutable GHCR references before hashing cached artifacts"
    )
    args = parser.parse_args()
    try:
        verify(args.manifest, args.artifact_dir, args.state, os.environ.get(args.key_env), args.pull)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
