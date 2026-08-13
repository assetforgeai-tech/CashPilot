from pathlib import Path

import scripts.check_deploy_baseline as guard


def test_deploy_baseline_records_approved_ui_sha():
    assert guard.BASELINE_FILE == Path(__file__).resolve().parents[1] / "DEPLOY_BASELINE.json"
    assert "40834f6" in guard.BASELINE_FILE.read_text(encoding="utf-8")
