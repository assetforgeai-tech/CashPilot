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
