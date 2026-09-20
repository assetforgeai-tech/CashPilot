"""Small, callback-driven EarnApp replacement transaction.

The module owns ordering only. Database CAS, worker mutation, and provider
verification stay in their existing adapters so a failed stage cannot silently
fall through to destructive cleanup.
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from typing import Any


class StagedReplacementError(RuntimeError):
    def __init__(self, stage: str, message: str = "staged replacement failed") -> None:
        super().__init__(f"{stage}: {message}")
        self.stage = stage


async def run_staged_replacement(
    *,
    reserve: Callable[[], Awaitable[Mapping[str, Any] | None]],
    deploy: Callable[[Mapping[str, Any]], Awaitable[Mapping[str, Any] | None]],
    verify: Callable[[Mapping[str, Any], Mapping[str, Any]], Awaitable[Mapping[str, Any] | None]],
    delete_old: Callable[[], Awaitable[bool]],
    remove_old: Callable[[], Awaitable[bool]],
    promote: Callable[[Mapping[str, Any], Mapping[str, Any]], Awaitable[bool]],
    cleanup: Callable[[Mapping[str, Any]], Awaitable[None]],
    state: MutableMapping[str, Any] | None = None,
    save_state: Callable[[Mapping[str, Any]], Awaitable[None]] | None = None,
) -> bool:
    durable = state is not None

    async def persist(stage: str, **values: Any) -> None:
        if state is None:
            return
        state.update({"state": stage, **values})
        if save_state is not None:
            await save_state(dict(state))

    persisted_state = str((state or {}).get("state") or "").upper()
    candidate = (state or {}).get("candidate") if persisted_state not in {"", "PREPARED"} else None
    if not isinstance(candidate, Mapping):
        candidate = await reserve()
        if not candidate:
            raise StagedReplacementError("reserve", "replacement proxy unavailable")
        await persist("PREPARED", candidate=dict(candidate))

    runtime: Mapping[str, Any] | None = (
        (state or {}).get("runtime")
        if persisted_state in {"STAGED", "LINKED", "VERIFIED", "OLD_DELETE_CONFIRMED", "PROMOTED_PENDING"}
        else None
    )
    try:
        if runtime is None:
            runtime = await deploy(candidate)
            if not runtime:
                raise StagedReplacementError("deploy", "replacement runtime unavailable")
            await persist("STAGED", candidate=dict(candidate), runtime=dict(runtime))

        if persisted_state not in {"VERIFIED", "OLD_DELETE_CONFIRMED", "PROMOTED_PENDING"}:
            evidence = await verify(runtime, candidate)
            if not _verified(evidence):
                raise StagedReplacementError("verify", "replacement workload is not verified")
            await persist("VERIFIED", candidate=dict(candidate), runtime=dict(runtime), evidence=dict(evidence or {}))

        persisted_state = str((state or {}).get("state") or "").upper()
        if persisted_state not in {"OLD_DELETE_CONFIRMED", "PROMOTED_PENDING"}:
            if not await delete_old():
                raise StagedReplacementError("delete_old", "remote device deletion was not confirmed")
            await persist("OLD_DELETE_CONFIRMED", candidate=dict(candidate), runtime=dict(runtime))

        persisted_state = str((state or {}).get("state") or "").upper()
        if persisted_state != "PROMOTED_PENDING":
            if not await remove_old():
                raise StagedReplacementError("remove_old", "old runtime removal was not confirmed")
            await persist("PROMOTED_PENDING", candidate=dict(candidate), runtime=dict(runtime))

        if not await promote(runtime, candidate):
            raise StagedReplacementError("promote", "replacement promotion was not confirmed")
        await persist("PROMOTED", candidate=dict(candidate), runtime=dict(runtime))
        if durable:
            await cleanup(runtime)
            await persist("CLEANED", candidate=dict(candidate), runtime=dict(runtime))
        else:
            # Preserve the historical callback contract for callers that have
            # not opted into durable state persistence.
            pass
        return True
    except Exception:
        # Before remote deletion, the old runtime is authoritative and only
        # the candidate may be removed. Once deletion is confirmed, cleanup is
        # unsafe: promotion must be retried from the persisted state instead.
        current_state = str((state or {}).get("state") or "").upper()
        safe_to_cleanup = current_state not in {"OLD_DELETE_CONFIRMED", "PROMOTED_PENDING", "PROMOTED"}
        if runtime is not None and safe_to_cleanup:
            # Cleanup is deliberately best-effort: caller retains recovery hold
            # when cleanup cannot be proven, rather than deleting more state.
            with contextlib.suppress(Exception):
                await cleanup(runtime)
        if state is not None and current_state in {"OLD_DELETE_CONFIRMED", "PROMOTED_PENDING"}:
            with contextlib.suppress(Exception):
                await persist(current_state, candidate=dict(candidate), runtime=dict(runtime or {}))
        raise


def _verified(evidence: Mapping[str, Any] | None) -> bool:
    if not isinstance(evidence, Mapping):
        return False
    return (
        evidence.get("authenticated") is True
        and evidence.get("device_present") is True
        and evidence.get("online") is True
        and evidence.get("banned") is not True
        and str(evidence.get("workload_state") or "").strip().lower() == "workload_verified"
    )
