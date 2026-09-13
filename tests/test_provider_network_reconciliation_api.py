from unittest.mock import AsyncMock

import pytest

from app import main


@pytest.mark.asyncio
async def test_network_reconciliation_exposes_lane_contract(monkeypatch):
    monkeypatch.setattr(main, "_require_owner", lambda _request: {"role": "owner"})
    monkeypatch.setattr(
        main.database,
        "list_workers",
        AsyncMock(
            return_value=[
                {
                    "id": 7,
                    "containers": '[{"name":"earnfm-direct-w7-ipv4-001","slug":"earnfm"}]',
                    "system_info": '{"containers_inventory_confirmed":true}',
                }
            ]
        ),
    )
    monkeypatch.setattr(
        main.database,
        "list_provider_instances",
        AsyncMock(
            return_value=[
                {
                    "instance_id": "earnfm-direct-w7-ipv4-001",
                    "slug": "earnfm",
                    "worker_id": 7,
                    "mode": "direct",
                    "status": "running",
                }
            ]
        ),
    )

    result = await main.api_provider_network_reconciliation(None)

    report = result["reports"][0]
    assert report["contract"]["topology"] == "slot_both"
    assert report["contract"]["lanes"] == ["direct", "proxy"]
    assert report["lane_counts"] == {"direct": 1, "proxy": 0}


@pytest.mark.asyncio
async def test_network_reconciliation_hydrates_encrypted_instance_spec(monkeypatch):
    monkeypatch.setattr(main, "_require_owner", lambda _request: {"role": "owner"})
    monkeypatch.setattr(
        main.database,
        "list_workers",
        AsyncMock(
            return_value=[
                {
                    "id": 8,
                    "containers": '[{"name":"packetstream-proxy-w8-proxy-001","slug":"packetstream","status":"running"}]',
                    "system_info": '{"containers_inventory_confirmed":true}',
                }
            ]
        ),
    )
    rows = [
        {
            "instance_id": "packetstream-proxy-w8-proxy-001",
            "slug": "packetstream",
            "worker_id": 8,
            "mode": "proxy",
            "status": "running",
            "spec_encrypted": "encrypted",
        }
    ]
    monkeypatch.setattr(main.database, "list_provider_instances", AsyncMock(return_value=rows))
    monkeypatch.setattr(
        main.database,
        "get_provider_instance_spec",
        AsyncMock(return_value={"proxy": {"exit_ip": "203.0.113.8", "proxy_id": 8}}),
    )

    result = await main.api_provider_network_reconciliation(None)

    assert result["reports"][0]["findings"]
    main.database.get_provider_instance_spec.assert_awaited_once_with("packetstream-proxy-w8-proxy-001")


@pytest.mark.asyncio
async def test_network_reconciliation_skips_superseded_worker_registration(monkeypatch):
    monkeypatch.setattr(main, "_require_owner", lambda _request: {"role": "owner"})
    monkeypatch.setattr(
        main.database,
        "list_workers",
        AsyncMock(
            return_value=[
                {
                    "id": 7,
                    "url": "http://worker:8081",
                    "status": "offline",
                    "last_heartbeat": "2026-01-01 00:00:00",
                    "containers": '[{"name":"stale","slug":"wipter"}]',
                    "system_info": '{"containers_inventory_confirmed":true}',
                },
                {
                    "id": 8,
                    "url": "http://worker:8081",
                    "status": "online",
                    "last_heartbeat": "2026-01-02 00:00:00",
                    "containers": "[]",
                    "system_info": '{"containers_inventory_confirmed":true}',
                },
            ]
        ),
    )
    monkeypatch.setattr(main.database, "list_provider_instances", AsyncMock(return_value=[]))

    result = await main.api_provider_network_reconciliation(None)

    assert result["reports"] == []
@pytest.mark.asyncio
async def test_network_reconciliation_skips_offline_worker(monkeypatch):
    monkeypatch.setattr(main, "_require_owner", lambda _request: {"role": "owner"})
    monkeypatch.setattr(
        main.database,
        "list_workers",
        AsyncMock(
            return_value=[
                {
                    "id": 9,
                    "url": "http://offline:8081",
                    "status": "offline",
                    "containers": '[{"name":"old","slug":"earnapp"}]',
                    "system_info": '{"containers_inventory_confirmed":true}',
                }
            ]
        ),
    )
    monkeypatch.setattr(
        main.database,
        "list_provider_instances",
        AsyncMock(
            return_value=[
                {
                    "instance_id": "old",
                    "slug": "earnapp",
                    "worker_id": 9,
                    "mode": "proxy",
                    "status": "running",
                }
            ]
        ),
    )

    result = await main.api_provider_network_reconciliation(None)

    assert result["reports"] == []
