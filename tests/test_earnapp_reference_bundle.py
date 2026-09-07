from pathlib import Path

from scripts.verify_earnapp_reference_bundle import build_manifest


def test_reference_manifest_is_deterministic_and_excludes_credentials(tmp_path: Path):
    (tmp_path / "runtime" / "mac").mkdir(parents=True)
    (tmp_path / "runtime" / "mac" / "entrypoint.sh").write_text("runtime", encoding="utf-8")
    (tmp_path / "vps.txt").write_text("secret", encoding="utf-8")

    manifest = build_manifest(tmp_path)
    assert manifest["schema"] == 1
    assert [item["path"] for item in manifest["artifacts"]] == ["runtime/mac/entrypoint.sh"]
    assert all("vps.txt" not in item["path"] for item in manifest["artifacts"])
