from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app import main


def test_nkn_dashboard_summary_counts_only_leased_instances_and_redacts_wallet_material():
    async def run():
        with patch.object(
            main.database,
            "list_nkn_wallets",
            AsyncMock(
                return_value=[
                    {
                        "id": 1,
                        "state": "LEASED",
                        "leased_to_client_id": "worker-a:nkn:ipv4-001",
                        "evidence_json": '{"online":true}',
                    },
                    {
                        "id": 2,
                        "state": "LEASED",
                        "leased_to_client_id": "worker-a:nkn:ipv4-002",
                        "evidence_json": '{"online":false}',
                    },
                    {"id": 3, "state": "AVAILABLE", "leased_to_client_id": "", "evidence_json": "{}"},
                ],
            ),
        ):
            result = await main._nkn_dashboard_summary()
        assert result == {"total_nodes": 2, "online": 1, "offline": 1}
        assert "wallet_json" not in str(result)

    asyncio.run(run())


def test_fleet_summary_exposes_nkn_counts_without_changing_legacy_counts():
    async def run():
        with (
            patch.object(main.database, "list_workers", AsyncMock(return_value=[])),
            patch.object(main.database, "list_nkn_wallets", AsyncMock(return_value=[])),
            patch.object(main, "_require_reader", return_value=None),
        ):
            result = await main.api_fleet_summary(type("Request", (), {"headers": {}})())
        assert result["total_workers"] == 0
        assert result["nkn"] == {"total_nodes": 0, "online": 0, "offline": 0}

    asyncio.run(run())
