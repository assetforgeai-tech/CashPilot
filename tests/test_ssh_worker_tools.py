from pathlib import Path

ROOT = Path(__file__).parents[1]
SSH = ROOT / "tools" / "ssh-worker.ps1"
PREFLIGHT = ROOT / "tools" / "azure-worker-preflight.ps1"


def test_worker_scripts_exist_and_never_embed_credentials():
    ssh = SSH.read_text(encoding="utf-8")
    preflight = PREFLIGHT.read_text(encoding="utf-8")

    assert "param(" in ssh and "param(" in preflight
    assert "BatchMode=yes" in ssh
    assert '"vm", "show"' in preflight
    assert "publicIpAddress" in preflight
    assert "Test-NetConnection" in preflight
    assert "IdentityFile" not in ssh
    assert "password" not in ssh.lower()
    assert "password" not in preflight.lower()


def test_scripts_fail_before_ssh_when_preflight_is_not_healthy():
    ssh = SSH.read_text(encoding="utf-8")
    preflight = PREFLIGHT.read_text(encoding="utf-8")

    assert "azure-worker-preflight.ps1" in ssh
    assert "PowerState/running" in preflight
    assert "throw" in preflight
    assert "ConnectTimeout" in ssh


def test_ssh_wrapper_passes_only_inventory_key_path_to_ssh():
    ssh = SSH.read_text(encoding="utf-8")

    assert "KeyPath" in ssh
    assert "-i" in ssh
    assert "Resolve-Path" in ssh
    assert "Get-Content" not in ssh
