from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "tools" / "verify-runtime-manifest.py"


def _verifier_module():
    spec = importlib.util.spec_from_file_location("runtime_manifest_verifier", VERIFY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest(path: str, digest: str) -> dict:
    return {
        "schema_version": 1,
        "release": "v2.0.0",
        "rollback_release": "v1.9.0",
        "artifacts": [
            {
                "name": "cashpilot-worker",
                "provider": "cashpilot",
                "architecture": "linux/amd64",
                "source": "ghcr",
                "reference": "ghcr.io/assetforgeai-tech/cashpilot-worker@sha256:" + "a" * 64,
                "asset_url": "https://github.com/assetforgeai-tech/CashPilot/releases/download/v2.0.0/worker.tar",
                "path": path,
                "sha256": digest,
            }
        ],
    }


def test_manifest_verifies_sha256_and_writes_active_pointer(tmp_path: Path):
    artifact = tmp_path / "worker.tar"
    artifact.write_bytes(b"runtime")
    digest = hashlib.sha256(b"runtime").hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(_manifest(artifact.name, digest)), encoding="utf-8")
    state = tmp_path / "active.json"

    result = subprocess.run(
        [
            sys.executable,
            str(VERIFY),
            "--manifest",
            str(manifest),
            "--artifact-dir",
            str(tmp_path),
            "--state",
            str(state),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(state.read_text(encoding="utf-8"))["release"] == "v2.0.0"


def test_failed_verification_preserves_previous_active_pointer(tmp_path: Path):
    artifact = tmp_path / "worker.tar"
    artifact.write_bytes(b"tampered")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(_manifest(artifact.name, "0" * 64)), encoding="utf-8")
    state = tmp_path / "active.json"
    state.write_text(json.dumps({"release": "v1.9.0"}), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(VERIFY),
            "--manifest",
            str(manifest),
            "--artifact-dir",
            str(tmp_path),
            "--state",
            str(state),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert json.loads(state.read_text(encoding="utf-8")) == {"release": "v1.9.0"}


def test_schema_rejects_secrets_and_mutable_image_reference():
    schema = json.loads((ROOT / "release" / "runtime-manifest.schema.json").read_text(encoding="utf-8"))
    assert "password" not in json.dumps(schema).lower()
    assert "latest" not in json.dumps(schema).lower()


def test_verifier_rejects_mutable_image_reference(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    payload = _manifest("worker.tar", "0" * 64)
    payload["artifacts"][0]["reference"] = "ghcr.io/assetforgeai-tech/cashpilot-worker:latest"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    state = tmp_path / "active.json"
    result = subprocess.run(
        [
            sys.executable,
            str(VERIFY),
            "--manifest",
            str(manifest),
            "--artifact-dir",
            str(tmp_path),
            "--state",
            str(state),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert not state.exists()


def test_ghcr_artifact_is_pulled_by_digest_before_activation(monkeypatch):
    verifier = _verifier_module()
    calls = []
    monkeypatch.setattr(verifier.subprocess, "run", lambda command, check: calls.append((command, check)))
    reference = "ghcr.io/assetforgeai-tech/cashpilot-worker@sha256:" + "a" * 64

    verifier._pull_ghcr(reference)

    assert calls == [(["docker", "pull", reference], True)]


def test_container_image_artifact_uses_reference_digest_without_local_file(tmp_path: Path):
    verifier = _verifier_module()
    digest = "a" * 64
    manifest = {
        "schema_version": 1,
        "release": "v2.0.0",
        "rollback_release": "v1.9.0",
        "artifacts": [
            {
                "name": "sing-box",
                "provider": "sagernet",
                "architecture": "linux/amd64",
                "source": "ghcr",
                "kind": "container-image",
                "reference": f"ghcr.io/sagernet/sing-box@sha256:{digest}",
                "path": "sing-box",
                "sha256": digest,
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    state = tmp_path / "active.json"

    verifier.verify(manifest_path, tmp_path, state, None)

    active = json.loads(state.read_text(encoding="utf-8"))
    assert active["artifacts"] == [
        {
            "name": "sing-box",
            "kind": "container-image",
            "reference": f"ghcr.io/sagernet/sing-box@sha256:{digest}",
            "sha256": digest,
        }
    ]


def test_container_image_artifact_rejects_reference_digest_mismatch(tmp_path: Path):
    verifier = _verifier_module()
    manifest = _manifest("worker.tar", "b" * 64)
    manifest["artifacts"][0]["kind"] = "container-image"
    manifest["artifacts"][0]["reference"] = "ghcr.io/assetforgeai-tech/cashpilot-worker@sha256:" + "a" * 64
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match sha256"):
        verifier.verify(manifest_path, tmp_path, tmp_path / "active.json", None)
