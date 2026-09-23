"""Bounded Proxy Pool probe and rotation orchestration.

The database remains the durable authority.  This module only controls the
in-process work queues: it pages the inventory, limits in-flight probes, and
forwards a deduplicated dead-proxy event to the durable rotation helper.
"""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import random
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

DEFAULT_PAGE_SIZE = 500
DEFAULT_PROBE_QUEUE_CAPACITY = 1_024
DEFAULT_ROTATION_QUEUE_CAPACITY = 1_024
DEFAULT_PROBE_TIMEOUT_SECONDS = 30.0
MAX_PROBE_CONCURRENCY = 64

_automatic_recheck = contextvars.ContextVar("cashpilot_automatic_proxy_recheck", default=False)
_scan_lock = asyncio.Lock()


def enter_automatic_recheck() -> contextvars.Token[bool]:
    """Mark the current task as the automatic scheduler path."""

    return _automatic_recheck.set(True)


def reset_automatic_recheck(token: contextvars.Token[bool]) -> None:
    _automatic_recheck.reset(token)


def automatic_recheck_enabled() -> bool:
    return bool(_automatic_recheck.get())


def bounded_backoff(attempt: int, *, base: float = 1.0, cap: float = 3_600.0, jitter: float = 0.0) -> float:
    """Return a bounded exponential delay for a retryable queue item."""

    exponent = max(0, min(20, int(attempt or 0)))
    delay = min(float(cap), max(0.0, float(base)) * (2**exponent))
    if jitter:
        delay += random.uniform(0.0, min(abs(float(jitter)), delay or abs(float(jitter))))
    return min(float(cap), delay)


