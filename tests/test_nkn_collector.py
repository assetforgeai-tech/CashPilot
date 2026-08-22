from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app import main
from app.collectors.nkn import NKN_RPC_URL, NknCollector


def _response(payload, status_code=200):
    request = httpx.Request("POST", NKN_RPC_URL)
    return httpx.Response(status_code, json=payload, request=request)


def test_nkn_collector_reads_official_balance_rpc_in_nkn_units():
    async def run():
        collector = NknCollector("NKNBeneficiaryAddress")
        client = MagicMock()
        client.is_closed = False
        client.post = AsyncMock(return_value=_response({"jsonrpc": "2.0", "result": {"amount": "16996.39104266"}}))
        collector._client = client
        result = await collector.collect()
        assert result.platform == "nkn"
        assert result.balance == 16996.39104266
        assert result.currency == "NKN"
        request = client.post.await_args
        assert request.args[0] == NKN_RPC_URL
        assert request.kwargs["json"] == {
            "jsonrpc": "2.0",
            "method": "getbalancebyaddr",
            "params": {"address": "NKNBeneficiaryAddress"},
            "id": 1,
        }

    asyncio.run(run())


def test_nkn_collector_maps_timeout_or_bad_shape_to_safe_error():
    async def run():
        collector = NknCollector("NKNBeneficiaryAddress")
        client = MagicMock()
        client.is_closed = False
        client.post = AsyncMock(side_effect=httpx.ReadTimeout("upstream timeout"))
        collector._client = client
        result = await collector.collect()
        assert result.error
        assert "upstream timeout" not in result.error

        client.post = AsyncMock(return_value=_response({"jsonrpc": "2.0", "result": {}}))
        result = await collector.collect()
        assert result.error == "NKN balance collection failed"

    asyncio.run(run())


def test_nkn_collector_requires_only_beneficiary_address_and_never_logs_secret():
    async def run():
        collector = NknCollector("")
        result = await collector.collect()
        assert result.error
        assert "NKNBeneficiary" not in result.error

    asyncio.run(run())


def test_nkn_collector_node_summary_counts_worker_evidence():
    collector = NknCollector("NKNBeneficiaryAddress")
    summary = collector.node_summary(
        [
            {"evidence": {"online": True}},
            {"evidence": {"online": False}},
            {"evidence": {}},
        ]
    )
    assert summary == {"total": 3, "online": 1, "offline": 2}


def test_collection_includes_nkn_without_a_global_deployment_row():
    async def run():
        with (
            patch.object(main.database, "get_deployments", AsyncMock(return_value=[])),
            patch.object(
                main.database,
                "get_config",
                AsyncMock(return_value={"nkn_beneficiary_address": "NKNBeneficiaryAddress"}),
            ),
            patch.object(main.database, "list_nkn_wallets", AsyncMock(return_value=[{"state": "LEASED"}])),
        ):
            deployments = await main._collection_deployments()
        assert deployments == [{"slug": "nkn", "status": "external"}]

    asyncio.run(run())
