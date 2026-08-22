from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import worker_api


def _state(tmp_path):
    slots = [
        {
            "slot_id": "ipv4-001",
            "public_ip": "8.8.8.8",
            "private_ip": "10.20.0.4",
            "interface": "eth0",
            "subnet": "10.20.0.0/24",
            "gateway": "10.20.0.1",
            "docker_network": "cashpilot-direct-ipv4-001",
            "bridge_subnet": "10.253.1.0/24",
            "bridge_gateway": "10.253.1.1",
            "source": "azure_imds",
            "route_ready": True,
        }
    ]
    path = tmp_path / "slots.json"
    path.write_text(json.dumps({"version": 1, "slots": slots}), encoding="utf-8")
    return path, slots


def test_worker_loads_only_validated_slot_state(tmp_path, monkeypatch):
    path, slots = _state(tmp_path)
    monkeypatch.setenv("CASHPILOT_PUBLIC_IP_SLOTS_FILE", str(path))
    assert worker_api._load_public_ip_slots() == slots

    path.write_text('{"version": 99, "slots": []}', encoding="utf-8")
    assert worker_api._load_public_ip_slots() == []


def test_worker_falls_back_to_its_persistent_data_volume_for_canonical_bootstrap(tmp_path, monkeypatch):
    path, slots = _state(tmp_path)
    data_dir = tmp_path / "worker-data"
    data_dir.mkdir()
    (data_dir / "public-ip-slots.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.delenv("CASHPILOT_PUBLIC_IP_SLOTS_FILE", raising=False)
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(data_dir))
    assert worker_api._load_public_ip_slots() == slots


def test_network_slots_endpoint_is_read_only_and_returns_no_wallet_material(tmp_path, monkeypatch):
    path, slots = _state(tmp_path)
    monkeypatch.setenv("CASHPILOT_PUBLIC_IP_SLOTS_FILE", str(path))
    with patch.object(worker_api, "_verify_api_key", return_value=None), TestClient(worker_api.app) as client:
        response = client.get("/api/network/slots")
    assert response.status_code == 200
    assert response.json() == slots
    assert "wallet_json" not in response.text
    assert "wallet_pswd" not in response.text


def test_heartbeat_includes_slots_as_system_metadata_without_secret_fields(tmp_path, monkeypatch):
    path, slots = _state(tmp_path)
    monkeypatch.setenv("CASHPILOT_PUBLIC_IP_SLOTS_FILE", str(path))
    monkeypatch.setattr(worker_api, "UI_URL", "https://ui.example")
    captured: dict[str, object] = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, *, json, headers):
            captured.update(json)
            return _Response()

    async def run():
        with (
            patch.object(worker_api.orchestrator, "get_status", return_value=[]),
            patch.object(worker_api.orchestrator, "docker_available", return_value=True),
            patch.object(worker_api, "_detect_egress_ip", AsyncMock(return_value="8.8.8.8")),
            patch.object(worker_api, "_detect_network_type", return_value="hosting"),
            patch.object(worker_api.httpx, "AsyncClient", return_value=_Client()),
        ):
            await worker_api._send_heartbeat()

    asyncio.run(run())
    assert captured["system_info"]["public_ip_slots"] == slots  # type: ignore[index]
    assert "wallet_json" not in json.dumps(captured)
    assert "wallet_pswd" not in json.dumps(captured)
