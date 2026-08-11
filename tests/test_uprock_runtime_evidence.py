from __future__ import annotations

from unittest.mock import MagicMock

from app import orchestrator

def test_uprock_provider_evidence_reads_daemon_status_and_device_id():
    container = MagicMock()
    container.exec_run.side_effect = [
        MagicMock(exit_code=0, output=b'{"status":"ok","authenticated":true,"earning":true,"earn_rate":0.5,"version":"v0.0.38"}\n'),
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
    assert orchestrator._provider_evidence("grass", MagicMock()) == {}
