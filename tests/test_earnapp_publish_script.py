from pathlib import Path


def test_publish_script_normalizes_uploaded_shell_script_line_endings():
    script = Path("scripts/publish_generic_earnapp.ps1").read_text(encoding="utf-8")
    assert '$remoteScript = $remoteScript -replace "`r`n", "`n"' in script
