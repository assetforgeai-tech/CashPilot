"""Build the immutable runtime manifest used by the release workflow."""

from __future__ import annotations

import argparse
import json
import re
import sys

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def _version(tag: str) -> tuple[int, int, int]:
    match = _TAG.fullmatch(tag)
    if not match:
        raise ValueError(f"invalid release tag: {tag}")
    return tuple(int(part) for part in match.groups())


def build_manifest(
    release: str,
    owner: str,
    ui_digest: str,
    worker_digest: str,
    tags: list[str],
) -> dict[str, object]:
    _version(release)
    for name, digest in (("UI", ui_digest), ("worker", worker_digest)):
        if not _DIGEST.fullmatch(digest):
            raise ValueError(f"invalid {name} image digest")
    previous = [tag for tag in tags if tag != release and _TAG.fullmatch(tag)]
    if not previous:
        raise ValueError("no previous release tag available for rollback")
    rollback = max(previous, key=_version)

    def artifact(name: str, digest: str) -> dict[str, str]:
        digest_value = digest.split(":", 1)[1]
        return {
            "name": name,
            "provider": "cashpilot",
            "architecture": "linux/amd64",
            "source": "ghcr",
            "reference": f"ghcr.io/{owner}/{name}@{digest}",
            "path": name,
            "sha256": digest_value,
        }

    return {
        "schema_version": 1,
        "release": release,
        "rollback_release": rollback,
        "artifacts": [
            artifact("cashpilot", ui_digest),
            artifact("cashpilot-worker", worker_digest),
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--ui-digest", required=True)
    parser.add_argument("--worker-digest", required=True)
    parser.add_argument("--tags", nargs="*", default=[])
    args = parser.parse_args()
    try:
        manifest = build_manifest(
            args.release,
            args.owner,
            args.ui_digest,
            args.worker_digest,
            args.tags,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    json.dump(manifest, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
