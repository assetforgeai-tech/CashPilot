from __future__ import annotations

from unittest.mock import MagicMock

from app import orchestrator


def test_uprock_provider_evidence_reads_daemon_status_and_device_id():
    container = MagicMock()
    container.exec_run.side_effect = [
        MagicMock(
            exit_code=0,
            output=b'{"status":"ok","authenticated":true,"earning":true,"earn_rate":0.5,"version":"v0.0.38"}\n',
        ),
        MagicMock(exit_code=0, output=b"wss://ws.olostep.com?device_id=uprock_abc123&platform=desktop-linux"),
    ]

    assert orchestrator._provider_evidence("uprock", container) == {
        "ok": True,
        "authenticated": True,
        "earning": True,
        "earn_rate": 0.5,
        "version": "v0.0.38",
        "device_id": "uprock_abc123",
    }


def test_non_uprock_provider_evidence_is_empty():
    assert orchestrator._provider_evidence("demo-provider", MagicMock()) == {}


def test_wipter_provider_evidence_reads_login_and_traffic_logs():
    container = MagicMock()
    container.exec_run.return_value = MagicMock(exit_code=1)
    container.logs.return_value = b"Credential stored for service: com.wipter.auth.production\n<<< PONG"

    assert orchestrator._provider_evidence("wipter", container) == {
        "ok": True,
        "authenticated": True,
        "earning": True,
        "traffic_seen": True,
    }


def test_wipter_provider_evidence_accepts_persisted_login_file():
    container = MagicMock()
    container.exec_run.return_value = MagicMock(exit_code=0)
    container.logs.return_value = b"HTTPS Request ID abc"

    assert orchestrator._provider_evidence("wipter", container) == {
        "ok": True,
        "authenticated": True,
        "earning": True,
        "traffic_seen": True,
    }
