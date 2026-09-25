import asyncio

import pytest

from app import proxy_pool_scheduler


@pytest.mark.asyncio
async def test_dead_probe_enqueues_rotation_before_slow_page_finishes():
    slow_finished = asyncio.Event()
    rotation_seen = asyncio.Event()
    pages = [[{"id": 1, "assigned_worker_id": 7}, {"id": 2, "assigned_worker_id": 8}]]

    async def list_page(page: int, page_size: int):
        assert page == 1
        assert page_size == 500
        return {"items": pages[0], "pages": 1, "total": 2}

    async def probe(row):
        if row["id"] == 2:
            await asyncio.sleep(0.05)
            slow_finished.set()
        return {
            "proxy_id": row["id"],
            "state": "dead" if row["id"] == 1 else "alive",
            "probe_generation": row["id"],
        }

    async def enqueue(proxy_id: int, generation: int):
        assert (proxy_id, generation) == (1, 1)
        assert not slow_finished.is_set()
        rotation_seen.set()
        return 1

    result = await proxy_pool_scheduler.run_incremental_probe_scan(
        list_page=list_page,
        probe_one=probe,
        enqueue_rotation=enqueue,
        concurrency=2,
        page_size=500,
        queue_capacity=2,
    )

    assert rotation_seen.is_set()
    assert result["checked"] == 2
    assert result["rotation_enqueued"] == 1


@pytest.mark.asyncio
async def test_incremental_scan_uses_pages_and_bounded_probe_queue():
    total = 50_000
    page_size = 500
    max_pending = 0
    pending = 0
    pages_seen = []

    async def list_page(page: int, requested_size: int):
        nonlocal pending, max_pending
        pages_seen.append(page)
        start = (page - 1) * requested_size
        end = min(total, start + requested_size)
        return {
            "items": [{"id": index} for index in range(start + 1, end + 1)],
            "pages": (total + requested_size - 1) // requested_size,
            "total": total,
        }

    async def probe(row):
        nonlocal pending, max_pending
        pending += 1
        max_pending = max(max_pending, pending)
        await asyncio.sleep(0)
        pending -= 1
        return {"proxy_id": row["id"], "state": "alive", "probe_generation": row["id"]}

    result = await proxy_pool_scheduler.run_incremental_probe_scan(
        list_page=list_page,
        probe_one=probe,
        concurrency=8,
        page_size=page_size,
        queue_capacity=16,
    )

    assert result["checked"] == total
    assert result["pages"] == total // page_size
    assert pages_seen == list(range(1, result["pages"] + 1))
    assert max_pending <= 8


@pytest.mark.asyncio
async def test_overlapping_scans_are_skipped():
    entered = asyncio.Event()
    release = asyncio.Event()

    async def list_page(page: int, page_size: int):
        entered.set()
        await release.wait()
        return {"items": [], "pages": 1, "total": 0}

    first = asyncio.create_task(
        proxy_pool_scheduler.run_incremental_probe_scan(
            list_page=list_page,
            probe_one=lambda _row: asyncio.sleep(0),
        )
    )
    await entered.wait()
    second = await proxy_pool_scheduler.run_incremental_probe_scan(
        list_page=list_page,
        probe_one=lambda _row: asyncio.sleep(0),
    )
    release.set()
    first_result = await first

    assert second["status"] == "skipped_overlap"
    assert first_result["status"] == "ok"
