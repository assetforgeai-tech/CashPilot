import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from app import main


def _worker(age_seconds: int, *, status: str = "online", generation: int = 1):
    return {
        "id": 7,
        "name": "worker-7",
        "status": status,
        "last_heartbeat": (datetime.now(UTC) - timedelta(seconds=age_seconds)).replace(tzinfo=None).isoformat(),
        "api_key_enc": "enrolled",
        "resource_generation": generation,
    }


def test_three_minute_stale_marks_offline_without_reclaiming():
    async def run():
        with (
            patch.object(main.database, "list_workers", AsyncMock(return_value=[_worker(181)])),
            patch.object(main.database, "set_worker_status", AsyncMock()) as set_status,
            patch.object(main.database, "reclaim_worker_resources", AsyncMock()) as reclaim,
        ):
            await main._check_stale_workers()
            set_status.assert_awaited_once_with(7, "offline")
            reclaim.assert_not_awaited()

    asyncio.run(run())


def test_fifteen_minute_stale_reclaims_once_with_generation_cas():
    async def run():
        with (
            patch.object(
                main.database, "list_workers", AsyncMock(return_value=[_worker(901, status="offline", generation=4)])
            ),
            patch.object(main.database, "set_worker_status", AsyncMock()),
            patch.object(
                main.database, "reclaim_worker_resources", AsyncMock(return_value={"reclaimed": True})
            ) as reclaim,
        ):
            await main._check_stale_workers()
            reclaim.assert_awaited_once()
            args = reclaim.await_args
            assert args.args[:2] == (7, "worker_lost")
            assert args.kwargs["expected_generation"] == 4
            assert args.args[2] == "worker-lost:7:4"

    asyncio.run(run())


def test_reclaimed_worker_heartbeat_is_quarantined_before_upsert():
    async def run():
        body = main.WorkerHeartbeat(name="worker-7", client_id="worker-7")
        request = type("Request", (), {"headers": {"authorization": "Bearer key"}})()
        with (
            patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="own")),
            patch.object(
                main.database,
                "get_worker_by_client_id",
                AsyncMock(return_value=_worker(901, status="reclaimed", generation=4)),
            ),
            patch.object(main.database, "upsert_worker", AsyncMock()) as upsert,
        ):
            result = await main.api_worker_heartbeat(request, body)
            assert result == {"status": "quarantined", "resource_generation": 4, "reenrollment_required": True}
            upsert.assert_not_awaited()

    asyncio.run(run())
