from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PS = ROOT / "azure_create" / "create-worker.ps1"
SH = ROOT / "azure_create" / "create-worker.sh"


def test_cli_generators_exist_and_expose_safe_inputs():
    ps = PS.read_text(encoding="utf-8")
    sh = SH.read_text(encoding="utf-8")

    for value in ("SubscriptionId", "Region", "VmSize", "Image", "OsDiskSizeGb", "PublicIpCount", "DryRun"):
        assert value in ps
    assert "--subscription" in sh
    assert "--location" in sh
    assert "--size" in sh
    assert "--image" in sh
    assert "--public-ip-addresses" in sh
    assert "--dry-run" in sh
    assert "admin-password" in ps.lower()
    assert "ssh" in ps.lower()


def test_generators_reject_secret_values_and_full_protocol_without_approval():
    ps = PS.read_text(encoding="utf-8")
    sh = SH.read_text(encoding="utf-8")

    assert "CASHPILOT_API_KEY" not in ps
    assert "password" in sh.lower()
    assert "FULL_TCP_UDP_APPROVED" in sh
