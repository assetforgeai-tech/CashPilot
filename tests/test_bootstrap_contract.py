from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bootstrap-worker.sh"


def test_bootstrap_prepares_slots_networking_and_persistent_nofile_without_deploying_providers():
    text = SCRIPT.read_text(encoding="utf-8")

    assert text.startswith("#!/usr/bin/env bash\nset -euo pipefail")
    assert "metadata/instance/network/interface" in text
    assert "public-ip-slots.json" in text
    assert "docker network create" in text
    assert "iptables -t nat" in text
    assert "SNAT --to-source" in text
    assert "30000:30005" in text
    assert "32768:65535" in text
    assert "LimitNOFILE=1048576" in text


def test_bootstrap_does_not_restart_docker_when_it_is_already_running():
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'if [ -z "$(docker ps -q)" ]; then' in text
    assert "systemctl restart docker" in text
    assert "Docker is already running CashPilot workloads; the new nofile limit" in text
    assert "systemctl daemon-reload" in text
    assert "systemctl enable --now docker" in text


def test_bootstrap_disables_docker_masquerade_for_per_slot_snat():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "com.docker.network.bridge.enable_ip_masquerade=false" in text
    assert "actual_masquerade=" in text
    assert 'test "${actual_masquerade}" = "false"' in text
    assert "cashpilot_public_ip_slots" in text
    assert "cashpilot-slots-sync.timer" in text
    assert "public-ip-slots.json" in text
    assert "ulimit -n unlimited" not in text
    assert "docker run" not in text
    assert "nknorg/nkn" not in text
    assert 'DISCOVERY="${INSTALL_ROOT}/public_ip_slots.py"' in text
    assert "LimitNOFILE=1048576" in text


def test_bootstrap_does_not_embed_fleet_or_provider_credentials():
    text = SCRIPT.read_text(encoding="utf-8").lower()
    forbidden = (
        "cashpilot_api_key=",
        "authorization: bearer",
        "wallet.json",
        "wallet.pswd",
        "mmn_api_key",
        "beneficiaryaddr",
    )
    assert not any(token in text for token in forbidden)
