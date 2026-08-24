from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-nkn-host-helper.sh"
BOOTSTRAP = ROOT / "scripts" / "bootstrap-worker.sh"


def test_host_helper_installer_updates_only_nkn_host_assets():
    text = INSTALLER.read_text(encoding="utf-8")

    assert text.startswith("#!/usr/bin/env bash\nset -euo pipefail")
    for asset in (
        "scripts/cashpilot-nkn-agent.py",
        "app/nkn_chaindb.py",
        "scripts/nkn_chaindb_restore.py",
        "scripts/nkn_chaindb_cache.py",
    ):
        assert asset in text
    assert "install -d -o root -g root -m 0755" in text
    assert '"${CACHE_ROOT}"' in text
    assert "chown root:root" in text
    assert "chmod 0644" in text
    assert "systemctl restart cashpilot-nkn-agent.service" in text
    assert "systemctl is-active --quiet cashpilot-nkn-agent.service" in text

    service = (ROOT / "scripts" / "cashpilot-nkn-agent.service").read_text(encoding="utf-8")
    assert "snap.lxd.daemon.service" in service

    forbidden = (
        "docker restart",
        "docker rm",
        "lxc launch",
        "lxc delete",
        "cashpilot-worker.service",
        "cashpilot-nkn-ipv4-",
    )
    assert not any(token in text for token in forbidden)


def test_full_bootstrap_delegates_host_helper_installation_to_the_tracked_installer():
    text = BOOTSTRAP.read_text(encoding="utf-8")

    assert 'NKN_HELPER_INSTALLER="${REPO_ROOT}/scripts/install-nkn-host-helper.sh"' in text
    assert '"${NKN_HELPER_INSTALLER}" "${REPO_ROOT}"' in text
    assert "cat >/etc/systemd/system/cashpilot-nkn-agent.service" not in text
    assert 'install -m 0755 "${REPO_ROOT}/scripts/cashpilot-nkn-agent.py"' not in text
    assert 'install -m 0644 "${REPO_ROOT}/scripts/nkn_chaindb_cache.py"' not in text


def test_host_helper_installer_never_contains_credentials_or_signed_urls():
    text = INSTALLER.read_text(encoding="utf-8").lower()
    forbidden = (
        "cashpilot_api_key",
        "authorization: bearer",
        "wallet.json",
        "wallet.pswd",
        "x-amz-signature",
        "secret_access_key",
    )
    assert not any(token in text for token in forbidden)
