from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from app import worker_api


def test_myst_state_file_round_trips_without_raw_wallet(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    state = {
        "myst_wallet_id": 7,
        "myst_wallet_client_id": "worker-a",
        "myst_wallet_assignment_version": 3,
        "myst_node_identity": "0xnode",
    }
    worker_api._save_myst_wallet_state(state)
    saved = json.loads(Path(tmp_path, "myst-wallet.json").read_text(encoding="utf-8"))
    assert saved["myst_wallet_id"] == 7
    assert "myst_wallet_raw" not in saved


def test_myst_wallet_heartbeat_posts_versioned_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_UI_URL", "https://ui.example")
    monkeypatch.setenv("CASHPILOT_API_KEY", "fleet-key")
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            {
                "path": request.url.path,
                "body": json.loads(request.content.decode("utf-8")),
            }
        )
        return httpx.Response(200, json={"status": "ok"}, request=request)

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await worker_api._post_myst_wallet_event(
                client,
                "heartbeat",
                {
                    "client_id": "worker-a",
                    "wallet_id": 7,
                    "wallet_assignment_version": 3,
                    "node_identity": "0xnode",
                    "runtime_status": "running",
                    "evidence": {"container_id": "abc"},
                },
            )

    asyncio.run(run())
    assert calls[0]["path"] == "/api/myst-wallets/heartbeat"
    assert calls[0]["body"]["wallet_assignment_version"] == 3
