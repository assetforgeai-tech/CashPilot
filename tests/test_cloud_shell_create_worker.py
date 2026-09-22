from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "azure_create" / "cloud-shell-create-worker.sh"


def test_script_is_self_contained_and_uses_target_defaults():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "Standard_D8s_v4" in text
    assert "Ubuntu2404" in text
    assert 'OS_DISK_SIZE_GB="${OS_DISK_SIZE_GB:-512}"' in text
    assert 'LOCATION="${LOCATION:-eastasia}"' in text
    assert 'IPV4_COUNT="${IPV4_COUNT:-20}"' in text
    assert "cat <<EOF" in text
    assert '--custom-data "$custom_data_file"' in text
    assert "CASHPILOT_API_KEY" in text
    assert "CASHPILOT_WORKER_URL" in text
    assert "base64 -d" in text
    assert "docker login ghcr.io" in text


def test_port_matrix_is_narrow_and_worker_ports_are_not_public():
    text = SCRIPT.read_text(encoding="utf-8")
    for port in ("4449", "30000-30005", "56000-56100"):
        assert port in text
    assert "8081" not in text
    assert "6080" not in text
    assert "1-65535" not in text


def test_script_has_dry_run_preinventory_idempotent_and_no_local_reads():
    text = SCRIPT.read_text(encoding="utf-8")
    for flag in ("--dry-run", "PREINVENTORY", "IDEMPOTENT", "az group show"):
        assert flag in text
    assert "worker-startup.sh" not in text
    assert "Test-Path" not in text
    assert "ssh-key-values" in text
    assert "admin-password" not in text
