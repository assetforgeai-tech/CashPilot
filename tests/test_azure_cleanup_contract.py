from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "azure-inventory-and-cleanup.sh"
RUNBOOK = ROOT / "docs" / "ops" / "azure-cleanup-runbook.md"


def test_cleanup_script_is_dry_run_and_scope_locked():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "DRY_RUN=true" in text
    assert "CP014J_APPROVED" in text
    assert "cashpilot-cp014j" in text
    assert "cashpilot-live-ea" not in text
    assert "cashpilot-live-je" not in text
    assert "az group delete" not in text
    assert "az resource delete" in text


def test_runbook_requires_fresh_approval_before_mutation():
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "read-only" in text.lower()
    assert "fresh approval" in text.lower()
    assert "zero orphan" in text.lower()
