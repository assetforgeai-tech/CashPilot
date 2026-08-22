from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from starlette.requests import Request

from app import database, main


def _request() -> Request:
    return Request({"type": "http", "method": "DELETE", "path": "/api/nkn/slots/ipv4-001", "headers": []})


def _spec() -> dict[str, object]:
    return {
        "slot_id": "ipv4-001",
        "wallet_id": 7,
        "wallet_assignment_version": 3,
        "lease_client_id": "worker-a:nkn:ipv4-001",
        "public_ip": "8.8.8.8",
        "beneficiary_address": "NKNBeneficiaryAddress",
    }


def test_server_nkn_remove_is_worker_first_then_release_and_delete_record():
    async def run():
        with (
            patch.object(main, "_require_writer", return_value=None),
            patch.object(main, "_resolve_worker_id", AsyncMock(return_value=7)),
            patch.object(
                database,
                "get_provider_instance",
                AsyncMock(return_value={"instance_id": "nkn-direct-ipv4-001", "worker_id": 7, "status": "running"}),
            ),
            patch.object(database, "get_provider_instance_spec", AsyncMock(return_value=_spec())),
            patch.object(main, "_proxy_to_worker", AsyncMock(return_value={"status": "removed"})) as proxy,
            patch.object(database, "release_nkn_wallet", AsyncMock(return_value=True)) as release,
            patch.object(database, "remove_provider_instance", AsyncMock()) as remove,
            patch.object(database, "record_health_event", AsyncMock()),
        ):
            result = await main._remove_nkn_slot(_request(), "ipv4-001", worker_id=7)

        assert result["status"] == "removed"
        proxy.assert_awaited_once()
        assert proxy.await_args.args[:3] == (7, "DELETE", "/api/nkn/slots/ipv4-001")
        assert proxy.await_args.kwargs["json"]["wallet_assignment_version"] == 3
        release.assert_awaited_once_with(
            7,
            "worker-a:nkn:ipv4-001",
            release_reason="REMOVED",
            wallet_assignment_version=3,
        )
        remove.assert_awaited_once_with("nkn-direct-ipv4-001")

    asyncio.run(run())


def test_server_nkn_remove_does_not_release_when_worker_remove_fails():
    async def run():
        with (
            patch.object(main, "_require_writer", return_value=None),
            patch.object(main, "_resolve_worker_id", AsyncMock(return_value=7)),
            patch.object(
                database,
                "get_provider_instance",
                AsyncMock(return_value={"instance_id": "nkn-direct-ipv4-001", "worker_id": 7, "status": "running"}),
            ),
            patch.object(database, "get_provider_instance_spec", AsyncMock(return_value=_spec())),
            patch.object(main, "_proxy_to_worker", AsyncMock(side_effect=RuntimeError("worker down"))),
            patch.object(database, "release_nkn_wallet", AsyncMock()) as release,
            pytest.raises(main.HTTPException) as exc,
        ):
            await main._remove_nkn_slot(_request(), "ipv4-001", worker_id=7)
        assert exc.value.status_code in {503, 500}
        release.assert_not_awaited()

    asyncio.run(run())


def test_generic_nkn_stop_is_rejected_instead_of_stopping_the_node():
    async def run():
        with patch.object(main, "_require_writer", return_value=None), pytest.raises(main.HTTPException) as exc:
            await main._svc_stop(_request(), "nkn-direct-ipv4-001", worker_id=7)
        assert exc.value.status_code == 409

    asyncio.run(run())


def test_worker_proxy_sends_assignment_body_on_delete():
    async def run():
        response = type("Response", (), {"status_code": 200, "json": lambda self: {"status": "removed"}})()
        client = type("Client", (), {"request": AsyncMock(return_value=response)})()
        with (
            patch.object(
                main.database,
                "get_worker",
                AsyncMock(return_value={"status": "online", "url": "http://127.0.0.1:8081", "client_id": "worker-a"}),
            ),
            patch.object(main, "_get_verified_worker_url", AsyncMock(return_value=("http://127.0.0.1:8081", {}))),
            patch.object(main.httpx, "AsyncClient") as factory,
        ):
            factory.return_value.__aenter__ = AsyncMock(return_value=client)
            factory.return_value.__aexit__ = AsyncMock(return_value=None)
            await main._proxy_to_worker(7, "DELETE", "/api/nkn/slots/ipv4-001", json={"wallet_id": 7})
        assert client.request.await_args.args[:2] == ("DELETE", "http://127.0.0.1:8081/api/nkn/slots/ipv4-001")
        assert client.request.await_args.kwargs["json"] == {"wallet_id": 7}

    asyncio.run(run())
