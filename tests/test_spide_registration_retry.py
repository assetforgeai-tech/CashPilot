import asyncio

import pytest

from app import main


@pytest.mark.asyncio
async def test_spide_registration_retries_after_transient_rejection(monkeypatch):
    calls = 0

    async def logs(*_args, **_kwargs):
        return {"logs": "Device key: SPIDE-abc_123456"}

    async def worker(_worker_id):
        return {"name": "worker-1", "system_info": {"egress_ip": "8.8.8.8"}}

    async def register(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("503 temporary")

    async def event(*_args, **_kwargs):
        return None

    async def no_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(main, "_proxy_worker_logs", logs)
    monkeypatch.setattr(main.database, "get_worker", worker)
    monkeypatch.setattr(main.database, "record_health_event", event)
    monkeypatch.setattr(main.provider_automation, "register_spide_device", register)
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    await main._register_spide_device_from_worker_logs(7, "spide-node", "direct", "worker-1", token="token")

    assert calls == 2
