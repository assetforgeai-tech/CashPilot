from pathlib import Path

import pytest

from scripts import build_earnapp_canary_image, verify_earnapp_runtime_fidelity


@pytest.mark.parametrize("platform", ["macos", "ios", "ubuntu"])
def test_staged_runtime_matches_authoritative_platform_contract(tmp_path: Path, platform: str):
    context = tmp_path / platform
    build_earnapp_canary_image.write_context(
        build_earnapp_canary_image.default_source_dir(platform),
        context,
        platform=platform,
    )

    result = verify_earnapp_runtime_fidelity.verify_context(context, platform)

    assert result["platform"] == platform
    assert result["artifacts"] > 0


def test_fidelity_verifier_rejects_modified_runtime_artifact(tmp_path: Path):
    context = tmp_path / "macos"
    build_earnapp_canary_image.write_context(
        build_earnapp_canary_image.default_source_dir("macos"),
        context,
        platform="macos",
    )
    (context / "boot.js").write_text("modified", encoding="utf-8")

    with pytest.raises(ValueError, match="incomplete"):
        verify_earnapp_runtime_fidelity.verify_context(context, "macos")


def test_image_builder_runs_fidelity_gate(tmp_path: Path, monkeypatch):
    verified = []
    monkeypatch.setattr(
        verify_earnapp_runtime_fidelity,
        "verify_context",
        lambda context, platform: verified.append((context, platform)),
    )

    context = tmp_path / "ubuntu"
    build_earnapp_canary_image.write_context(
        build_earnapp_canary_image.default_source_dir("ubuntu"),
        context,
        platform="ubuntu",
    )

    assert verified == [(context, "ubuntu")]
