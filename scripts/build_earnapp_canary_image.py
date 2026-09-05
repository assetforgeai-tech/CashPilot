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

_ENTRYPOINT_INSTALL_MARKERS = {
    "macos": '[[ ! -f "$STATE_DIR/uuid" || ! -x /usr/bin/earnapp ]]',
    "ios": '[[ ! -f "$STATE_DIR/uuid" || ! -x /usr/bin/earnapp ]]',
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_artifacts(
    source_dir: str | Path,
    expected_hashes: Mapping[str, str] | None = None,
    *,
    platform: str = "macos",
) -> dict:
    source = Path(source_dir)
    selected = str(platform or "macos").strip().lower()
    defaults = {
        "macos": earnapp_runtime.MAC_RUNTIME_ARTIFACT_HASHES,
        "ios": earnapp_runtime.IOS_RUNTIME_ARTIFACT_HASHES,
        "ubuntu": earnapp_runtime.UBUNTU_RUNTIME_ARTIFACT_HASHES,
    }
    if selected not in defaults:
        raise ValueError("unsupported EarnApp image platform")
    expected = dict(expected_hashes or defaults[selected])
    for name, expected_hash in expected.items():
        path = source / name
        if not path.is_file():
            raise FileNotFoundError(f"missing EarnApp runtime artifact: {path}")
        actual = _sha256(path)
        if actual.lower() != str(expected_hash).lower():
            raise ValueError(f"EarnApp runtime artifact hash mismatch for {name}")
    if selected in _ENTRYPOINT_INSTALL_MARKERS:
        entrypoint = (source / "entrypoint.sh").read_text(encoding="utf-8")
        if _ENTRYPOINT_INSTALL_MARKERS[selected] not in entrypoint:
            raise ValueError(f"EarnApp {selected} entrypoint install marker is invalid")
    return earnapp_runtime.runtime_asset_manifest(expected, platform=selected)


def render_ios_registration_wrapper() -> str:
    """Render the iOS registration script from the same source as the digest."""
    return earnapp_runtime.ios_registration_script().decode("utf-8")


def render_dockerfile(manifest: Mapping[str, object], *, platform: str = "macos") -> str:
    selected = str(platform or "macos").strip().lower()
    if selected not in {"macos", "ios", "ubuntu"}:
        raise ValueError("unsupported EarnApp image platform")
    manifest_hash = hashlib.sha256(_manifest_bytes(manifest)).hexdigest()
    if selected == "ubuntu":
        return f"""FROM {earnapp_runtime.UBUNTU_REFERENCE_IMAGE_PIN}

RUN mv /usr/local/bin/entrypoint.sh /usr/local/bin/entrypoint-original.sh
COPY cashpilot-proxy-entrypoint /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh /usr/local/bin/entrypoint-original.sh

LABEL com.cashpilot.earnapp.runtime={earnapp_runtime.UBUNTU_RUNTIME_HOST} \\
      com.cashpilot.earnapp.platform={earnapp_runtime.UBUNTU_PLATFORM} \\
      com.cashpilot.earnapp.appid={earnapp_runtime.UBUNTU_APPID} \\
      com.cashpilot.earnapp.device-prefix={earnapp_runtime.UBUNTU_DEVICE_PREFIX} \\
      com.cashpilot.earnapp.assets-sha256={manifest_hash}

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
"""
    if selected == "ios":
        binary_source = "earnapp-bootstrap"
        binary_target = "earnapp-ios"
        runtime = earnapp_runtime.IOS_RUNTIME_HOST
        wire_platform = earnapp_runtime.IOS_PLATFORM
        appid = earnapp_runtime.IOS_APPID
        device_prefix = earnapp_runtime.IOS_DEVICE_PREFIX
        registration_copy = (
            "COPY entrypoint.sh /usr/local/bin/entrypoint-original.sh\n"
            "COPY ios-entrypoint /usr/local/bin/ios-entrypoint\n"
            "COPY ios-register-device /usr/local/bin/ios-register-device\n"
            "COPY cashpilot-proxy-entrypoint /usr/local/bin/entrypoint.sh\n"
        )
        registration_mode = " /usr/local/bin/ios-entrypoint /usr/local/bin/ios-register-device"
        entrypoint_copy = ""
        shellcheck = " /usr/local/bin/entrypoint-original.sh /usr/local/bin/ios-register-device"
    else:
        binary_source = "earnapp-mac"
        binary_target = "earnapp-mac"
        runtime = earnapp_runtime.MAC_RUNTIME_HOST
        wire_platform = earnapp_runtime.MAC_PLATFORM
        appid = earnapp_runtime.MAC_APPID
        device_prefix = earnapp_runtime.MAC_DEVICE_PREFIX
        registration_copy = ""
        registration_mode = ""
        entrypoint_copy = (
            "COPY entrypoint.sh /usr/local/bin/entrypoint-original.sh\n"
            "COPY cashpilot-proxy-entrypoint /usr/local/bin/entrypoint.sh\n"
        )
        shellcheck = ""
    return f"""FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \\
    EARNAPP_WATCHDOG=1 \\
    NODE_TLS_REJECT_UNAUTHORIZED=0

RUN apt-get update \\
    && apt-get install -y --no-install-recommends ca-certificates curl dbus iproute2 iptables nodejs procps redsocks \\
    && rm -rf /var/lib/apt/lists/*

COPY {binary_source} /opt/{binary_target}
COPY boot.js /usr/local/lib/node/boot.js
COPY earn-supervisor /usr/local/bin/earn-supervisor
{entrypoint_copy}{registration_copy}COPY runtime-manifest.json /opt/cashpilot/runtime-manifest.json

RUN chmod 0755 /opt/{binary_target} /usr/local/bin/earn-supervisor /usr/local/bin/entrypoint.sh /usr/local/bin/entrypoint-original.sh{registration_mode} \\
    && node --check /usr/local/lib/node/boot.js \\
    && bash -n /usr/local/bin/earn-supervisor /usr/local/bin/entrypoint.sh{shellcheck}

LABEL com.cashpilot.earnapp.runtime={runtime} \\
      com.cashpilot.earnapp.platform={wire_platform} \\
      com.cashpilot.earnapp.appid={appid} \\
      com.cashpilot.earnapp.device-prefix={device_prefix} \\
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


def _manifest_bytes(manifest: Mapping[str, object]) -> bytes:
    payload = json.dumps(dict(manifest), sort_keys=True, separators=(",", ":"))
    return (payload + "\n").encode("utf-8")


def write_context(
    source_dir: str | Path,
    context_dir: str | Path,
    *,
    platform: str = "macos",
) -> tuple[Path, str]:
    source = Path(source_dir)
    context = Path(context_dir)
    if context.exists() and any(context.iterdir()):
        raise FileExistsError(f"build context must be empty: {context}")
    context.mkdir(parents=True, exist_ok=True)
    selected = str(platform or "macos").strip().lower()
    manifest = validate_artifacts(source, platform=selected)
    generated_names = set(earnapp_runtime.generated_runtime_artifacts(selected))
    for row in manifest["artifacts"]:
        name = str(row["path"])
        if name not in generated_names:
            shutil.copy2(source / name, context / name)
    manifest_bytes = _manifest_bytes(manifest)
    (context / "runtime-manifest.json").write_bytes(manifest_bytes)
    for name, payload in earnapp_runtime.generated_runtime_artifacts(selected).items():
        (context / name).write_bytes(payload)
    (context / "Dockerfile").write_text(render_dockerfile(manifest, platform=selected), encoding="utf-8")
    return context, hashlib.sha256(manifest_bytes).hexdigest()


def image_reference(manifest_hash: str, *, platform: str = "macos") -> str:
    selected = str(platform or "macos").strip().lower()
    repository = {
        "ios": "cashpilot/earnapp-ios",
        "ubuntu": "cashpilot/earnapp-ubuntu",
    }.get(selected, "cashpilot/earnapp-mac-canary")
    return f"{repository}:asset-{str(manifest_hash)[:12]}"


def default_source_dir(platform: str = "macos") -> Path:
    """Return the external operator-supplied runtime bundle path."""
    selected = str(platform or "macos").strip().lower()
    external_root = ROOT.parents[1] / "earnapp_new_update"
    if selected == "ubuntu":
        return ROOT / ".runtime-src" / "ubuntu"
    bundle = "ios" if selected == "ios" else "mac-1.660.577"
    return external_root / "earnapp-runtime-files" / bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=None)
    parser.add_argument("--context-dir", type=Path, default=None)
    parser.add_argument("--platform", choices=("macos", "ios", "ubuntu"), default="macos")
    parser.add_argument("--build", action="store_true", help="run docker build after staging")
    args = parser.parse_args()

    source = args.source_dir or default_source_dir(args.platform)
    context = args.context_dir or (Path.cwd() / f".tmp-earnapp-{args.platform}-context")
    if context.exists() and any(context.iterdir()):
        raise SystemExit(f"refusing non-empty context directory: {context}")
    _, digest = write_context(source, context, platform=args.platform)
    tag = image_reference(digest, platform=args.platform)
    print(json.dumps({"manifest_sha256": digest, "image": tag, "context": str(context)}, sort_keys=True))
    if args.build:
        subprocess.run(["docker", "build", "--tag", tag, str(context)], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