async def _await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def run_incremental_probe_scan(
    *,
    list_page: Callable[[int, int], Awaitable[Mapping[str, Any]] | Mapping[str, Any]],
    probe_one: Callable[[Mapping[str, Any]], Awaitable[Mapping[str, Any]] | Mapping[str, Any]],
    enqueue_rotation: Callable[[int, int], Awaitable[int] | int] | None = None,
    on_probe_result: Callable[[Mapping[str, Any], Mapping[str, Any]], Awaitable[Mapping[str, Any]] | Mapping[str, Any]]
    | None = None,
    process_rotation: Callable[[], Awaitable[Any] | Any] | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    queue_capacity: int = DEFAULT_PROBE_QUEUE_CAPACITY,
    rotation_queue_capacity: int = DEFAULT_ROTATION_QUEUE_CAPACITY,
    concurrency: int = 8,
    probe_timeout: float = DEFAULT_PROBE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Probe a paged inventory with bounded memory and immediate rotation events.

    ``list_page`` must return ``items`` and may return ``pages``/``total``.  A
    probe result is considered rotation-eligible only when it reports
    ``state=dead`` and a non-negative ``probe_generation``.  Duplicate
    ``(proxy_id, generation)`` events are collapsed before touching the
    durable queue.
    """

    if _scan_lock.locked():
        return {"status": "skipped_overlap", "checked": 0, "pages": 0, "timeouts": 0, "errors": 0}

    size = min(10_000, max(1, int(page_size or DEFAULT_PAGE_SIZE)))
    capacity = max(1, int(queue_capacity or DEFAULT_PROBE_QUEUE_CAPACITY))
    rotation_capacity = max(1, int(rotation_queue_capacity or DEFAULT_ROTATION_QUEUE_CAPACITY))
    workers = min(MAX_PROBE_CONCURRENCY, max(1, int(concurrency or 1)))
    timeout = max(0.001, float(probe_timeout or DEFAULT_PROBE_TIMEOUT_SECONDS))

    async with _scan_lock:
        probe_queue: asyncio.Queue[Mapping[str, Any] | None] = asyncio.Queue(maxsize=capacity)
        rotation_queue: asyncio.Queue[tuple[int, int] | None] = asyncio.Queue(maxsize=rotation_capacity)
        dedupe: OrderedDict[tuple[int, int], None] = OrderedDict()
        metrics = {
            "status": "ok",
            "checked": 0,
            "pages": 0,
            "timeouts": 0,
            "errors": 0,
            "rotation_enqueued": 0,
            "rotation_events": 0,
            "max_probe_queue": 0,
        }
        metrics_lock = asyncio.Lock()

        async def add_rotation_event(result: Mapping[str, Any]) -> None:
            if enqueue_rotation is None or str(result.get("state") or result.get("status") or "").lower() != "dead":
                return
            try:
                proxy_id = int(result.get("proxy_id") or 0)
                generation = int(result.get("probe_generation") or -1)
            except (TypeError, ValueError):
                return
            key = (proxy_id, generation)
            if proxy_id <= 0 or generation < 0 or key in dedupe:
                return
            dedupe[key] = None
            while len(dedupe) > rotation_capacity:
                dedupe.popitem(last=False)
            await rotation_queue.put((proxy_id, generation))

        async def probe_worker() -> None:
            while True:
                row = await probe_queue.get()
                try:
                    if row is None:
                        return
                    async with metrics_lock:
                        metrics["checked"] += 1
                    try:
                        result = await asyncio.wait_for(_await(probe_one(row)), timeout=timeout)
                    except TimeoutError:
                        async with metrics_lock:
                            metrics["timeouts"] += 1
                        if on_probe_result is not None:
                            await _await(on_probe_result(row, {"status": "inconclusive", "reason": "probe_timeout"}))
                        continue
                    except Exception:
                        async with metrics_lock:
                            metrics["errors"] += 1
                        continue
                    if on_probe_result is not None:
                        try:
                            result = await _await(on_probe_result(row, result))
                        except Exception:
                            async with metrics_lock:
                                metrics["errors"] += 1
                            continue
                    try:
                        await add_rotation_event(result)
                    except Exception:
                        async with metrics_lock:
                            metrics["errors"] += 1
                finally:
                    probe_queue.task_done()

        async def rotation_worker() -> None:
            while True:
                event = await rotation_queue.get()
                try:
                    if event is None:
                        return
                    proxy_id, generation = event
                    try:
                        inserted = int(await _await(enqueue_rotation(proxy_id, generation))) if enqueue_rotation else 0
                    except Exception:
                        inserted = 0
                        async with metrics_lock:
                            metrics["errors"] += 1
                    async with metrics_lock:
                        metrics["rotation_events"] += 1
                        metrics["rotation_enqueued"] += max(0, inserted)
                    if process_rotation is not None:
                        try:
                            await _await(process_rotation())
                        except Exception:
                            async with metrics_lock:
                                metrics["errors"] += 1
                finally:
                    rotation_queue.task_done()

        probe_tasks = [asyncio.create_task(probe_worker()) for _ in range(workers)]
        rotation_task = asyncio.create_task(rotation_worker())
        try:
            page = 1
            total_pages: int | None = None
            while total_pages is None or page <= total_pages:
                payload = await _await(list_page(page, size))
                items = list(payload.get("items") or []) if isinstance(payload, Mapping) else []
                if isinstance(payload, Mapping):
                    raw_pages = payload.get("pages")
                    if raw_pages is not None:
                        try:
                            total_pages = max(1, int(raw_pages))
                        except (TypeError, ValueError):
                            total_pages = None
                if not items and (total_pages is None or page >= total_pages):
                    break
                metrics["pages"] += 1
                for row in items:
                    await probe_queue.put(row)
                    metrics["max_probe_queue"] = max(metrics["max_probe_queue"], probe_queue.qsize())
                page += 1
                if total_pages is None and len(items) < size:
                    break
            await probe_queue.join()
            await rotation_queue.join()
        finally:
            for _ in probe_tasks:
                await probe_queue.put(None)
            await asyncio.gather(*probe_tasks)
            await rotation_queue.put(None)
            await rotation_task
        return metrics


async def drain_rotation_queue(
    *,
    claim_request: Callable[[], Awaitable[Mapping[str, Any] | None] | Mapping[str, Any] | None],
    apply_request: Callable[[Mapping[str, Any]], Awaitable[bool] | bool],
    complete_request: Callable[..., Awaitable[bool] | bool],
    max_items: int = 64,
) -> dict[str, int]:
    """Claim and apply durable rotation work sequentially.

    Database CAS fencing remains authoritative.  A failed apply is returned to
    the durable helper for its persisted exponential backoff; this function
    never releases or deletes the old lease itself.
    """

    claimed = applied = failed = 0
    for _ in range(max(0, int(max_items or 0))):
        request = await _await(claim_request())
        if not request:
            break
        claimed += 1
        token = str(request.get("lease_token") or "")
        try:
            success = bool(await _await(apply_request(request)))
        except Exception as exc:
            success = False
            error = type(exc).__name__
        else:
            error = "" if success else "rotation_apply_failed"
        if success:
            try:
                completed = bool(
                    await _await(
                        complete_request(
                            int(request["id"]),
                            "succeeded",
                            lease_token=token,
                            replacement_committed=True,
                        )
                    )
                )
            except Exception:
                completed = False
            if completed:
                applied += 1
            else:
                failed += 1
        else:
            try:
                await _await(
                    complete_request(
                        int(request["id"]),
                        "failed",
                        error=error,
                        lease_token=token,
                    )
                )
            finally:
                failed += 1
    return {"claimed": claimed, "applied": applied, "failed": failed}


__all__ = [
    "automatic_recheck_enabled",
    "bounded_backoff",
    "drain_rotation_queue",
    "enter_automatic_recheck",
    "reset_automatic_recheck",
    "run_incremental_probe_scan",
]
