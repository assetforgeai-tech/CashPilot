import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "create_release_runtime_manifest.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def test_manifest_uses_previous_release_and_excludes_current_tag():
    result = _run(
        "--release",
        "v1.61.0",
        "--owner",
        "assetforgeai-tech",
        "--ui-digest",
        "sha256:" + "1" * 64,
        "--worker-digest",
        "sha256:" + "2" * 64,
        "--tags",
        "v1.61.0",
        "v1.60.0",
        "v1.9.0",
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads(result.stdout)
    assert manifest["release"] == "v1.61.0"
    assert manifest["rollback_release"] == "v1.60.0"


def test_manifest_fails_when_no_previous_release_exists():
    result = _run(
        "--release",
        "v1.61.0",
        "--owner",
        "assetforgeai-tech",
        "--ui-digest",
        "sha256:" + "1" * 64,
        "--worker-digest",
        "sha256:" + "2" * 64,
        "--tags",
        "v1.61.0",
    )

    assert result.returncode != 0
    assert "previous release tag" in result.stderr


def test_manifest_rejects_missing_or_invalid_digest():
    result = _run(
        "--release",
        "v1.61.0",
        "--owner",
        "assetforgeai-tech",
        "--ui-digest",
        "",
        "--worker-digest",
        "not-a-digest",
        "--tags",
        "v1.60.0",
    )

    assert result.returncode != 0
    assert "digest" in result.stderr


def test_publish_fetches_fork_tags_before_manifest_generation():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    publish = workflow[workflow.index("  publish:") :]
    fetch = "git fetch --force origin 'refs/tags/*:refs/fork-tags/*'"
    assert fetch in publish
    assert publish.index(fetch) < publish.index("Attach immutable runtime manifest")
    assert "create_release_runtime_manifest.py" in publish


def test_release_serializes_main_publication_to_avoid_duplicate_versions():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "group: cashpilot-release-main" in workflow
    assert "cancel-in-progress: false" in workflow
