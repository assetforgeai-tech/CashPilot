from pathlib import Path

import scripts.check_deploy_baseline as guard


def test_deploy_baseline_records_approved_ui_sha():
    assert Path(__file__).resolve().parents[1] / "DEPLOY_BASELINE.json" == guard.BASELINE_FILE
    assert "40834f6" in guard.BASELINE_FILE.read_text(encoding="utf-8")
