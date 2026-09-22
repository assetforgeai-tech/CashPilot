import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location("resolve_release_digest", ROOT / "scripts/resolve_release_digest.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_digest_retries_transient_not_found_then_succeeds():
    module = _module()
    responses = iter([RuntimeError("not found"), RuntimeError("not found"), '"sha256:' + "a" * 64 + '"'])
    sleeps = []

    def inspect(_image):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    assert (
        module.resolve_digest(
            "ghcr.io/example/app:v1", attempts=6, delay_seconds=0, inspect=inspect, sleep=sleeps.append
        )
        == "sha256:" + "a" * 64
    )
    assert len(sleeps) == 2


def test_digest_fails_closed_after_bounded_not_found_retries():
    module = _module()
    with pytest.raises(RuntimeError, match="after 3 attempts"):
        module.resolve_digest(
            "ghcr.io/example/app:v1",
            attempts=3,
            delay_seconds=0,
            inspect=lambda _image: (_ for _ in ()).throw(RuntimeError("not found")),
            sleep=lambda _delay: None,
        )


def test_release_workflow_uses_bounded_digest_resolver():
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "resolve_release_digest.py" in workflow
    assert "--attempts 6" in workflow


def test_publish_authenticates_before_reading_private_ghcr_images():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    publish = workflow[workflow.index("  publish:") :]
    manifest = publish.index("Attach immutable runtime manifest")
    assert "packages: read" in publish[:manifest]
    assert "docker/login-action@" in publish[:manifest]
    assert "registry: ghcr.io" in publish[:manifest]


def test_release_workflow_has_explicit_existing_release_recovery_path():
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "recover_version" in workflow
    assert "Repair existing release manifest" in workflow
    assert 'gh release upload "$VERSION" runtime-manifest.json --clobber' in workflow
    assert workflow.count('image_version="${VERSION#v}"') == 2
    assert workflow.count('cashpilot:${image_version}') == 4
