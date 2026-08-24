from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_publisher_service_and_timer_are_crash_safe_and_daily():
    service = (ROOT / "scripts" / "cashpilot-nkn-chaindb-publisher.service").read_text(encoding="utf-8")
    failure_service = (ROOT / "scripts" / "cashpilot-nkn-chaindb-publisher-failure.service").read_text(encoding="utf-8")
    timer = (ROOT / "scripts" / "cashpilot-nkn-chaindb-publisher.timer").read_text(encoding="utf-8")
    assert "flock" in service
    assert "Type=simple" in service
    assert "Type=oneshot" not in service
    assert "Restart=on-failure" in service
    assert "OnFailure=cashpilot-nkn-chaindb-publisher-failure.service" in service
    assert "/usr/bin/logger" in failure_service
    assert "publisher.json" not in failure_service
    assert "ExecStopPost=-/usr/bin/docker start cashpilot-nkn" in service
    assert "NoNewPrivileges=true" in service
    assert "OnCalendar=daily" in timer
    assert "Persistent=true" in timer


def test_publisher_installer_keeps_secrets_out_of_argv_and_preserves_existing_wallet():
    text = (ROOT / "scripts" / "install-nkn-chaindb-publisher.sh").read_text(encoding="utf-8")
    assert "cmp -s" in text
    assert "wallet.json differs" in text
    assert "chmod 0600" in text
    assert "AWS_SECRET_ACCESS_KEY=" not in text
    assert "systemctl enable --now cashpilot-nkn-chaindb-publisher.timer" in text
    assert "ufw allow 30000:30005/tcp" in text
    assert "ufw allow 30000:30005/udp" in text
    assert 'SSH_PORT="$(python3' in text
    assert 'ufw allow "${SSH_PORT}/tcp"' in text
    assert "LimitNOFILE=1048576" in text
    assert "docker start cashpilot-nkn >/dev/null || true" not in text
    assert "cashpilot-nkn-chaindb-publisher-failure.service" in text


def test_worker_bootstrap_installs_snapshot_dependencies_without_credentials():
    text = (ROOT / "scripts" / "bootstrap-worker.sh").read_text(encoding="utf-8")
    assert "nkn_chaindb_restore.py" in text
    assert "nkn_chaindb.py" in text
    assert "nkn_chaindb_cache.py" in text
    assert "secret_access_key" not in text


def test_lxd_inner_runtime_installs_zstd_before_snapshot_restore():
    text = (ROOT / "scripts" / "cashpilot-nkn-agent.py").read_text(encoding="utf-8")
    assert "apt-get install -y zstd" in text
    assert 'NKN_SNAPSHOT_CACHE_DEVICE = "nkn-chaindb-cache"' in text
    assert '"readonly=true"' in text


def test_standalone_publisher_assets_support_ubuntu_2204_python310():
    """The publisher installer targets Ubuntu 22.04, whose system Python is 3.10."""
    installed_assets = [
        ROOT / "app" / "nkn_chaindb.py",
        ROOT / "scripts" / "nkn_chaindb_publisher.py",
    ]
    for path in installed_assets:
        text = path.read_text(encoding="utf-8")
        assert "from datetime import UTC" not in text, f"{path.name} requires Python 3.11+"
