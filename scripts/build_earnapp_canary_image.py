#!/usr/bin/env python3
"""Build the pinned EarnApp Mac canary image from an external asset bundle.

The runtime binaries are intentionally kept outside the repository.  This
helper validates their hashes, writes a canonical manifest, and only then
builds an image whose labels are checked by the worker at deployment time.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

# ``python scripts/<file>.py`` puts only ``scripts/`` on sys.path.  Add the
# repository root so the helper is usable both as a module and as a CLI.
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


def validate_artifacts(source_dir: str | Path, expected_hashes: Mapping[str, str] | None = None) -> dict:
    source = Path(source_dir)
    expected = dict(expected_hashes or earnapp_runtime.MAC_RUNTIME_ARTIFACT_HASHES)
    for name, expected_hash in expected.items():
        path = source / name
        if not path.is_file():
            raise FileNotFoundError(f"missing EarnApp runtime artifact: {path}")
        actual = _sha256(path)
        if actual.lower() != str(expected_hash).lower():
            raise ValueError(f"EarnApp runtime artifact hash mismatch for {name}")
    return earnapp_runtime.runtime_asset_manifest(expected)


def render_dockerfile(manifest: Mapping[str, object]) -> str:
    manifest_hash = earnapp_runtime.runtime_asset_manifest_sha256(manifest_hashes(manifest))
    return f"""FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \\
    EARNAPP_WATCHDOG=1 \\
    NODE_TLS_REJECT_UNAUTHORIZED=0

RUN apt-get update \\
    && apt-get install -y --no-install-recommends ca-certificates curl dbus iproute2 iptables nodejs procps redsocks \\
    && rm -rf /var/lib/apt/lists/*

COPY earnapp-mac /opt/earnapp-mac
COPY boot.js /usr/local/lib/node/boot.js
COPY earn-supervisor /usr/local/bin/earn-supervisor
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY runtime-manifest.json /opt/cashpilot/runtime-manifest.json

RUN chmod 0755 /opt/earnapp-mac /usr/local/bin/earn-supervisor /usr/local/bin/entrypoint.sh \\
    && node --check /usr/local/lib/node/boot.js \\
    && bash -n /usr/local/bin/earn-supervisor /usr/local/bin/entrypoint.sh

LABEL com.cashpilot.earnapp.runtime=earnapp_mac_canary \\
      com.cashpilot.earnapp.platform=darwin \\
      com.cashpilot.earnapp.appid=mac_com.earnapp \\
      com.cashpilot.earnapp.device-prefix=sdk-mac- \\
      com.cashpilot.earnapp.assets-sha256={manifest_hash}

VOLUME ["/etc/earnapp"]
ENTRYPOINT ["/usr/local/bin/earn-supervisor"]
"""


def manifest_hashes(manifest: Mapping[str, object]) -> dict[str, str]:
    rows = manifest.get("artifacts") if isinstance(manifest, Mapping) else None
    if not isinstance(rows, list):
        raise ValueError("runtime manifest artifacts are missing")
    result: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("runtime manifest artifact is invalid")
        result[str(row["path"])] = str(row["sha256"])
    return result


def write_context(source_dir: str | Path, context_dir: str | Path) -> tuple[Path, str]:
    source = Path(source_dir)
    context = Path(context_dir)
    if context.exists() and any(context.iterdir()):
        raise FileExistsError(f"build context must be empty: {context}")
    context.mkdir(parents=True, exist_ok=True)
    manifest = validate_artifacts(source)
    for row in manifest["artifacts"]:
        name = str(row["path"])
        shutil.copy2(source / name, context / name)
    manifest_bytes = earnapp_runtime.runtime_asset_manifest_bytes(manifest_hashes(manifest))
    (context / "runtime-manifest.json").write_bytes(manifest_bytes)
    (context / "Dockerfile").write_text(render_dockerfile(manifest), encoding="utf-8")
    return context, earnapp_runtime.runtime_asset_manifest_sha256(manifest_hashes(manifest))


def image_reference(manifest_hash: str) -> str:
    return f"cashpilot/earnapp-mac-canary:asset-{str(manifest_hash)[:12]}"


def default_source_dir() -> Path:
    """Return the external, operator-supplied Mac runtime bundle path."""
    return ROOT.parent / "earnapp_new_update" / "earnapp-runtime-files" / "mac"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=None)
    parser.add_argument("--context-dir", type=Path, default=None)
    parser.add_argument("--build", action="store_true", help="run docker build after staging")
    args = parser.parse_args()

    source = args.source_dir or default_source_dir()
    context = args.context_dir or (Path.cwd() / ".tmp-earnapp-mac-canary-context")
    if context.exists() and any(context.iterdir()):
        raise SystemExit(f"refusing non-empty context directory: {context}")
    _, digest = write_context(source, context)
    tag = image_reference(digest)
    print(json.dumps({"manifest_sha256": digest, "image": tag, "context": str(context)}, sort_keys=True))
    if args.build:
        subprocess.run(["docker", "build", "--tag", tag, str(context)], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
