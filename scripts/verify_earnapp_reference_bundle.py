#!/usr/bin/env python3
"""Create a secret-free manifest for the upgraded EarnApp reference bundle.

The manifest proves which exported image/runtime bytes are being cloned. It
does not inspect or copy identities, credentials, volumes, or proxy settings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(root: Path) -> dict[str, object]:
    artifacts = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name not in {"vps.txt"}:
            artifacts.append({"path": path.relative_to(root).as_posix(), "sha256": sha256(path), "size": path.stat().st_size})
    return {"schema": 1, "source": "earnapp_update_05092026", "artifacts": artifacts}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_manifest(args.root)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"artifact_count": len(manifest["artifacts"]), "manifest": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
