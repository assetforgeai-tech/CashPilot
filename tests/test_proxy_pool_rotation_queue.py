import asyncio

import pytest

from app import proxy_pool_scheduler


@pytest.mark.asyncio
async def test_rotation_events_are_deduplicated_before_durable_enqueue():
    calls = []

    async def list_page(_page: int, _page_size: int):
        return {
            "items": [
                {"id": 11},
                {"id": 11},
                {"id": 12},
            ],
            "pages": 1,
            "total": 3,
        }

    async def probe(row):
        return {"proxy_id": row["id"], "state": "dead", "probe_generation": 4}

    async def enqueue(proxy_id: int, generation: int):
        calls.append((proxy_id, generation))
        return 1

    result = await proxy_pool_scheduler.run_incremental_probe_scan(
        list_page=list_page,
        probe_one=probe,
        enqueue_rotation=enqueue,
        concurrency=2,
        queue_capacity=2,
        rotation_queue_capacity=1,
    )

    assert calls == [(11, 4), (12, 4)]
    assert result["rotation_enqueued"] == 2


@pytest.mark.asyncio
async def test_probe_timeout_is_bounded_and_reported_without_rotation():
    async def list_page(_page: int, _page_size: int):
        return {"items": [{"id": 1}], "pages": 1, "total": 1}

    async def probe(_row):
        await asyncio.sleep(0.05)
        return {"proxy_id": 1, "state": "dead", "probe_generation": 1}

    result = await proxy_pool_scheduler.run_incremental_probe_scan(
        list_page=list_page,
        probe_one=probe,
        enqueue_rotation=lambda *_args: asyncio.sleep(0),
        concurrency=1,
        probe_timeout=0.001,
    )

    assert result["checked"] == 1
    assert result["timeouts"] == 1
    assert result["rotation_enqueued"] == 0


def test_retry_backoff_is_exponential_but_bounded():
    assert proxy_pool_scheduler.bounded_backoff(0) == 1
    assert proxy_pool_scheduler.bounded_backoff(3) == 8
    assert proxy_pool_scheduler.bounded_backoff(99, cap=10) == 10


@pytest.mark.asyncio
async def test_drain_rotation_queue_completes_success_and_persists_failure():
    requests = iter(
        [
            {"id": 1, "lease_token": "token-1"},
            {"id": 2, "lease_token": "token-2"},
            None,
        ]
    )
    applied = []
    completed = []

    async def claim():
        return next(requests)

    async def apply(request):
        applied.append(request["id"])
        return request["id"] == 1

    async def complete(request_id, state, **kwargs):
        completed.append((request_id, state, kwargs))
        return True

    result = await proxy_pool_scheduler.drain_rotation_queue(
        claim_request=claim,
        apply_request=apply,
        complete_request=complete,
        max_items=2,
    )

    assert result == {"claimed": 2, "applied": 1, "failed": 1}
    assert applied == [1, 2]
    assert completed[0][1:] == ("succeeded", {"lease_token": "token-1", "replacement_committed": True})
    assert completed[1][1:] == ("failed", {"error": "rotation_apply_failed", "lease_token": "token-2"})
