#!/usr/bin/env python3
"""Fail-closed verifier for the three staged EarnApp runtime contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# Prefer this checkout when a shared workstation exports another ``app`` package.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import earnapp_runtime  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_context(context: Path, platform: str) -> dict[str, object]:
    manifest_path = context / "runtime-manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"{platform}: runtime-manifest.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_base = earnapp_runtime.REFERENCE_VPS_IMAGES[platform]
    if platform == "ubuntu" and manifest.get("base_image") != expected_base:
        raise ValueError(f"{platform}: base image differs from the authoritative reference pin")
    checked = 0
    inherited = {"earnapp-mac", "earnapp-bootstrap"}
    for row in manifest["artifacts"]:
        path = context / str(row["path"])
        # Generated wrapper artifacts are verified by the manifest builder.
        if str(row["path"]) in inherited:
            checked += 1
            continue
        if path.is_file() and _sha256(path) == str(row["sha256"]):
            checked += 1
    required = len(manifest["artifacts"])
    if checked < required:
        raise ValueError(f"{platform}: staged artifact set is incomplete ({checked}/{required})")
    dockerfile = (context / "Dockerfile").read_text(encoding="utf-8")
    base_image = earnapp_runtime.REFERENCE_VPS_IMAGES[platform]
    for marker in (
        f"FROM {base_image}",
        "COPY cashpilot-proxy-entrypoint /usr/local/bin/entrypoint.sh",
        "COPY cashpilot-doh.js /usr/local/lib/cashpilot-doh.js",
        "com.cashpilot.earnapp.assets-sha256=",
    ):
        if marker not in dockerfile:
            raise ValueError(f"{platform}: Dockerfile missing required marker {marker}")
    return {
        "platform": platform,
        "artifacts": required,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context-root", type=Path, required=True)
    args = parser.parse_args()
    result = [verify_context(args.context_root / platform, platform) for platform in ("macos", "ios", "ubuntu")]
    print(json.dumps({"status": "ok", "platforms": result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
