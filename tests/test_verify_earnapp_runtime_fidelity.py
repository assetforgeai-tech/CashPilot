import hashlib
import json
from pathlib import Path

import pytest

from scripts import verify_earnapp_runtime_fidelity


def _context(tmp_path: Path, platform: str = "ubuntu") -> Path:
    context = tmp_path / platform
    context.mkdir()
    payload = b"artifact"
    digest = hashlib.sha256(payload).hexdigest()
    manifest = {"version": 1, "artifacts": [{"path": "entrypoint.sh", "sha256": digest}]}
    if platform == "ubuntu":
        manifest["base_image"] = "reference"
    (context / "entrypoint.sh").write_bytes(payload)
    (context / "runtime-manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    (context / "Dockerfile").write_text(
        "FROM reference\nCOPY cashpilot-proxy-entrypoint /usr/local/bin/entrypoint.sh\n"
        "COPY cashpilot-doh.js /usr/local/lib/cashpilot-doh.js\n"
        "LABEL com.cashpilot.earnapp.assets-sha256=x\n",
        encoding="utf-8",
    )
    return context


def test_fidelity_verifier_accepts_complete_context(tmp_path: Path, monkeypatch):
    monkeypatch.setitem(verify_earnapp_runtime_fidelity.earnapp_runtime.REFERENCE_VPS_IMAGES, "ubuntu", "reference")
    result = verify_earnapp_runtime_fidelity.verify_context(_context(tmp_path), "ubuntu")
    assert result["platform"] == "ubuntu"
    assert result["artifacts"] == 1


def test_fidelity_verifier_rejects_modified_runtime_artifact(tmp_path: Path, monkeypatch):
    monkeypatch.setitem(verify_earnapp_runtime_fidelity.earnapp_runtime.REFERENCE_VPS_IMAGES, "ubuntu", "reference")
    context = _context(tmp_path)
    (context / "entrypoint.sh").write_text("modified", encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete"):
        verify_earnapp_runtime_fidelity.verify_context(context, "ubuntu")
