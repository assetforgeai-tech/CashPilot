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


def test_bootstrap_does_not_install_docker_io_over_an_existing_docker_engine():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "if ! command -v docker >/dev/null 2>&1; then" in text
    assert 'packages=(docker.io "${packages[@]}")' in text
    assert 'apt-get install -y "${packages[@]}"' in text
    assert "apt-get install -y docker.io ufw" not in text


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


def test_bootstrap_installs_the_restricted_nkn_lxd_host_helper_without_deploying_a_node():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "cashpilot-nkn-agent.py" in text
    assert "cashpilot-nkn-agent.service" in text
    assert "/run/cashpilot-nkn-agent/agent.sock" in text
    assert "lxd init --auto" in text
    assert "systemctl enable --now cashpilot-nkn-agent.service" in text
    assert "lxc launch" not in text
    assert "nknorg/nkn" not in text


def test_bootstrap_uses_supported_lxc_storage_list_syntax():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "lxc storage list --format csv -c n" not in text
    assert "lxc storage list --format csv" in text


def test_bootstrap_installs_the_nkn_snapshot_cache_without_credentials():
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'NKN_CHAINDb_CACHE="${INSTALL_ROOT}/nkn_chaindb_cache.py"' in text
    assert 'NKN_HELPER_INSTALLER="${REPO_ROOT}/scripts/install-nkn-host-helper.sh"' in text
    assert '"${NKN_HELPER_INSTALLER}" "${REPO_ROOT}"' in text
    assert "X-Amz-Signature" not in text
    assert "secret_access_key" not in text


def test_worker_compose_mounts_only_the_restricted_nkn_agent_socket():
    root = SCRIPT.parents[1]
    for name in ("docker-compose.yml", "docker-compose.fleet.yml", "docker-compose.build.yml"):
        text = (root / name).read_text(encoding="utf-8")
        assert "/run/cashpilot-nkn-agent:/run/cashpilot-nkn-agent" in text
        assert "/var/snap/lxd/common/lxd/unix.socket" not in text
