from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "azure_create" / "worker-startup.sh"


def test_worker_entrypoint_repairs_earnapp_state_ownership():
    entrypoint = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    assert "chown -R cashpilot:root /data/earnapp-nodes" in entrypoint


def test_entrypoint_preserves_project_venv_path_before_su_exec():
    entrypoint = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    assert 'export PATH="/app/.venv/bin:${PATH}"' in entrypoint


def test_azure_startup_requires_explicit_release_and_secrets():
    text = SCRIPT.read_text(encoding="utf-8")

    assert text.startswith("#!/usr/bin/env bash\nset -euo pipefail")
    assert "CASHPILOT_RELEASE:?" in text
    assert "CASHPILOT_API_KEY:?" in text
    assert "CASHPILOT_UI_URL:?" in text
    assert "CASHPILOT_WORKER_BIND_ADDR:?" in text
    assert "cashpilot-worker:${CASHPILOT_RELEASE}" in text
    assert "cashpilot-worker:1.53.0" not in text
    assert "--admin-password" not in text
    assert "GHCR_TOKEN=" not in text
    assert "/etc/cashpilot/worker.env" in text
    assert "chmod 0600 /etc/cashpilot/worker.env" in text
    assert "CASHPILOT_API_KEY: \\${CASHPILOT_API_KEY}" in text


def test_azure_startup_pins_systemd_to_the_generated_release_override():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "docker-compose.worker-${CASHPILOT_RELEASE}.override.yml" in text
    assert "-f docker-compose.fleet.yml" in text
    assert "-f docker-compose.worker.yml" not in text
    assert "ExecStart=/usr/bin/docker compose" in text
    assert "ExecStop=/usr/bin/docker compose" in text
    assert "scripts/bootstrap-worker.sh" in text


def test_azure_startup_writes_env_without_heredoc_and_rejects_newlines():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "printf '%s\\n'" in text
    assert "must not contain newlines" in text
    assert "cat > /etc/cashpilot/worker.env <<ENV" not in text
