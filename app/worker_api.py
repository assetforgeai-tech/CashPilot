"""CashPilot Worker — Lightweight container management agent.

Runs on each server in the fleet. Manages local Docker containers,
sends heartbeats to the CashPilot UI, and accepts commands from it.

Configure via environment variables:
    CASHPILOT_UI_URL        URL of the CashPilot UI (e.g. http://192.168.10.100:8080)
    CASHPILOT_API_KEY       Shared API key for worker<->UI auth
    CASHPILOT_WORKER_NAME   Human-readable name (default: hostname)
    CASHPILOT_PORT          Mini-UI port (default: 8081)
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hmac
import json
import logging
import os
import platform
import re
import shutil
import socket
import subprocess
import time
import urllib.parse
import uuid
from collections.abc import Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import wraps
from html import escape as _esc
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, model_validator

from app import (
    earnapp_lxd_runtime,
    earnapp_policy,
    earnapp_runtime,
    egress,
    fleet_key,
    myst_runtime,
    nkn_lxd_runtime,
    nkn_runtime,
    orchestrator,
    provider_runtime,
    proxy_egress,
    public_ip_slots,
    singbox_config,
    state_backup,
    version,
)

try:
    from app.catalog import get_services as _catalog_get_services
except ImportError:
    # Worker image may not include the catalog module in some builds.
    _catalog_get_services = None  # type: ignore[assignment]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _reject_earnapp_runtime_mutation(
    logical_node_id: str = "earnapp",
    *,
    platform: str = "",
    runtime_backend: str = "",
) -> None:
    """Fail closed before a disabled EarnApp platform is touched."""
    if earnapp_policy.is_protected_runtime_reference(logical_node_id):
        raise HTTPException(status_code=409, detail="Protected EarnApp node is inspection-only")
    # These routes are already provider-scoped; include the canonical slug so
    # legacy logical-node IDs cannot bypass the policy by lacking a prefix.
    policy = provider_runtime.mutation_block(
        logical_node_id,
        {
            "provider_slug": "earnapp",
            "platform": platform,
            "runtime_backend": runtime_backend,
        },
    )
    if policy:
        raise HTTPException(status_code=409, detail=policy.policy_message)


def _reject_protected_runtime_alias(value: str) -> None:
    """Block exact protected aliases before any generic host mutation."""
    if earnapp_policy.is_protected_runtime_reference(value):
        raise HTTPException(status_code=409, detail="Protected EarnApp node is inspection-only")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

UI_URL = os.getenv("CASHPILOT_UI_URL", "")
API_KEY: str = fleet_key.resolve_fleet_key()
if not API_KEY:
    logger.warning("Could not resolve fleet API key — set CASHPILOT_API_KEY or mount a shared /fleet volume")
WORKER_NAME = os.getenv("CASHPILOT_WORKER_NAME", socket.gethostname())
WORKER_PORT = int(os.getenv("CASHPILOT_PORT", "8081"))
WORKER_URL = os.getenv("CASHPILOT_WORKER_URL", "")
HEARTBEAT_INTERVAL = 60  # seconds
# Stop locally one heartbeat before the server's 15-minute reclaim boundary so
# the old wallet cannot still be running when the server makes it available.
NKN_LEASE_GUARD_SECONDS = 14 * 60
_heartbeat_task: asyncio.Task | None = None
_ui_connected = False
_last_heartbeat: str = "never"
_last_error: str = ""

# Consecutive 401s while holding our own per-worker key. One is unremarkable (the UI
# may be restarting); a run of them means our identity no longer matches our key.
_consecutive_auth_failures = 0
_AUTH_FAILURE_ALARM_AFTER = 3
# Well above the alarm: the operator is told first, and a key is only discarded
# after the rejection has clearly persisted rather than on a flaky link.
_AUTH_FAILURE_DISCARD_AFTER = 10

# Per-worker fleet key. On first contact the UI enrolls this worker and hands back
# a key unique to us, which we persist here (in our own private /data, never the
# shared /fleet volume) and use for all subsequent auth in both directions. Until
# enrollment we authenticate with the shared bootstrap key.
_WORKER_KEY_FILE = Path(os.getenv("CASHPILOT_DATA_DIR", "/data")) / ".worker_key"

# A proxy rotation recreates a Docker container under its stable name. The
# server serializes most rotations, but a retry can still arrive while the
# first request is mutating Docker. Keep the worker-side boundary as well so
# later requests observe the pending CAS marker instead of racing the name.
_EARNAPP_NODE_MUTATION_LOCKS: dict[tuple[int, str], asyncio.Lock] = {}


def _earnapp_node_mutation_lock(logical_node_id: str) -> asyncio.Lock:
    loop_key = (id(asyncio.get_running_loop()), str(logical_node_id or "").strip())
    return _EARNAPP_NODE_MUTATION_LOCKS.setdefault(loop_key, asyncio.Lock())


def _serialize_earnapp_node_mutation(handler):
    """Serialize apply/finalize calls for one logical node on this worker."""

    @wraps(handler)
    async def guarded(request, *args, **kwargs):
        _verify_api_key(request)
        logical_node_id = args[0] if args else kwargs.get("logical_node_id", kwargs.get("slug", ""))
        async with _earnapp_node_mutation_lock(logical_node_id):
            return await handler(request, *args, **kwargs)

    return guarded


def _load_worker_key() -> str | None:
    try:
        if _WORKER_KEY_FILE.is_file():
            return _WORKER_KEY_FILE.read_text().strip() or None
    except OSError as exc:
        logger.warning("Could not read per-worker key: %s", exc)
    return None


def _save_worker_key(key: str) -> bool:
    """Persist the newly issued per-worker key to disk, then adopt it in memory.

    Returns True once the key is durably on disk. On persistence failure the
    key is NOT adopted -- we keep authenticating with whatever key was active
    before, so a write failure here can never leave us relying on a key that
    only exists in memory and vanishes on the next restart (lockout).
    """
    try:
        _WORKER_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _WORKER_KEY_FILE.write_text(key)
        _WORKER_KEY_FILE.chmod(0o600)
    except OSError as exc:
        logger.error("Could not persist per-worker key — NOT adopting it: %s", exc)
        return False
    global _worker_key
    _worker_key = key
    return True


def _discard_worker_key(reason: str) -> None:
    """Forget our per-worker key so the next heartbeat re-enrols.

    Removing a worker in the fleet dashboard deletes its row and its key on the
    UI side, but the worker keeps sending the key it persisted — so it 401s
    forever, on a host whose containers are still running and still earning.
    Nothing on either side says why: the UI shows one fewer worker, the worker
    logs a bare 401. The documented recovery ("remove it and the shared key is
    accepted again") could not work, and the real fix was SSHing in to delete a
    file that is documented nowhere.

    Bounded on purpose. Discarding after a single failure would re-enrol on any
    transient blip and widen the window in which the shared key is accepted; it
    takes sustained rejection, which is what a deleted row actually looks like.
    """
    global _worker_key, _consecutive_auth_failures
    try:
        _WORKER_KEY_FILE.unlink(missing_ok=True)
    except OSError as exc:
        logger.error(
            "Could not remove the stale per-worker key at %s: %s. Delete it by hand "
            "and restart this container to re-enrol.",
            _WORKER_KEY_FILE,
            exc,
        )
        return
    _worker_key = None
    _consecutive_auth_failures = 0
    logger.warning(
        "Discarded this worker's per-worker key (%s). Re-enrolling with the shared key on the next heartbeat.",
        reason,
    )


_worker_key: str | None = _load_worker_key()


# Stable per-worker identity. The UI keys a worker's DB row (and its per-worker key) on
# this client_id, NOT on the mutable display name: two hosts sharing a default hostname
# (ubuntu/raspberrypi/docker-desktop) must not collapse onto one identity, and renaming
# CASHPILOT_WORKER_NAME must not mint a new identity that locks the worker out.
_WORKER_ID_FILE = Path(os.getenv("CASHPILOT_DATA_DIR", "/data")) / ".worker_id"


_DOCKER_CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def _name_is_ephemeral(name: str) -> bool:
    """True when WORKER_NAME is really a Docker-assigned container ID.

    Docker defaults a container's hostname to the first 12 hex characters of its
    ID, and that ID changes every time the container is recreated -- which is
    exactly what an image bump does. Treating such a name as a durable identity
    mints a new client_id on every upgrade; the UI then sees a still-valid
    per-worker key arriving from an unknown client and correctly refuses it, so
    every heartbeat 401s while the service containers keep earning. The outage
    is silent. Observed in production upgrading 1.0.0 -> 1.4.1.

    A real host name (bare metal, a VM, or an explicit `hostname:`/
    CASHPILOT_WORKER_NAME) stays stable across restarts and remains a perfectly
    good identity, so only the container-ID shape is rejected, and only when we
    are actually inside a container.
    """
    return bool(_DOCKER_CONTAINER_ID_RE.match(name)) and Path("/.dockerenv").exists()


def _load_or_create_client_id() -> str:
    """Return this worker's stable client_id, generating and persisting one on first run.

    Migration: a worker already enrolled under the pre-client_id scheme has a persisted
    per-worker key but no id file. It keeps the identity the UI already knows it by --
    its WORKER_NAME -- so upgrading never orphans its row. The one exception is a name
    that is really a Docker container ID: that is regenerated on every recreate, so
    reusing it would mint a new identity and lock the worker out (see _name_is_ephemeral).
    A brand-new worker gets a random id.
    """
    try:
        existing = _WORKER_ID_FILE.read_text().strip()
        if existing:
            return existing
    except OSError:
        pass
    if _worker_key and not _name_is_ephemeral(WORKER_NAME):
        cid = WORKER_NAME
    else:
        cid = uuid.uuid4().hex
        if _worker_key:
            # Enrolled already, but our only clue to which row is ours was an
            # ephemeral container ID. This is NOT recoverable by re-enrolling:
            # we still send our own per-worker key (see _active_key), and the UI
            # refuses it under an id it never enrolled, so every heartbeat 401s
            # until the id is restored by hand. Say exactly that -- the symptom
            # is otherwise very hard to trace back to this decision.
            logger.error(
                "This worker holds a per-worker key but no persisted client_id, and its "
                "name (%s) is a container ID that changes on every recreate. Heartbeats "
                "will be REJECTED (401) under the generated id %s, because we authenticate "
                "with our existing key and the UI does not know that id. To recover: stop "
                "this container, write the client_id the UI lists for this worker into %s, "
                "start it again, and set CASHPILOT_WORKER_NAME so this cannot recur.",
                WORKER_NAME,
                cid,
                _WORKER_ID_FILE,
            )
    try:
        _WORKER_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
        _WORKER_ID_FILE.write_text(cid)
        _WORKER_ID_FILE.chmod(0o600)
    except OSError as exc:
        logger.warning("Could not persist worker client_id — using in-memory id: %s", exc)
    return cid


CLIENT_ID: str = _load_or_create_client_id()


def _active_key() -> str:
    """The key we authenticate with: our own once enrolled, else the shared key."""
    return _worker_key or API_KEY


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _verify_api_key(request: Request) -> None:
    """Verify an inbound UI->worker call.

    Once enrolled we require OUR OWN per-worker key; the shared bootstrap key is
    rejected (the cutover). Before enrollment we accept the shared key so the UI
    can reach us to enroll in the first place.
    """
    expected = _active_key()
    if not expected:
        raise HTTPException(status_code=503, detail="Fleet key not configured")
    auth = request.headers.get("Authorization", "")
    if not hmac.compare_digest(auth.encode(), f"Bearer {expected}".encode()):
        raise HTTPException(status_code=401, detail="Invalid API key")


# ---------------------------------------------------------------------------
# Heartbeat loop
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Egress identity (CashPilot-5qc)
# ---------------------------------------------------------------------------

# Every provider in the catalog caps per IP address, so the UI cannot warn about
# two workers behind one connection unless each worker knows its own exit.
#
# This is the one outbound call CashPilot makes purely to learn about the user,
# so it is opt-outable and endpoint-overridable. The privacy cost is genuinely
# small — a worker's whole purpose is to route traffic for these providers, all
# of whom already see this address — but "small" is not "none", and defaults
# that quietly phone somewhere are how trust is lost in this category.
_EGRESS_ENDPOINTS = ("https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com")

# Local, network-free hosting hint. Read from DMI rather than an ASN lookup so
# nothing is disclosed to a third party and it still works offline.
_DMI_PATHS = ("/sys/class/dmi/id/sys_vendor", "/sys/class/dmi/id/product_name", "/sys/class/dmi/id/chassis_vendor")

_egress_cache: tuple[str | None, float] = (None, 0.0)
_EGRESS_TTL_SECONDS = 3600.0
# A failed lookup is cached too, and briefly. Without it a blackholed network
# (DROP, not REJECT) costs the full timeout on EVERY heartbeat, forever.
_EGRESS_FAILURE_TTL_SECONDS = 300.0
# Wall-clock budget for the WHOLE attempt, shared across every endpoint tried
# (see the deadline in _detect_egress_ip). Per-endpoint would multiply by the
# endpoint count: at 3 endpoints plus the 15s heartbeat POST that is already 45s
# on a 60s serial cycle, and a longer list would breach the 180s offline
# threshold — the exact failure this bound exists to prevent. httpx's timeout is PER
# OPERATION — its read timeout is the maximum gap between chunks, not a deadline
# — so an endpoint dribbling one byte every few seconds would hold the request
# open indefinitely. That matters here because the heartbeat loop is serial: a
# stalled lookup stops heartbeats entirely and the UI marks this worker offline
# after 180s, so deploys and restarts for this host start failing. A diagnostic
# nicety must never be able to take the control plane down.
_EGRESS_TOTAL_TIMEOUT = 10.0
# Enough for any textual IP form; the body is never read past this.
_EGRESS_MAX_BYTES = 128
_EGRESS_CONFIG_DIR = Path(os.getenv("CASHPILOT_DATA_DIR", "/data")) / "egress"
_EGRESS_CONFIG_FILE = _EGRESS_CONFIG_DIR / "sing-box.json"
_RUNTIME_ASSET_DIR = Path(os.getenv("CASHPILOT_DATA_DIR", "/data")) / "runtime-assets"


def _public_ip_slots_path() -> Path:
    configured = os.getenv("CASHPILOT_PUBLIC_IP_SLOTS_FILE", "").strip()
    if configured:
        return Path(configured)
    # The canonical one-command VPS installer mounts only the worker's /data
    # volume.  The host bootstrap mirrors the state file there; standard Compose
    # files may still opt into the dedicated read-only /network mount.
    persistent = Path(os.getenv("CASHPILOT_DATA_DIR", "/data")) / "public-ip-slots.json"
    if persistent.exists():
        return persistent
    return Path("/etc/cashpilot/public-ip-slots.json")


def _load_public_ip_slots() -> list[dict[str, Any]]:
    """Read bootstrap-owned routing slots without mutating host networking."""
    return public_ip_slots.load_slots(_public_ip_slots_path())


def _nkn_state_dir() -> Path:
    return Path(os.getenv("CASHPILOT_DATA_DIR", "/data")) / "nkn-wallets"


def _nkn_state_path(slot_id: str) -> Path:
    match = re.fullmatch(r"ipv4-(\d{3,6})", str(slot_id or ""))
    if match is None:
        raise ValueError("invalid NKN slot id")
    # Resolve and confine the generated name before any filesystem access. The
    # route value originates at an HTTP boundary, so validation alone must not
    # be the only protection against path traversal or symlinked state roots.
    canonical_slot_id = match.group(0)
    root = os.path.realpath(os.fspath(_nkn_state_dir()))
    path = os.path.realpath(os.path.join(root, f"{canonical_slot_id}.json"))
    if not path.startswith(root + os.sep):
        raise ValueError("invalid NKN state path")
    return Path(path)


def _save_nkn_wallet_state(slot_id: str, state: dict[str, Any]) -> None:
    """Persist redacted assignment/runtime state; never write wallet secrets."""
    payload = dict(state)
    for secret in ("wallet_json", "wallet_pswd", "raw_wallet", "password"):
        payload.pop(secret, None)
    path = _nkn_state_path(slot_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def _load_nkn_states() -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []
    directory = _nkn_state_dir()
    try:
        paths = sorted(directory.glob("ipv4-*.json"))
    except OSError:
        return states
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            for secret in ("wallet_json", "wallet_pswd", "raw_wallet", "password"):
                value.pop(secret, None)
            states.append(value)
    return states


def _earnapp_state_dir() -> Path:
    return Path(os.getenv("CASHPILOT_DATA_DIR", "/data")) / "earnapp-nodes"


def _earnapp_state_path(logical_node_id: str) -> Path:
    node_id = str(logical_node_id or "").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,120}", node_id):
        raise ValueError("invalid EarnApp logical node id")
    root = os.path.realpath(os.fspath(_earnapp_state_dir()))
    path = os.path.realpath(os.path.join(root, f"{node_id}.json"))
    if not path.startswith(root + os.sep):
        raise ValueError("invalid EarnApp state path")
    return Path(path)


def _save_earnapp_state(logical_node_id: str, state: dict[str, Any]) -> None:
    """Persist only redacted lease/runtime identity for heartbeat recovery."""
    payload = earnapp_runtime.redacted_evidence(dict(state))
    payload["logical_node_id"] = str(logical_node_id or "").strip()
    path = _earnapp_state_path(logical_node_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def _earnapp_hydration_state_token(value: dict[str, Any]) -> dict[str, Any]:
    """Normalize the non-secret local fields used by the hydration CAS."""

    def integer(field: str) -> int:
        try:
            return int(value.get(field) or 0)
        except (TypeError, ValueError):
            return 0

    return {
        "proxy_id": integer("proxy_id"),
        "platform": str(value.get("platform") or "unknown").strip().lower() or "unknown",
        "runtime_backend": str(value.get("runtime_backend") or "docker").strip().lower() or "docker",
        "expected_egress_ip": str(value.get("expected_egress_ip") or "").strip(),
        "pending_binding_version": str(value.get("pending_binding_version") or "").strip(),
        "pending_proxy_id": integer("pending_proxy_id"),
        "pending_expected_egress_ip": str(value.get("pending_expected_egress_ip") or "").strip(),
    }


def _load_earnapp_states() -> list[dict[str, Any]]:
    try:
        paths = sorted(_earnapp_state_dir().glob("*.json"))
    except OSError:
        return []
    states: list[dict[str, Any]] = []
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            states.append(earnapp_runtime.redacted_evidence(value))
    return states


def _remove_earnapp_state(logical_node_id: str) -> None:
    """Remove only one canary's local heartbeat marker after a confirmed remove."""
    if earnapp_policy.is_protected_runtime_reference(logical_node_id):
        raise ValueError("protected EarnApp node is inspection-only")
    path = _earnapp_state_path(logical_node_id)
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


def _hydrate_earnapp_state_from_assignment(assignment: dict[str, Any]) -> bool:
    """Backfill durable fields for a legacy runtime without recreating it.

    Older workers persisted only the container/device marker.  The server's
    authenticated heartbeat response is authoritative for the missing lease
    and platform fields, so hydrate only when identity and generation match.
    """
    if not isinstance(assignment, dict) or assignment.get("hydrate_state") is not True:
        return False
    logical_node_id = str(assignment.get("logical_node_id") or "").strip()
    if not logical_node_id:
        return False
    try:
        path = _earnapp_state_path(logical_node_id)
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(state, dict):
        return False
    try:
        state_generation = int(state.get("generation") or 0)
        assignment_generation = int(assignment.get("generation") or 0)
        proxy_id = int(assignment.get("proxy_id") or 0)
    except (TypeError, ValueError):
        return False
    if state_generation != assignment_generation:
        return False
    if str(state.get("device_id") or "") != str(assignment.get("device_id") or ""):
        return False
    expected_token = assignment.get("hydrate_expected")
    if not isinstance(expected_token, dict) or _earnapp_hydration_state_token(state) != _earnapp_hydration_state_token(
        expected_token
    ):
        return False
    platform = str(assignment.get("platform") or "").strip().lower()
    expected = str(assignment.get("expected_egress_ip") or "").strip()
    backend = str(assignment.get("runtime_backend") or "docker").strip().lower()
    if proxy_id <= 0 or not expected or platform not in {"macos", "ios", "ubuntu"} or backend not in {"docker", "lxd"}:
        return False
    # MacOS/iOS are Docker-only. Ubuntu accepts either backend so legacy LXD
    # state remains recoverable while new assignments can use Docker.
    if platform in {"macos", "ios"} and backend != "docker":
        return False
    state.update(
        proxy_id=proxy_id,
        platform=platform,
        runtime_backend=backend,
        expected_egress_ip=expected,
    )
    _save_earnapp_state(logical_node_id, state)
    return True


def _earnapp_provider_state(containers: list[dict[str, Any]]) -> dict[str, Any] | None:
    states = _load_earnapp_states()
    if not states:
        return None
    by_instance = {
        str(item.get("instance_slug") or item.get("name") or ""): item for item in containers if isinstance(item, dict)
    }
    instances: list[dict[str, Any]] = []
    for state in states:
        logical_node_id = str(state.get("logical_node_id") or "")
        runtime = by_instance.get(logical_node_id, {})
        if str(state.get("runtime_backend") or "docker") == "lxd":
            evidence = earnapp_runtime.redacted_evidence(state.get("evidence") or {})
        else:
            evidence = earnapp_runtime.redacted_evidence(
                runtime.get("provider_evidence") or state.get("evidence") or {}
            )
        instances.append(
            {
                "logical_node_id": logical_node_id,
                "generation": int(state.get("generation") or 0),
                "device_id": str(state.get("device_id") or ""),
                "platform": str(state.get("platform") or "unknown"),
                "runtime_backend": str(state.get("runtime_backend") or "docker"),
                "proxy_id": int(state.get("proxy_id") or 0),
                "expected_egress_ip": str(state.get("expected_egress_ip") or ""),
                "proxy_health": str(state.get("proxy_health") or "unknown"),
                "observed_egress_ip": str(state.get("observed_egress_ip") or ""),
                "proxy_health_reason": str(state.get("proxy_health_reason") or ""),
                "pending_binding_version": str(state.get("pending_binding_version") or ""),
                "pending_proxy_id": int(state.get("pending_proxy_id") or 0),
                "pending_expected_egress_ip": str(state.get("pending_expected_egress_ip") or ""),
                "pending_observed_egress_ip": str(state.get("pending_observed_egress_ip") or ""),
                "runtime_status": str(runtime.get("status") or state.get("runtime_status") or "unknown"),
                "evidence": evidence,
            }
        )
    online = sum(1 for item in instances if item["evidence"].get("online") is True)
    return {"instances": instances, "online": online, "offline": len(instances) - online}


async def _refresh_earnapp_lxd_evidence() -> None:
    """Backward-compatible wrapper for the all-backend runtime evidence pass."""
    await _refresh_earnapp_runtime_evidence()


async def _refresh_earnapp_runtime_evidence() -> None:
    """Probe each EarnApp node in its own namespace and persist scoped health."""
    states = _load_earnapp_states()
    semaphore = asyncio.Semaphore(8)

    async def refresh(state: dict[str, Any]) -> None:
        logical_node_id = str(state.get("logical_node_id") or "").strip()
        if not logical_node_id:
            return
        mutation_lock = _earnapp_node_mutation_lock(logical_node_id)
        if mutation_lock.locked():
            return
        async with mutation_lock:
            # The inventory snapshot can predate a proxy apply that was already
            # waiting on Docker. Reload after acquiring the same node lock so a
            # heartbeat cannot erase its journal or recreated container ID.
            try:
                state = _earnapp_node_state(logical_node_id)
            except HTTPException:
                return
            backend = str(state.get("runtime_backend") or "docker").strip().lower()
            generation = int(state.get("generation") or 0)
            device_id = str(state.get("device_id") or "")
            try:
                async with semaphore:
                    if backend == "lxd":
                        evidence = await asyncio.wait_for(
                            asyncio.to_thread(
                                earnapp_lxd_runtime.node_evidence,
                                logical_node_id,
                                generation=generation,
                                device_id=device_id,
                            ),
                            timeout=20,
                        )
                    else:
                        evidence = await asyncio.wait_for(
                            asyncio.to_thread(orchestrator.probe_service_egress, logical_node_id),
                            timeout=20,
                        )
            except (TimeoutError, ValueError, RuntimeError, OSError):
                # An inspection failure is inconclusive; never rotate on it alone.
                state["proxy_health"] = "unknown"
                state["proxy_health_reason"] = "runtime_probe_unavailable"
                _save_earnapp_state(logical_node_id, state)
                return

            evidence = earnapp_runtime.redacted_evidence(evidence)
            running = evidence.get("running") is True
            observed = str(evidence.get("observed_egress_ip") or "").strip()
            expected = str(state.get("expected_egress_ip") or "").strip()
            probe_ok = evidence.get("probe_ok") is True
            pending_version = str(state.get("pending_binding_version") or "").strip()
            if pending_version:
                pending_expected = str(state.get("pending_expected_egress_ip") or "").strip()
                state["pending_observed_egress_ip"] = observed if probe_ok and observed == pending_expected else ""
                health, reason = "unknown", "proxy_binding_pending"
            elif not running:
                health, reason = "unknown", "runtime_stopped"
            elif not probe_ok or not observed:
                health, reason = "unhealthy", "proxy_probe_failed"
            elif expected and observed != expected:
                health, reason = "unhealthy", "egress_mismatch"
            else:
                health, reason = "healthy", ""
            state["runtime_status"] = "running" if running else "stopped"
            state["observed_egress_ip"] = observed
            state["proxy_health"] = health
            state["proxy_health_reason"] = reason
            state["evidence"] = evidence
            _save_earnapp_state(logical_node_id, state)

    await asyncio.gather(*(refresh(state) for state in states))


def _nkn_assignment_identity(state: dict[str, Any]) -> tuple[str, int, int, str] | None:
    slot_id = str(state.get("slot_id") or "")
    wallet_id = int(state.get("wallet_id") or 0)
    assignment_version = int(state.get("wallet_assignment_version") or 0)
    lease_client_id = str(state.get("lease_client_id") or "")
    if not re.fullmatch(r"ipv4-\d{3,6}", slot_id) or wallet_id <= 0 or assignment_version <= 0 or not lease_client_id:
        return None
    return slot_id, wallet_id, assignment_version, lease_client_id


def _same_nkn_identity(state: dict[str, Any], item: dict[str, Any]) -> bool:
    identity = _nkn_assignment_identity(state)
    return identity is not None and identity == (
        str(item.get("slot_id") or ""),
        int(item.get("wallet_id") or 0),
        int(item.get("wallet_assignment_version") or 0),
        str(item.get("lease_client_id") or ""),
    )


async def _reconcile_nkn_assignment_acks(
    acknowledgements: list[dict[str, Any]], *, acknowledged_at: float | None = None
) -> None:
    """Refresh local lease deadlines and resume only the exact ACKed assignment."""
    ack_time = time.time() if acknowledged_at is None else float(acknowledged_at)
    for item in acknowledgements:
        if not isinstance(item, dict):
            continue
        slot_id = str(item.get("slot_id") or "")
        try:
            path = _nkn_state_path(slot_id)
            state = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or not _same_nkn_identity(state, item):
                continue
            if state.get("lease_guard_suspended") is True:
                identity = _nkn_assignment_identity(state)
                if identity is None:
                    continue
                _, wallet_id, assignment_version, lease_client_id = identity
                if str(state.get("runtime_backend") or "docker") == "lxd":
                    await asyncio.to_thread(
                        nkn_lxd_runtime.resume_slot,
                        slot_id,
                        wallet_id=wallet_id,
                        wallet_assignment_version=assignment_version,
                        lease_client_id=lease_client_id,
                    )
                else:
                    client = await asyncio.to_thread(orchestrator._get_client)
                    try:
                        await asyncio.to_thread(
                            nkn_runtime.resume_slot,
                            slot_id,
                            wallet_id=wallet_id,
                            wallet_assignment_version=assignment_version,
                            lease_client_id=lease_client_id,
                            client=client,
                        )
                    finally:
                        with contextlib.suppress(Exception):
                            await asyncio.to_thread(client.close)
            state["last_server_ack_at"] = ack_time
            state["lease_guard_suspended"] = False
            state["runtime_status"] = "running"
            _save_nkn_wallet_state(slot_id, state)
        except Exception as exc:  # noqa: BLE001 - retry on the next successful heartbeat
            logger.warning("Could not apply NKN lease ACK for slot %s: %s", slot_id, type(exc).__name__)


async def _enforce_nkn_lease_guard(*, now: float | None = None) -> None:
    """Fail closed after the local 14-minute ACK deadline, preserving identity."""
    current = time.time() if now is None else float(now)
    for state in _load_nkn_states():
        identity = _nkn_assignment_identity(state)
        if identity is None:
            continue
        last_ack = float(state.get("last_server_ack_at") or 0)
        if last_ack <= 0:
            # A pre-guard state has no proof of a successful server round-trip.
            # Stop it fail-closed; the next valid ACK resumes it immediately.
            last_ack = 0
        if state.get("lease_guard_suspended") is not True and current - last_ack < NKN_LEASE_GUARD_SECONDS:
            continue
        slot_id, wallet_id, assignment_version, lease_client_id = identity
        try:
            if str(state.get("runtime_backend") or "docker") == "lxd":
                await asyncio.to_thread(
                    nkn_lxd_runtime.suspend_slot,
                    slot_id,
                    wallet_id=wallet_id,
                    wallet_assignment_version=assignment_version,
                    lease_client_id=lease_client_id,
                )
            else:
                client = await asyncio.to_thread(orchestrator._get_client)
                try:
                    await asyncio.to_thread(
                        nkn_runtime.suspend_slot,
                        slot_id,
                        wallet_id=wallet_id,
                        wallet_assignment_version=assignment_version,
                        lease_client_id=lease_client_id,
                        client=client,
                    )
                finally:
                    with contextlib.suppress(Exception):
                        await asyncio.to_thread(client.close)
            state["lease_guard_suspended"] = True
            state["runtime_status"] = "lease_guard_suspended"
            evidence = dict(state.get("evidence") or {})
            evidence.update({"running": False, "online": False, "lease_guard_suspended": True})
            state["evidence"] = evidence
            _save_nkn_wallet_state(slot_id, state)
            logger.warning("Suspended NKN slot %s after the 14-minute lease ACK deadline", slot_id)
        except Exception as exc:  # noqa: BLE001 - retry each heartbeat until safely stopped
            logger.warning("Could not suspend stale NKN slot %s: %s", slot_id, type(exc).__name__)


async def _reconcile_nkn_assignment_rejections(rejections: list[dict[str, Any]]) -> None:
    """Remove local NKN state whose server lease was reclaimed or reassigned.

    The runtime checks Docker labels before deleting anything, so a new local
    assignment can never be removed by a stale heartbeat response.
    """
    for item in rejections:
        if not isinstance(item, dict):
            continue
        slot_id = str(item.get("slot_id") or "")
        try:
            path = _nkn_state_path(slot_id)
            state = json.loads(path.read_text(encoding="utf-8"))
            if (
                int(state.get("wallet_id") or 0) != int(item.get("wallet_id") or 0)
                or int(state.get("wallet_assignment_version") or 0) != int(item.get("wallet_assignment_version") or 0)
                or str(state.get("lease_client_id") or "") != str(item.get("lease_client_id") or "")
            ):
                continue
            wallet_id = int(item.get("wallet_id") or 0)
            assignment_version = int(item.get("wallet_assignment_version") or 0)
            lease_client_id = str(item.get("lease_client_id") or "")
            if str(state.get("runtime_backend") or "docker") == "lxd":
                await asyncio.to_thread(
                    nkn_lxd_runtime.remove_slot,
                    slot_id,
                    wallet_id=wallet_id,
                    wallet_assignment_version=assignment_version,
                    lease_client_id=lease_client_id,
                    delete_volume=True,
                )
            else:
                client = await asyncio.to_thread(orchestrator._get_client)
                try:
                    await asyncio.to_thread(
                        nkn_runtime.remove_slot,
                        slot_id,
                        wallet_id=wallet_id,
                        wallet_assignment_version=assignment_version,
                        lease_client_id=lease_client_id,
                        client=client,
                        delete_volume=True,
                    )
                finally:
                    with contextlib.suppress(Exception):
                        await asyncio.to_thread(client.close)
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
        except Exception as exc:  # noqa: BLE001 - retry on the next heartbeat
            logger.warning("Could not reconcile stale NKN slot %s: %s", slot_id, type(exc).__name__)


async def _nkn_provider_state() -> dict[str, Any] | None:
    states = _load_nkn_states()
    if not states:
        return None
    has_docker_state = any(str(state.get("runtime_backend") or "docker") != "lxd" for state in states)
    try:
        containers = await asyncio.to_thread(orchestrator.get_status) if has_docker_state else []
    except Exception as exc:  # noqa: BLE001 - heartbeat must remain alive
        logger.debug("NKN container evidence unavailable: %s", exc)
        containers = []
    docker_client = None
    if has_docker_state:
        try:
            docker_client = await asyncio.to_thread(orchestrator._get_client)
        except Exception:  # noqa: BLE001 - evidence is best effort
            docker_client = None
    by_instance = {str(item.get("instance_id") or ""): item for item in containers if isinstance(item, dict)}
    instances: list[dict[str, Any]] = []
    try:
        for state in states:
            item = dict(state)
            instance_id = str(item.get("instance_id") or "")
            runtime = by_instance.get(instance_id) or next(
                (
                    candidate
                    for candidate in containers
                    if isinstance(candidate, dict)
                    and str(candidate.get("instance_slug") or candidate.get("name") or "") == instance_id
                ),
                {},
            )
            item["runtime_status"] = str(runtime.get("status") or item.get("runtime_status") or "unknown")
            item["evidence"] = dict(item.get("evidence") or {})
            if str(item.get("runtime_backend") or "docker") == "lxd":
                try:
                    item["evidence"] = await asyncio.to_thread(nkn_lxd_runtime.node_evidence, item)
                    item["runtime_status"] = "running" if item["evidence"].get("running") is True else "stopped"
                    if item["evidence"].get("node_id"):
                        item["node_identity"] = str(item["evidence"]["node_id"])
                except Exception:  # noqa: BLE001 - a missing helper is offline evidence
                    item["evidence"] = {"running": False, "online": False, "runtime_backend": "lxd"}
                    item["runtime_status"] = "unknown"
                instances.append(item)
                continue
            container = None
            if docker_client is not None and instance_id:
                try:
                    container = await asyncio.to_thread(docker_client.containers.get, instance_id)
                except Exception:  # noqa: BLE001 - a missing container is offline evidence
                    container = None
            if container is not None:
                with contextlib.suppress(Exception):
                    item["evidence"] = nkn_runtime.node_evidence(container)
                item["container_id"] = str(getattr(container, "id", "") or item.get("container_id") or "")
            item["evidence"].setdefault("running", item["runtime_status"] == "running")
            instances.append(item)
    finally:
        if docker_client is not None:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(docker_client.close)
    online = sum(1 for item in instances if item.get("evidence", {}).get("online") is True)
    return {"instances": instances, "online": online, "offline": len(instances) - online}


def _docker_host_path(path: Path) -> Path:
    """Translate this worker's /data path to the host path Docker will mount.

    The worker writes runtime assets inside its own /data. Docker bind mounts are
    resolved by the host daemon, not by this container, so passing /data/... makes
    the provider see an empty host directory. For the normal named-volume setup,
    use this container's /data mountpoint on the host.
    """
    raw_path = str(path).replace("\\", "/")
    data_dir_raw = os.getenv("CASHPILOT_DATA_DIR", "/data").rstrip("/")
    try:
        if raw_path != data_dir_raw and not raw_path.startswith(data_dir_raw + "/"):
            return path
        rel = raw_path[len(data_dir_raw) :].lstrip("/")
    except Exception:
        return path
    try:
        client = orchestrator._get_client()
        self_id = os.getenv("HOSTNAME", "")
        container = client.containers.get(self_id)
        for mount in container.attrs.get("Mounts", []):
            if str(mount.get("Destination", "")).rstrip("/") == data_dir_raw:
                source = mount.get("Source")
                if source:
                    return Path(source) / rel
    except Exception as exc:
        logger.warning("Could not resolve host path for runtime asset %s: %s", path, exc)
    return path


def _myst_state_path() -> Path:
    return Path(os.getenv("CASHPILOT_DATA_DIR", "/data")) / "myst-wallet.json"


def _save_myst_wallet_state(state: dict[str, Any]) -> None:
    payload = dict(state)
    payload.pop("myst_wallet_raw", None)
    path = _myst_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _load_myst_wallet_state() -> dict[str, Any] | None:
    path = _myst_state_path()
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except OSError:
        return None


async def _sync_myst_wallet_after_deploy(deploy_credentials: dict[str, Any], container_id: str) -> None:
    wallet_id = int(deploy_credentials.get("myst_wallet_id") or 0)
    client_id = str(deploy_credentials.get("myst_wallet_client_id") or CLIENT_ID)
    wallet_address = str(deploy_credentials.get("myst_wallet_address") or "")
    if not wallet_address and deploy_credentials.get("myst_wallet_raw"):
        with contextlib.suppress(ValueError):
            wallet_address = myst_runtime.wallet_address(str(deploy_credentials.get("myst_wallet_raw") or ""))
    if not wallet_id or not client_id:
        return
    state = {
        "myst_wallet_id": wallet_id,
        "myst_wallet_client_id": client_id,
        "myst_wallet_assignment_version": int(deploy_credentials.get("myst_wallet_assignment_version") or 0),
        "myst_node_identity": str(deploy_credentials.get("myst_node_identity") or ""),
        "myst_wallet_address": wallet_address,
        "container_id": container_id,
    }
    if container_id and wallet_address:
        try:
            status = await asyncio.to_thread(
                myst_runtime.registration_status,
                orchestrator._find_container("mysterium"),
                wallet_address,
            )
        except Exception:
            status = ""
        if status:
            state["myst_registration_status"] = status
    _save_myst_wallet_state(state)


async def _myst_provider_state() -> dict[str, Any] | None:
    state = _load_myst_wallet_state()
    if not state:
        return None
    wallet_id = int(state.get("myst_wallet_id") or 0)
    client_id = str(state.get("myst_wallet_client_id") or "")
    wallet_address = str(state.get("myst_wallet_address") or "")
    if not wallet_id or not client_id:
        return None
    registration_status = str(state.get("myst_registration_status") or "")
    container_id = str(state.get("container_id") or "")
    if not registration_status and container_id:
        try:
            status = await asyncio.to_thread(
                myst_runtime.registration_status,
                orchestrator._find_container("mysterium"),
                wallet_address,
            )
        except Exception:
            status = ""
        if status:
            registration_status = status
    return {
        "wallet_id": wallet_id,
        "lease_client_id": client_id,
        "wallet_assignment_version": int(state.get("myst_wallet_assignment_version") or 0),
        "wallet_address": wallet_address,
        "node_identity": str(state.get("myst_node_identity") or wallet_address),
        "public_ip": str(state.get("myst_public_ip") or state.get("myst_wallet_public_ip") or ""),
        "runtime_status": "running",
        "evidence": {
            "container_id": state.get("container_id", ""),
            "source": "heartbeat",
            **(
                {"public_ip": str(state.get("myst_public_ip") or state.get("myst_wallet_public_ip") or "")}
                if str(state.get("myst_public_ip") or state.get("myst_wallet_public_ip") or "")
                else {}
            ),
            **({"registration_status": registration_status} if registration_status else {}),
        },
    }


async def _release_myst_wallet_state(reason: str) -> None:
    state = _load_myst_wallet_state()
    if not state:
        return
    wallet_id = int(state.get("myst_wallet_id") or 0)
    client_id = str(state.get("myst_wallet_client_id") or "")
    if not wallet_id or not client_id:
        return
    with contextlib.suppress(OSError):
        _myst_state_path().unlink()


def _disk_usage() -> dict[str, Any] | None:
    """Free and total bytes on the filesystem holding the data directory.

    Storj is paid for data it STORES, so free space is earning capacity, not a
    housekeeping detail -- a node that quietly fills up stops growing and nothing
    in CashPilot said so.

    Returns None when it cannot be read. None is UNKNOWN; a caller must not
    render it as 0 (a full disk) or as 100% (an empty one). Both are worse than
    an em-dash.
    """
    try:
        usage = shutil.disk_usage(str(_WORKER_ID_FILE.parent))
    except OSError as exc:
        logger.debug("Could not read disk usage: %s", exc)
        return None
    return {"path": str(_WORKER_ID_FILE.parent), "free_bytes": usage.free, "total_bytes": usage.total}


def _gpu_info() -> dict[str, Any]:
    """What this worker can see of a GPU, and how sure it is.

    Salad, Nosana, io.net and Vast.ai only earn when a real GPU is present AND
    usable. Today a GPU service that is running but idle -- because the device
    was never passed into the container -- looks exactly like one that is
    earning. That is the Mysterium /dev/net/tun failure again: healthy-looking
    and worth nothing.

    THE THREE-VALUED PART MATTERS. Inside a container with no device passed
    through, the absence of nvidia-smi proves nothing about the HOST. So:

        available True   we saw a device
        available False  we looked, found none, and we are NOT in a container,
                         so the host really has none
        available None   we could not tell -- in a container with nothing passed
                         through, which is exactly when a user most needs to know

    Reporting None as False would tell someone their machine has no GPU when it
    may have an unused one, which is the opposite of the useful answer.
    """
    devices: list[str] = []
    how = None

    nvidia = shutil.which("nvidia-smi")
    if nvidia:
        try:
            out = subprocess.run(  # noqa: S603 - fixed binary, no shell, no user input
                [nvidia, "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if out.returncode == 0:
                devices = [line.strip() for line in out.stdout.splitlines() if line.strip()]
                how = "nvidia-smi"
        except (OSError, subprocess.SubprocessError) as exc:
            logger.debug("nvidia-smi failed: %s", exc)

    if not devices:
        # A DRM render node means SOME GPU is reachable -- integrated, AMD, or an
        # NVIDIA card without the management tool. Enough to say "yes", not
        # enough to name it.
        render_nodes = sorted(str(p) for p in Path("/dev/dri").glob("renderD*")) if Path("/dev/dri").is_dir() else []
        if render_nodes:
            devices = [f"DRM render node ({len(render_nodes)})"]
            how = "drm"

    if devices:
        return {"available": True, "devices": devices, "detected_by": how}

    # Both probes above are LINUX-specific: nvidia-smi is not on a stock macOS,
    # and /dev/dri is the Linux DRM interface. Their absence on any other
    # platform proves nothing at all -- every Mac has a GPU. Caught by running
    # this on macOS, where the first version confidently reported "no GPU".
    if platform.system() != "Linux":
        return {
            "available": None,
            "devices": [],
            "detected_by": None,
            "reason": f"GPU detection is not implemented for {platform.system()}; this says nothing about whether one exists",
        }

    if Path("/.dockerenv").exists():
        # On Linux, in a container, with nothing passed through. We genuinely
        # cannot tell -- and this is exactly when a user most needs to know,
        # because it is the case where a GPU service runs and earns nothing.
        return {
            "available": None,
            "devices": [],
            "detected_by": None,
            "reason": "no GPU is visible from inside this container; the host may still have one that was not passed through",
        }

    # Linux, on the host, with no NVIDIA tool and no render node. This is the
    # one case where "no" is a real answer.
    return {"available": False, "devices": [], "detected_by": None}


def _detect_network_type() -> str:
    """residential / hosting / unknown, from local hardware identifiers only.

    An explicit ``CASHPILOT_WORKER_NETWORK`` always wins: the user knows their
    own connection better than any heuristic, and a wrong "hosting" verdict
    fires ban warnings at people who are fine.
    """
    declared = egress.normalise_network_type(os.getenv("CASHPILOT_WORKER_NETWORK"))
    if declared != egress.UNKNOWN:
        return declared
    for path in _DMI_PATHS:
        try:
            vendor = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        detected = egress.classify_vendor(vendor)
        if detected != egress.UNKNOWN:
            return detected
    return egress.UNKNOWN


async def _fetch_egress_ip(url: str) -> str | None:
    """One IP-echo request, with the response body capped while streaming."""
    async with httpx.AsyncClient(timeout=5) as client, client.stream("GET", url) as resp:
        if resp.status_code != 200:
            return None
        body = b""
        async for chunk in resp.aiter_bytes():
            body += chunk
            if len(body) >= _EGRESS_MAX_BYTES:
                break
    return egress.public_ip(body[:_EGRESS_MAX_BYTES].decode("utf-8", "replace").strip())


async def _detect_egress_ip() -> str | None:
    """This worker's public IP, cached for an hour, or None.

    Every failure mode returns None rather than a guess: a wrong address would
    group unrelated machines together, which is worse than the fleet view simply
    saying it does not know.
    """
    global _egress_cache

    if os.getenv("CASHPILOT_EGRESS_DETECT", "").strip().lower() in {"0", "off", "false", "no"}:
        return None

    cached, fetched_at = _egress_cache
    # time.monotonic(), not the event loop's clock: the loop's epoch is
    # unspecified, and one starting near zero would make this difference
    # negative — always under the TTL — pinning a stale address forever.
    now = time.monotonic()
    age = now - fetched_at
    if cached and age < _EGRESS_TTL_SECONDS:
        return cached
    if not cached and fetched_at and age < _EGRESS_FAILURE_TTL_SECONDS:
        return None

    override = os.getenv("CASHPILOT_EGRESS_IP", "").strip()
    if override:
        # A user behind a proxy or split tunnel can state the truth directly.
        confirmed = egress.public_ip(override)
        if confirmed:
            _egress_cache = (confirmed, now)
            return confirmed
        # Ignoring this silently would be cruel: "192.168.1.5" is what most
        # people would call their IP, and the only symptom is nothing happening.
        logger.warning(
            "CASHPILOT_EGRESS_IP=%r is not a public address, so it cannot be this worker's "
            "egress IP — ignoring it and looking the address up instead.",
            override,
        )

    custom = os.getenv("CASHPILOT_EGRESS_IP_URL", "").strip()
    # An operator who names their own endpoint did so to avoid disclosing to a
    # third party. Falling back to the public ones on a transient failure would
    # quietly undo exactly that choice, so a custom endpoint is used ALONE.
    endpoints = [custom] if custom else list(_EGRESS_ENDPOINTS)

    deadline = time.monotonic() + _EGRESS_TOTAL_TIMEOUT
    for url in endpoints:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            logger.debug("Egress IP lookup budget exhausted before trying %s", url)
            break
        try:
            found = await asyncio.wait_for(_fetch_egress_ip(url), timeout=remaining)
        except Exception as exc:  # noqa: BLE001 — never let this break a heartbeat
            logger.debug("Egress IP lookup via %s failed: %s", url, exc)
            continue
        if found:
            _egress_cache = (found, now)
            return found

    _egress_cache = (None, now)
    return None


async def _send_heartbeat() -> None:
    """Send a single heartbeat to the UI."""
    global _ui_connected, _last_heartbeat, _last_error, _consecutive_auth_failures

    containers = []
    try:
        containers = await asyncio.to_thread(orchestrator.get_status)
    except Exception as exc:
        logger.warning("Failed to get container status for heartbeat: %s", exc)

    payload = {
        "name": WORKER_NAME,
        "client_id": CLIENT_ID,
        "url": WORKER_URL or f"http://{_get_local_ip()}:{WORKER_PORT}",
        "containers": containers,
        "system_info": {
            "os": f"{platform.system()} {platform.release()}",
            "arch": platform.machine(),
            "hostname": socket.gethostname(),
            "docker_available": await asyncio.to_thread(orchestrator.docker_available),
            # So the UI can tell an operator when the two halves are different
            # releases. An older worker sends nothing here, which reads as
            # unknown rather than as a mismatch (CashPilot-l6c).
            "version": version.current(),
            # Providers count devices per public IP, so the UI needs the address
            # the provider sees — not this container's LAN or tailnet address.
            "egress_ip": await _detect_egress_ip(),
            "egress_network_type": _detect_network_type(),
            # Disk is earning capacity for Storj; GPU decides whether the compute
            # services can earn at all. Both are None/unknown-aware -- see the
            # helpers (CashPilot-cle).
            "disk": await asyncio.to_thread(_disk_usage),
            "gpu": await asyncio.to_thread(_gpu_info),
            "public_ip_slots": _load_public_ip_slots(),
        },
    }
    provider_states: dict[str, dict[str, Any]] = {}
    myst_state = await _myst_provider_state()
    if myst_state:
        provider_states["mysterium"] = myst_state
    nkn_state = await _nkn_provider_state()
    if nkn_state:
        provider_states["nkn"] = nkn_state
    await _refresh_earnapp_lxd_evidence()
    earnapp_state = _earnapp_provider_state(containers)
    if earnapp_state:
        provider_states["earnapp"] = earnapp_state
    if provider_states:
        payload["provider_states"] = provider_states

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{UI_URL.rstrip('/')}/api/workers/heartbeat",
                json=payload,
                headers={"Authorization": f"Bearer {_active_key()}"},
            )
            resp.raise_for_status()
            # Enrollment: the UI returns our own per-worker key exactly once.
            issued = None
            response_payload: dict[str, Any] = {}
            with contextlib.suppress(Exception):
                response_payload = resp.json()
                issued = response_payload.get("worker_key")
            if issued and issued != _worker_key:
                if _save_worker_key(issued):
                    logger.info("Enrolled: received and persisted this worker's own fleet key")
                else:
                    logger.error("Received per-worker key but could not persist it — staying on shared key")
            _ui_connected = True
            _last_heartbeat = datetime.now(UTC).strftime("%H:%M:%S UTC")
            _last_error = ""
            _consecutive_auth_failures = 0
            rejections = response_payload.get("nkn_assignment_rejections")
            if isinstance(rejections, list) and rejections:
                await _reconcile_nkn_assignment_rejections(rejections)
            acknowledgements = response_payload.get("nkn_assignment_acks")
            if isinstance(acknowledgements, list) and acknowledgements:
                await _reconcile_nkn_assignment_acks(acknowledgements)
            earnapp_assignments = response_payload.get("earnapp_assignment_acks")
            if isinstance(earnapp_assignments, list):
                for assignment in earnapp_assignments:
                    if isinstance(assignment, dict):
                        _hydrate_earnapp_state_from_assignment(assignment)
            logger.debug("Heartbeat sent to %s", UI_URL)
    except httpx.HTTPStatusError as exc:
        _ui_connected = False
        status = exc.response.status_code
        _last_error = f"authentication rejected ({status})" if status in (401, 403) else "connection failed"
        logger.warning("Heartbeat failed: %s", exc)
        if status == 401:
            # Counted whether or not we hold our own key. The condition used to
            # be `and _worker_key`, which skipped the alarm in exactly the case
            # it is most needed: a worker that LOST /data/.worker_key — a partial
            # restore, an appdata copy that skips dotfiles — holds no key, sends
            # the shared one, and is refused because the UI's row for this
            # client_id is enrolled and confirmed. That worker 401'd forever and
            # logged nothing but a generic "Heartbeat failed" every 60 seconds,
            # while its service containers kept earning (CashPilot-65s).
            _consecutive_auth_failures += 1
            if _consecutive_auth_failures == _AUTH_FAILURE_ALARM_AFTER:
                # Two different lockouts, two different fixes. Saying the wrong
                # one is worse than saying nothing: the previous message told the
                # operator to write a client_id into /data/.worker_id, which is
                # the fix for neither of the lockouts that actually happen — in
                # both the id is fine and it is the KEY that has to change — and
                # it named an id the dashboard has never displayed.
                if _worker_key:
                    logger.error(
                        "Rejected %d times with this worker's own key. Either it was removed "
                        "in the fleet dashboard, or the UI's credential-encryption key changed "
                        "so it can no longer read the copy it stored. Both are recovered the "
                        "same way and this worker will do it itself after about %d more "
                        "rejections: discard the key and re-enrol. To fix it now, delete %s "
                        "on this host and restart the container.",
                        _consecutive_auth_failures,
                        _AUTH_FAILURE_DISCARD_AFTER - _consecutive_auth_failures,
                        _WORKER_KEY_FILE,
                    )
                else:
                    logger.error(
                        "Rejected %d times using the shared CASHPILOT_API_KEY. The UI already "
                        "has a confirmed enrolment for client_id %r, so it refuses the shared "
                        "key for it — this worker has lost the per-worker key it was issued "
                        "(%s is missing). Restore that file, or remove this worker in the fleet "
                        "dashboard and it will enrol again on its next heartbeat.",
                        _consecutive_auth_failures,
                        CLIENT_ID,
                        _WORKER_KEY_FILE,
                    )
            elif _worker_key and _consecutive_auth_failures >= _AUTH_FAILURE_DISCARD_AFTER:
                # Sustained rejection of our own key is what a worker REMOVED in
                # the dashboard looks like from here. Re-enrol rather than 401
                # forever on a host that is still running containers.
                _discard_worker_key(f"rejected {_consecutive_auth_failures} times; the UI no longer has this enrolment")
        else:
            # Any other outcome breaks the run. "Consecutive" has to mean it:
            # 401 -> timeout -> 401 -> 500 -> 401 is a flaky link, not an
            # identity mismatch, and must not raise the alarm.
            _consecutive_auth_failures = 0
    except Exception as exc:
        _ui_connected = False
        _last_error = "connection failed"
        # A network failure is not an auth rejection, so it breaks the run too.
        _consecutive_auth_failures = 0
        logger.warning("Heartbeat failed: %s", exc)


async def _heartbeat_loop() -> None:
    """Send heartbeats to the UI at regular intervals.

    Every cycle is guarded. _send_heartbeat builds its payload OUTSIDE its own
    try (docker_available, the egress lookup and the network-type probe all run
    while the dict literal is evaluated), so an exception there would otherwise
    propagate out of this loop and kill the task silently and permanently.
    That is strictly worse than any single failed heartbeat: a missed cycle
    costs one 180s offline window and self-heals, whereas a dead task means
    offline until someone restarts the container — while the service containers
    keep earning and nothing surfaces the problem.
    """
    while True:
        try:
            await _send_heartbeat()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Heartbeat cycle failed — continuing")
        try:
            await _enforce_nkn_lease_guard()
        except Exception:
            logger.exception("NKN lease guard cycle failed — continuing")
        await asyncio.sleep(HEARTBEAT_INTERVAL)


def _get_local_ip() -> str:
    """Best-effort local IP detection for worker URL."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        return socket.gethostname()


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _heartbeat_task

    logger.info("CashPilot Worker '%s' starting", WORKER_NAME)
    docker_mode = "direct" if await asyncio.to_thread(orchestrator.docker_available) else "monitor-only"
    logger.info("Docker: %s", docker_mode)

    if UI_URL:
        _heartbeat_task = asyncio.create_task(_heartbeat_loop())
        logger.info("Heartbeat enabled -> %s (every %ds)", UI_URL, HEARTBEAT_INTERVAL)
        if not API_KEY:
            logger.warning("CASHPILOT_API_KEY not set — heartbeats sent without auth")
    else:
        logger.warning("No CASHPILOT_UI_URL — running without UI connection")

    yield

    if _heartbeat_task and not _heartbeat_task.done():
        _heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _heartbeat_task
    logger.info("CashPilot Worker stopped")


app = FastAPI(title="CashPilot Worker", version=version.current(), lifespan=lifespan)


# ---------------------------------------------------------------------------
# Mini-UI (status page)
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def worker_status_page(request: Request):
    """Self-contained HTML status page for the worker."""
    _verify_api_key(request)
    containers = []
    try:
        containers = await asyncio.to_thread(orchestrator.get_status_cached)
    except Exception as exc:
        logger.warning("Failed to get container status for status page: %s", exc)

    container_rows = ""
    for c in containers:
        status_color = "#22c55e" if c.get("status") == "running" else "#ef4444"
        container_rows += f"""
        <tr>
            <td>{_esc(str(c.get("slug", "unknown")))}</td>
            <td><span style="color:{status_color}">{_esc(str(c.get("status", "unknown")))}</span></td>
            <td>{_esc(str(c.get("image", "")))}</td>
            <td>{c.get("cpu_percent", 0)}%</td>
            <td>{c.get("memory_mb", 0)} MB</td>
        </tr>"""

    if not container_rows:
        container_rows = '<tr><td colspan="5" style="text-align:center;color:#6b7280">No managed containers</td></tr>'

    ui_status = (
        f'<span style="color:#22c55e">Connected</span> to <code>{_esc(UI_URL)}</code>'
        if _ui_connected
        else '<span style="color:#ef4444">Disconnected</span>' + (f" — {_esc(_last_error)}" if _last_error else "")
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>CashPilot Worker — {_esc(WORKER_NAME)}</title>
    <meta http-equiv="refresh" content="30">
    <style>
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ font-family:-apple-system,BlinkMacSystemFont,sans-serif; background:#0f1117; color:#e5e7eb; padding:2rem; }}
        h1 {{ font-size:1.5rem; margin-bottom:1.5rem; color:#3b82f6; }}
        .card {{ background:#1a1d26; border-radius:8px; padding:1.25rem; margin-bottom:1rem; }}
        .card h2 {{ font-size:1rem; color:#9ca3af; margin-bottom:.75rem; }}
        .info {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:.5rem; }}
        .info div {{ padding:.5rem; background:#0f1117; border-radius:4px; }}
        .info label {{ font-size:.75rem; color:#6b7280; display:block; }}
        .info span {{ font-size:.875rem; }}
        table {{ width:100%; border-collapse:collapse; }}
        th {{ text-align:left; padding:.5rem; color:#9ca3af; font-size:.75rem; text-transform:uppercase; border-bottom:1px solid #2d3748; }}
        td {{ padding:.5rem; font-size:.875rem; border-bottom:1px solid #1e2433; }}
        code {{ background:#2d3748; padding:.125rem .375rem; border-radius:3px; font-size:.8rem; }}
    </style>
</head>
<body>
    <h1>CashPilot Worker</h1>
    <div class="card">
        <h2>Worker Info</h2>
        <div class="info">
            <div><label>Name</label><span>{_esc(WORKER_NAME)}</span></div>
            <div><label>ID</label><span>{_esc(CLIENT_ID)}</span></div>
            <div><label>Host</label><span>{_esc(socket.gethostname())}</span></div>
            <div><label>Platform</label><span>{_esc(platform.system())} {_esc(platform.machine())}</span></div>
            <div><label>Docker</label><span>{"Available" if await asyncio.to_thread(orchestrator.docker_available) else "Not available"}</span></div>
            <div><label>UI Connection</label><span>{ui_status}</span></div>
            <div><label>Last Heartbeat</label><span>{_last_heartbeat}</span></div>
        </div>
    </div>
    <div class="card">
        <h2>Managed Containers ({len(containers)})</h2>
        <table>
            <thead><tr><th>Service</th><th>Status</th><th>Image</th><th>CPU</th><th>Memory</th></tr></thead>
            <tbody>{container_rows}</tbody>
        </table>
    </div>
    <p style="margin-top:2rem;color:#4b5563;font-size:.75rem">Auto-refreshes every 30s</p>
</body>
</html>"""


# ---------------------------------------------------------------------------
# API: Container management (called by UI)
# ---------------------------------------------------------------------------


class ResourceSpec(BaseModel):
    """Optional Docker resource limits applied when the container is created.

    mem_limit / mem_reservation follow Docker's size syntax ("768m", "2g");
    oom_score_adj biases the kernel OOM killer (-1000 = sacrificed last).
    """

    mem_limit: str | None = None
    mem_reservation: str | None = None
    oom_score_adj: int | None = None


class RuntimeAssetSpec(BaseModel):
    provider: str
    asset_kind: str
    target: str
    asset_id: str = ""
    encoding: str = "text"
    url: str | None = None
    url_arg: str | None = None
    sha256: str | None = None
    decrypt: str | None = None
    decrypt_key_arg: str | None = None


class DeploySpec(BaseModel):
    image: str
    env: dict[str, str] = {}
    ports: dict[str, int] = {}
    volumes: dict[str, dict[str, str]] = {}
    network_mode: str | None = None
    cap_add: list[str] | None = None
    devices: list[str] | None = None
    privileged: bool = False
    command: str | None = None
    hostname: str | None = None
    labels: dict[str, str] = {}
    resources: ResourceSpec | None = None
    egress_mode: str | None = None
    egress_udp: str | None = None
    proxy: dict[str, Any] | None = None
    runtime_assets: list[RuntimeAssetSpec] = Field(default_factory=list)
    installer_manifest_url: str | None = None
    installer_platform: str | None = None
    deploy_credentials: dict[str, Any] = Field(default_factory=dict)
    provider_slug: str | None = None
    host_runtime: str | None = None
    runtime_contract: dict[str, str] = Field(default_factory=dict)
    image_contract_sha256: str = ""
    image_delivery: str = "registry"
    expected_device_id: str = ""
    require_fresh_volume: bool = False
    sysctls: dict[str, str] | None = None
    shm_size: str | None = None
    # Advanced and unsupported. Absent means Docker's default runtime, which is
    # what everything uses and what everything is tested against.
    runtime: str | None = None
    user: str | None = None


class NknDeploySpec(BaseModel):
    wallet_id: int
    wallet_assignment_version: int
    lease_client_id: str = Field(min_length=3, max_length=256)
    wallet_json: str = Field(min_length=1, max_length=200_000)
    wallet_pswd: str = Field(min_length=1, max_length=10_000)
    beneficiary_address: str = Field(min_length=9, max_length=128)
    # Older workers default to the existing Docker backend; the current server
    # always sends ``lxd`` explicitly for newly-created NKN nodes.
    runtime_backend: str = Field(default="docker", pattern=r"^(docker|lxd)$")
    lxd_cpu: int = Field(default=1, ge=1, le=64)
    lxd_memory_mib: int = Field(default=1024, ge=128, le=65536)
    chaindb_snapshot: dict[str, Any] | None = None
    # One-shot, owner-authorized migration of the pre-existing LXD canary.
    # The host helper applies the same exact-name and node-identity guard.
    adopt_instance: str | None = Field(default=None, pattern=r"^cashpilot-nkn-lxd-canary$")
    expected_node_id: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")

    @model_validator(mode="after")
    def validate_canary_adoption(self) -> NknDeploySpec:
        if bool(self.adopt_instance) != bool(self.expected_node_id):
            raise ValueError("canary adoption requires both instance name and expected node id")
        if self.adopt_instance and self.runtime_backend != "lxd":
            raise ValueError("canary adoption requires the LXD runtime backend")
        return self


class NknRemoveSpec(BaseModel):
    wallet_id: int
    wallet_assignment_version: int
    lease_client_id: str = Field(min_length=3, max_length=256)


class EarnAppLxdDeploySpec(BaseModel):
    account_id: int = Field(ge=1)
    generation: int = Field(ge=1)
    platform: str = Field(default="ubuntu", pattern=r"^ubuntu$")
    device_id: str = Field(pattern=r"^sdk-node-[0-9a-f]{32}$")
    identity: dict[str, Any]
    proxy_id: int = Field(ge=1)
    proxy: dict[str, Any]
    lxd_cpu: int = Field(default=1, ge=1, le=64)
    lxd_memory_mib: int = Field(default=1024, ge=128, le=65536)

    @model_validator(mode="after")
    def validate_identity_and_proxy(self) -> EarnAppLxdDeploySpec:
        from app import earnapp_identity

        earnapp_identity.validate_identity(self.identity, "ubuntu")
        if str(self.identity.get("device_id") or "") != self.device_id:
            raise ValueError("EarnApp identity does not match device_id")
        if int(self.proxy.get("proxy_id") or self.proxy.get("id") or 0) != self.proxy_id:
            raise ValueError("EarnApp proxy_id does not match proxy payload")
        if str(self.proxy.get("ip_type") or "").strip().lower() != "residential":
            raise ValueError("EarnApp requires a residential proxy")
        return self


class EarnAppNodeCasSpec(BaseModel):
    generation: int = Field(ge=1)
    device_id: str = Field(pattern=r"^sdk-node-[0-9a-f]{32}$")


class EarnAppDockerNodeCasSpec(BaseModel):
    generation: int = Field(ge=1)
    device_id: str = Field(pattern=r"^sdk-(?:mac|ios|node)-[0-9a-f]{32}$")


class EarnAppProxyApplySpec(BaseModel):
    generation: int = Field(ge=1)
    device_id: str = Field(min_length=8, max_length=128)
    expected_proxy_id: int = Field(ge=1)
    binding_version: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    proxy: dict[str, Any]

    @model_validator(mode="after")
    def validate_proxy(self) -> EarnAppProxyApplySpec:
        if not re.fullmatch(r"sdk-(?:mac|ios|node)-[A-Za-z0-9-]{4,96}", self.device_id):
            raise ValueError("EarnApp device_id is invalid")
        proxy_id = int(self.proxy.get("proxy_id") or self.proxy.get("id") or 0)
        if proxy_id <= 0 or proxy_id == self.expected_proxy_id:
            raise ValueError("EarnApp replacement proxy is invalid")
        if str(self.proxy.get("ip_type") or "").strip().lower() != "residential":
            raise ValueError("EarnApp requires a residential proxy")
        if not str(self.proxy.get("exit_ip") or "").strip():
            raise ValueError("EarnApp replacement proxy requires an egress IP")
        return self


class EarnAppProxyFinalizeSpec(BaseModel):
    generation: int = Field(ge=1)
    device_id: str = Field(min_length=8, max_length=128)
    expected_proxy_id: int = Field(ge=1)
    new_proxy_id: int = Field(ge=1)
    binding_version: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    expected_egress_ip: str = ""
    observed_egress_ip: str = ""
    commit: bool

    @model_validator(mode="after")
    def validate_binding(self) -> EarnAppProxyFinalizeSpec:
        if not re.fullmatch(r"sdk-(?:mac|ios|node)-[A-Za-z0-9-]{4,96}", self.device_id):
            raise ValueError("EarnApp device_id is invalid")
        if self.new_proxy_id == self.expected_proxy_id:
            raise ValueError("EarnApp replacement proxy is invalid")
        if self.commit and (not self.expected_egress_ip or self.observed_egress_ip != self.expected_egress_ip):
            raise ValueError("EarnApp proxy egress evidence does not match")
        return self


class EgressApplySpec(BaseModel):
    mode: str = proxy_egress.PROXY
    service_udp: str = "none"
    worker_name: str | None = None
    proxy: dict[str, Any] | None = None


class ProxyTargetProbeSpec(BaseModel):
    proxy: dict[str, Any]
    targets: list[str] = Field(default_factory=list)


class ProxyBindingApplySpec(BaseModel):
    binding_version: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    proxy: dict[str, Any]
    instances: list[str] = Field(min_length=1, max_length=256)


def _reject_protected_proxy_binding_instances(instances: list[str]) -> None:
    """Reject a batch before probing or mutating any worker-side sidecar."""
    if any(earnapp_policy.is_protected_runtime_reference(instance) for instance in instances):
        raise HTTPException(status_code=409, detail="Protected EarnApp node is inspection-only")


def _probe_proxy_url(proxy: dict[str, Any]) -> str:
    scheme = str(proxy.get("protocol") or proxy.get("scheme") or "socks5").strip().lower()
    if scheme == "socks":
        scheme = "socks5"
    host = str(proxy.get("host") or proxy.get("endpoint_ip") or "").strip()
    port = int(proxy.get("port") or 0)
    username = str(proxy.get("username") or "")
    password = str(proxy.get("password") or "")
    if not host or port <= 0:
        raise ValueError("proxy host/port required")
    auth = ""
    if username:
        auth = urllib.parse.quote(username, safe="") + ":" + urllib.parse.quote(password, safe="") + "@"
    return f"{scheme}://{auth}{host}:{port}"


_DEFAULT_PROXY_PROBE_TARGETS = [
    "https://example.com/",
    "https://proxyjs.brdtnet.com/",
    "https://api.ipify.org?format=json",
]
_PROXY_BINDING_PROBE_TARGETS = ["https://api.ipify.org?format=json"]


async def _probe_proxy_targets(proxy: dict[str, Any], targets: list[str]) -> dict[str, Any]:
    try:
        proxy_url = _probe_proxy_url(proxy)
    except ValueError as exc:
        return {"ok": False, "observed_exit_ip": "", "results": [], "error": type(exc).__name__}

    results: list[dict[str, Any]] = []
    observed_exit_ip = ""
    try:
        async with httpx.AsyncClient(proxy=proxy_url, timeout=12, follow_redirects=False, trust_env=False) as client:
            for target in targets:
                try:
                    resp = await client.get(target, headers={"user-agent": "Mozilla/5.0"})
                    ok = 0 < resp.status_code < 500
                    results.append({"target": target, "status_code": resp.status_code, "ok": ok})
                    if ok and "ipify" in target:
                        with contextlib.suppress(Exception):
                            value = (
                                resp.json().get("ip") if "json" in resp.headers.get("content-type", "") else resp.text
                            )
                            observed_exit_ip = egress.public_ip(str(value or "")) or ""
                except Exception as exc:
                    results.append({"target": target, "status_code": 0, "ok": False, "error": type(exc).__name__})
    except Exception as exc:
        return {"ok": False, "observed_exit_ip": "", "results": results, "error": type(exc).__name__}
    requires_exit_ip = any("ipify" in target for target in targets)
    return {
        "ok": bool(results)
        and all(item["ok"] for item in results)
        and (bool(observed_exit_ip) or not requires_exit_ip),
        "observed_exit_ip": observed_exit_ip,
        "results": results,
    }


async def _fetch_runtime_asset(provider: str, asset_kind: str, *, asset_id: str = "") -> str:
    if not UI_URL:
        raise RuntimeError("CashPilot UI URL not configured")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{UI_URL.rstrip('/')}/api/workers/runtime-asset",
            headers={"Authorization": f"Bearer {_active_key()}"},
            json={"client_id": CLIENT_ID, "provider": provider, "asset_kind": asset_kind, "asset_id": asset_id},
        )
    if resp.status_code == 404:
        raise FileNotFoundError(f"runtime asset {provider}:{asset_kind} not found")
    if resp.status_code in (401, 403):
        raise PermissionError(f"runtime asset {provider}:{asset_kind} rejected")
    resp.raise_for_status()
    value = resp.json().get("value")
    if not isinstance(value, str):
        raise ValueError(f"runtime asset {provider}:{asset_kind} missing value")
    return value


def _runtime_asset_url(asset: RuntimeAssetSpec, spec: DeploySpec, slug: str) -> str:
    url = str(asset.url or "").strip()
    if url:
        return url
    if asset.url_arg:
        return str((spec.deploy_credentials or {}).get(asset.url_arg) or "").strip()
    return ""


def _runtime_asset_scope(value: str, *, label: str) -> str:
    scope = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", scope):
        raise HTTPException(status_code=400, detail=f"Invalid runtime asset {label}")
    return scope


async def _materialize_runtime_assets(slug: str, spec: DeploySpec) -> None:
    if not spec.runtime_assets:
        return
    _RUNTIME_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    for asset in spec.runtime_assets:
        target = str(asset.target or "").strip()
        if not target.startswith("/") or ".." in Path(target).parts:
            raise HTTPException(status_code=400, detail=f"Invalid runtime asset target for {slug}: {target!r}")
        provider = str(asset.provider or slug).strip().lower()
        asset_kind = str(asset.asset_kind or "").strip().lower()
        if not provider or not asset_kind:
            raise HTTPException(status_code=400, detail=f"Invalid runtime asset ref for {slug}")
        encoding = str(asset.encoding or "").lower()
        _runtime_asset_scope(slug, label="slug")
        scope_asset = str(asset.asset_id or "").strip()
        if scope_asset:
            _runtime_asset_scope(scope_asset, label="asset_id")
        asset_root = _RUNTIME_ASSET_DIR / uuid.uuid4().hex
        asset_root.mkdir(parents=True, exist_ok=True)
        host_path = asset_root / "asset"
        download_url = _runtime_asset_url(asset, spec, slug)
        if download_url:
            raise HTTPException(status_code=400, detail="Direct runtime asset downloads are disabled")
        if encoding == "zip":
            raise HTTPException(status_code=400, detail="ZIP runtime assets are disabled")
        else:
            payload = await _fetch_runtime_asset(provider, asset_kind, asset_id=str(asset.asset_id or ""))
            data = base64.b64decode(payload) if encoding == "base64" else payload.encode()
        host_path.write_bytes(data)
        with contextlib.suppress(OSError):
            host_path.chmod(0o644)
        spec.volumes[str(_docker_host_path(host_path))] = {"bind": target, "mode": "ro"}


_BLOCKED_VOLUME_ROOTS = {
    "/",
    "/etc",
    "/root",
    "/proc",
    "/sys",
    "/boot",
    "/dev",
    "/var",
    "/usr",
    "/home",
    "/lib",
    "/lib64",
    "/bin",
    "/sbin",
    "/var/run",
    "/run",  # also covers /run/docker.sock (modern /var/run -> /run symlink)
    "/var/lib/docker",
    "/mnt",  # e.g. Unraid array root (/mnt/user/appdata/<app>) — co-located apps' secrets
    "/media",
    "/opt",
    "/srv",
    "/data",  # per-container app data roots, incl. this worker's own /data
    "/tmp",
}


# System roots that may never be opened up, at ANY depth. An allowlist entry under
# one of these would hand a third-party container the Docker socket (/run,
# /var/run), the host's secrets (/etc, /root) or its devices (/dev) — so unlike the
# data roots below, no subdirectory of these is ever acceptable.
_NEVER_ALLOWLISTABLE = (
    "/etc",
    "/root",
    "/proc",
    "/sys",
    "/dev",
    "/boot",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/run",
    "/var",  # covers /var/run (docker.sock) and /var/lib/docker
)

# How many path components an entry must have below the blocked root it sits under.
# 2 means /mnt/user/storj is allowed but /mnt/user — the whole Unraid array — is not.
_MIN_DEPTH_BELOW_ROOT = 2


def _parse_allowed_volume_roots(raw: str) -> frozenset[str]:
    """Parse CASHPILOT_ALLOWED_VOLUME_ROOTS into a set of opted-in real paths.

    Escape hatch for the blocked roots above. Some legitimate service volumes live
    under one: Storj needs a large data directory, and on Unraid the only such path
    is under /mnt/user/... — so a blanket /mnt deny made Storj undeployable through
    the worker on the platform most users run, pushing them to bypass CashPilot
    entirely (strictly worse for security than a scoped exception).

    Deny-by-default is unchanged, and an entry must clear BOTH gates:

    * it may not resolve under a system root (``_NEVER_ALLOWLISTABLE``) at any depth,
      so /run/docker.sock, /var/lib/docker/... and /etc/shadow are refused; and
    * it must sit at least ``_MIN_DEPTH_BELOW_ROOT`` components below the blocked
      root it belongs to, so /mnt/user/storj is accepted but /mnt and /mnt/user
      (the entire array) are not.

    RESIDUAL RISK, stated plainly rather than papered over: this worker resolves
    paths in its OWN mount namespace and cannot see the host filesystem, so a
    symlink created *inside* an allowlisted directory by the service that owns it
    resolves differently here than in the Docker daemon. Only allowlist a directory
    whose contents you are willing to treat as trusted.
    """
    allowed: set[str] = set()
    for entry in raw.split(":"):
        entry = entry.strip()
        if not entry:
            continue
        if not entry.startswith("/"):
            logger.warning(
                "Ignoring CASHPILOT_ALLOWED_VOLUME_ROOTS entry %r: must be an absolute path",
                entry,
            )
            continue
        # Check the resolved path AND the lexical one: resolving can move a path out
        # of a blocked prefix (on macOS /etc -> /private/etc), and a system path must
        # be refused under either spelling rather than relying on one platform's
        # symlink layout.
        real = os.path.realpath(entry)
        lexical = os.path.normpath(entry)
        if any(
            candidate == sys_root or candidate.startswith(sys_root + "/")
            for candidate in (real, lexical)
            for sys_root in _NEVER_ALLOWLISTABLE
        ):
            logger.warning(
                "Refusing CASHPILOT_ALLOWED_VOLUME_ROOTS entry %r: %s is a system path and can never be opted in",
                entry,
                real,
            )
            continue
        if real == "/" or real in _BLOCKED_VOLUME_ROOTS:
            logger.warning(
                "Refusing CASHPILOT_ALLOWED_VOLUME_ROOTS entry %r: that is a whole root, not a service directory",
                entry,
            )
            continue
        depth_ok = True  # not under any blocked root -> the deny list never applied anyway
        for blocked in _BLOCKED_VOLUME_ROOTS:
            if blocked != "/" and real.startswith(blocked + "/"):
                depth_ok = real[len(blocked) + 1 :].count("/") >= _MIN_DEPTH_BELOW_ROOT - 1
                break
        if not depth_ok:
            logger.warning(
                "Refusing CASHPILOT_ALLOWED_VOLUME_ROOTS entry %r: name a specific service "
                "directory (e.g. /mnt/user/storj), not a whole root like /mnt or /mnt/user",
                entry,
            )
            continue
        allowed.add(real)
    return frozenset(allowed)


_ALLOWED_VOLUME_ROOTS = _parse_allowed_volume_roots(os.getenv("CASHPILOT_ALLOWED_VOLUME_ROOTS", ""))

# Docker memory size syntax: a positive integer with an optional b/k/m/g unit.
_MEM_LIMIT_RE = re.compile(r"^\d+[bkmgBKMG]?$")


# Devices a service may ever request. A device is a direct line to the kernel,
# so this is a hard ceiling that the catalog cannot widen: adding an entry here
# is a deliberate maintainer decision, not something a service YAML can do on
# its own. /dev/net/tun is here because Mysterium genuinely cannot carry
# wireguard traffic without it — deployed without the device the node starts,
# registers and earns nothing, which is exactly the failure this closes.
_ALLOWED_DEVICES = frozenset({"/dev/net/tun"})


def _catalog_allowed_devices(slug: str | None = None) -> set[str]:
    """Devices the catalog declares for one slug, intersected with the ceiling.

    Scoped per-slug for the same reason capabilities are: with a union, one
    service declaring a device would let every other slug request it too. An
    unknown slug gets the empty set — deny rather than fall back to the union.
    """
    if not _catalog_get_services:
        return set()
    devices: set[str] = set()
    for svc in _catalog_get_services():
        if slug is not None and svc.get("slug") != slug:
            continue
        for dev in (svc.get("docker") or {}).get("devices") or []:
            devices.add(str(dev).split(":")[0].rstrip("/"))
    # Never return anything outside the ceiling, even if a YAML asks for it.
    return devices & set(_ALLOWED_DEVICES)


def _catalog_allowed_capabilities(slug: str | None = None) -> set[str]:
    """cap_add values the catalog declares — for one slug, or the union.

    Derived from services/*.yml (the single source of truth) instead of a
    hardcoded list, so it stays correct as the catalog changes. A capability
    no catalog service asks for is refused, whatever it is.

    Pass ``slug`` to scope the answer to that one service. That matters: with a
    union, a single service declaring NET_RAW would let *every* slug request
    NET_RAW, so adding one capability to one YAML quietly widens the allowlist
    for all 49. Per-slug keeps each service to exactly what its own YAML asks
    for. An unknown slug gets the empty set — deny, not fall back to the union.
    """
    if not _catalog_get_services:
        return set()
    caps: set[str] = set()
    for svc in _catalog_get_services():
        if slug is not None and svc.get("slug") != slug:
            continue
        for cap in (svc.get("docker") or {}).get("cap_add") or []:
            caps.add(str(cap).upper())
    return caps


def _catalog_host_network_slugs() -> set[str]:
    """Slugs whose catalog definition legitimately declares network_mode: host."""
    if not _catalog_get_services:
        return set()
    return {svc["slug"] for svc in _catalog_get_services() if (svc.get("docker") or {}).get("network_mode") == "host"}


# Named volumes (bridge/none/unset) are always allowed. `host` is allowed only for
# catalog services that declare it (checked separately below, by slug). `container:<id>`
# (namespace join) and any other value are rejected outright.
_ALLOWED_NETWORK_MODES = {None, "", "bridge", "none", "host"}
_HOST_NETWORK_DIRECT_EXCEPTIONS = {"earnfm"}


def _validate_runtime(runtime: str | None) -> None:
    """Allow only a runtime this daemon actually reports.

    Deliberately NOT a hardcoded list. A runtime CashPilot recognises but the
    host has not installed would fail at container-create time with a Docker
    error the user cannot act on; asking the daemon means the only runtimes
    accepted are ones that exist here.

    Nothing selects a non-default runtime on its own. See docs/security-defaults.md for
    why gVisor is not adopted as a default or as a supported profile: it costs
    roughly 1.7x network throughput on a workload that is pure network I/O, it
    breaks host-networked services outright, and it does not address the risks
    that actually occur in this category.
    """
    if not runtime:
        return
    available = orchestrator.available_runtimes()
    if runtime not in available:
        raise HTTPException(
            status_code=400,
            detail=(
                f"This host's Docker daemon does not provide a {runtime!r} runtime. "
                f"Available: {sorted(available) or 'none reported'}."
            ),
        )


def _validate_deploy_spec(spec: DeploySpec, slug: str | None = None) -> None:
    _validate_runtime(spec.runtime)
    provider_slug = spec.provider_slug or slug
    if provider_slug == "earnapp":
        try:
            earnapp_runtime.validate_runtime_spec(spec.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        if spec.image_delivery != "operator_preload":
            raise HTTPException(status_code=403, detail="EarnApp runtime requires an operator-preloaded image")
    if spec.privileged:
        raise HTTPException(status_code=403, detail="Privileged containers are not allowed")
    if spec.cap_add:
        requested = {c.upper() for c in spec.cap_add}
        blocked = requested - _catalog_allowed_capabilities(provider_slug)
        if blocked:
            raise HTTPException(status_code=403, detail=f"Blocked capabilities: {', '.join(sorted(blocked))}")
    if spec.devices:
        requested_devices = {str(d).split(":")[0].rstrip("/") for d in spec.devices}
        blocked_devices = requested_devices - _catalog_allowed_devices(provider_slug)
        if blocked_devices:
            raise HTTPException(
                status_code=403,
                detail=f"Blocked devices: {', '.join(sorted(blocked_devices))}",
            )
    if spec.network_mode not in _ALLOWED_NETWORK_MODES:
        raise HTTPException(status_code=403, detail=f"Network mode '{spec.network_mode}' is not allowed")
    if spec.network_mode == "host" and provider_slug not in (
        _catalog_host_network_slugs() | _HOST_NETWORK_DIRECT_EXCEPTIONS
    ):
        raise HTTPException(status_code=403, detail=f"Network mode 'host' is not allowed for '{slug}'")
    for source in spec.volumes:
        if not source.startswith("/"):
            continue  # named volume (e.g. "mysterium-data") — always allowed
        real = os.path.realpath(source)
        if any(real == root or real.startswith(root + "/") for root in _ALLOWED_VOLUME_ROOTS):
            continue  # explicitly opted in by the operator (see _parse_allowed_volume_roots)
        for blocked in _BLOCKED_VOLUME_ROOTS:
            if real == blocked or real.startswith(blocked + "/"):
                raise HTTPException(status_code=403, detail=f"Volume mount '{source}' is blocked")
    _validate_resources(spec.resources)


def _validate_resources(resources: ResourceSpec | None) -> None:
    if resources is None:
        return
    for field, value in (("mem_limit", resources.mem_limit), ("mem_reservation", resources.mem_reservation)):
        if value is not None and not _MEM_LIMIT_RE.match(value):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid {field} '{value}': expected a size like '768m' or '2g'",
            )
    if resources.oom_score_adj is not None and not (-1000 <= resources.oom_score_adj <= 1000):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid oom_score_adj '{resources.oom_score_adj}': must be between -1000 and 1000",
        )


@app.get("/api/status")
async def api_worker_status(request: Request) -> dict[str, Any]:
    """Return worker status summary."""
    _verify_api_key(request)
    containers = []
    try:
        containers = await asyncio.to_thread(orchestrator.get_status_cached)
    except Exception as exc:
        logger.warning("Failed to get container status: %s", exc)
    return {
        "name": WORKER_NAME,
        "client_id": CLIENT_ID,
        "docker_available": await asyncio.to_thread(orchestrator.docker_available),
        "ui_connected": _ui_connected,
        "container_count": len(containers),
        "running_count": sum(1 for c in containers if c.get("status") == "running"),
    }


@app.get("/api/network/slots")
async def api_network_slots(request: Request) -> list[dict[str, Any]]:
    """Return the read-only public-IP slot state prepared during bootstrap."""
    _verify_api_key(request)
    return _load_public_ip_slots()


@app.get("/api/containers")
async def api_list_containers(request: Request) -> list[dict[str, Any]]:
    """List all CashPilot-managed containers."""
    _verify_api_key(request)
    try:
        return await asyncio.to_thread(orchestrator.get_status_cached)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/containers/{slug}/presence")
async def api_container_presence(request: Request, slug: str) -> dict[str, Any]:
    """Check one exact managed Docker container without consulting the cache."""
    _verify_api_key(request)
    try:
        container = await asyncio.to_thread(orchestrator._find_container, slug)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    labels = getattr(container, "labels", {}) or {}
    provider = str(labels.get("cashpilot.provider") or labels.get("cashpilot.service") or "")
    return {
        "present": True,
        "slug": slug,
        "provider_slug": provider,
        "container_id": str(getattr(container, "short_id", "") or ""),
    }


@app.post("/api/nkn/slots/{slot_id}/deploy")
async def api_deploy_nkn_slot(request: Request, slot_id: str, spec: NknDeploySpec) -> dict[str, str]:
    """Deploy exactly one NKN node into a bootstrap-prepared public-IP slot."""
    _verify_api_key(request)
    slots = {str(slot.get("slot_id")): slot for slot in _load_public_ip_slots()}
    slot = slots.get(slot_id)
    if slot is None:
        raise HTTPException(status_code=404, detail="NKN public-IP slot not found")
    if spec.wallet_id <= 0 or spec.wallet_assignment_version <= 0:
        raise HTTPException(status_code=400, detail="Invalid NKN wallet assignment")
    wallet_address = nkn_runtime._wallet_address(spec.wallet_json)
    assignment = {
        "wallet_id": spec.wallet_id,
        "wallet_assignment_version": spec.wallet_assignment_version,
        "lease_client_id": spec.lease_client_id,
        "wallet_json": spec.wallet_json,
        "wallet_pswd": spec.wallet_pswd,
        "beneficiary_address": spec.beneficiary_address,
    }

    def _deploy() -> dict[str, str]:
        if spec.runtime_backend == "lxd":
            return nkn_lxd_runtime.deploy_slot(
                slot,
                assignment,
                settings={"cpu": spec.lxd_cpu, "memory_mib": spec.lxd_memory_mib},
                snapshot=spec.chaindb_snapshot,
                adopt_instance=spec.adopt_instance,
                expected_node_id=spec.expected_node_id,
            )
        client = orchestrator._get_client()
        try:
            return nkn_runtime.deploy_slot(slot, assignment, client=client)
        finally:
            with contextlib.suppress(Exception):
                client.close()

    try:
        result = await asyncio.to_thread(_deploy)
    except nkn_runtime.NknAssignmentConflict as exc:
        raise HTTPException(status_code=409, detail="NKN slot assignment conflict") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    state = {
        "slot_id": slot_id,
        "instance_id": result["instance_id"],
        "container_id": result.get("container_id", ""),
        "wallet_id": spec.wallet_id,
        "wallet_assignment_version": spec.wallet_assignment_version,
        "lease_client_id": spec.lease_client_id,
        "wallet_address": wallet_address,
        "public_ip": slot.get("public_ip", ""),
        "runtime_status": "running",
        "runtime_backend": spec.runtime_backend,
        "lxd_cpu": spec.lxd_cpu if spec.runtime_backend == "lxd" else None,
        "lxd_memory_mib": spec.lxd_memory_mib if spec.runtime_backend == "lxd" else None,
        "evidence": {"running": True, "online": False},
        "last_server_ack_at": time.time(),
        "lease_guard_suspended": False,
        "snapshot_status": str(result.get("snapshot_status") or "skipped"),
    }
    _save_nkn_wallet_state(slot_id, state)
    response = {
        "status": "deployed",
        "container_id": result["container_id"],
        "instance_id": result["instance_id"],
        "slot_id": slot_id,
    }
    if result.get("snapshot_status"):
        response["snapshot_status"] = str(result["snapshot_status"])
    return response


@app.delete("/api/nkn/slots/{slot_id}")
async def api_remove_nkn_slot(request: Request, slot_id: str, spec: NknRemoveSpec) -> dict[str, Any]:
    """Deliberately remove one NKN node and its identity volume with assignment CAS."""
    _verify_api_key(request)
    try:
        state = json.loads(_nkn_state_path(slot_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="NKN slot state not found") from exc
    expected = (
        int(state.get("wallet_id") or 0),
        int(state.get("wallet_assignment_version") or 0),
        str(state.get("lease_client_id") or ""),
    )
    supplied = (spec.wallet_id, spec.wallet_assignment_version, spec.lease_client_id)
    if supplied != expected:
        raise HTTPException(status_code=409, detail="NKN slot assignment conflict")

    def _remove() -> dict[str, Any]:
        if str(state.get("runtime_backend") or "docker") == "lxd":
            return nkn_lxd_runtime.remove_slot(
                slot_id,
                wallet_id=spec.wallet_id,
                wallet_assignment_version=spec.wallet_assignment_version,
                lease_client_id=spec.lease_client_id,
                delete_volume=True,
            )
        client = orchestrator._get_client()
        try:
            return nkn_runtime.remove_slot(
                slot_id,
                wallet_id=spec.wallet_id,
                wallet_assignment_version=spec.wallet_assignment_version,
                lease_client_id=spec.lease_client_id,
                client=client,
                delete_volume=True,
            )
        finally:
            with contextlib.suppress(Exception):
                client.close()

    try:
        result = await asyncio.to_thread(_remove)
    except nkn_runtime.NknAssignmentConflict as exc:
        raise HTTPException(status_code=409, detail="NKN slot assignment conflict") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with contextlib.suppress(FileNotFoundError):
        _nkn_state_path(slot_id).unlink()
    return {"status": "removed", "slot_id": slot_id, **result}


def _earnapp_lxd_state(logical_node_id: str) -> dict[str, Any]:
    try:
        value = json.loads(_earnapp_state_path(logical_node_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="EarnApp node state not found") from exc
    if not isinstance(value, dict) or str(value.get("runtime_backend") or "") != "lxd":
        raise HTTPException(status_code=404, detail="EarnApp LXD node state not found")
    return value


def _earnapp_node_state(logical_node_id: str) -> dict[str, Any]:
    try:
        value = json.loads(_earnapp_state_path(logical_node_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="EarnApp node state not found") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=404, detail="EarnApp node state not found")
    return value


def _validate_earnapp_proxy_cas(
    state: dict[str, Any], *, generation: int, device_id: str, expected_proxy_id: int
) -> None:
    expected = (
        int(state.get("generation") or 0),
        str(state.get("device_id") or ""),
        int(state.get("proxy_id") or 0),
    )
    supplied = (int(generation), str(device_id), int(expected_proxy_id))
    if expected != supplied:
        raise HTTPException(status_code=409, detail="EarnApp proxy assignment conflict")


def _earnapp_proxy_finalize_replay(state: dict[str, Any], spec: EarnAppProxyFinalizeSpec) -> bool:
    """Accept only an exact replay of a commit whose acknowledgement was lost.

    The committed binding journal is deliberately separate from ``proxy_id``.  A
    changed proxy by itself is not evidence that an arbitrary finalize request is
    safe to replay.
    """
    if not spec.commit:
        return False
    if any(
        state.get(key) not in (None, "")
        for key in (
            "pending_binding_version",
            "pending_proxy_id",
            "pending_expected_egress_ip",
            "pending_observed_egress_ip",
        )
    ):
        return False
    return (
        str(state.get("last_binding_version") or "") == spec.binding_version
        and int(state.get("last_binding_generation") or 0) == spec.generation
        and str(state.get("last_binding_device_id") or "") == spec.device_id
        and int(state.get("last_binding_expected_proxy_id") or 0) == spec.expected_proxy_id
        and int(state.get("last_binding_proxy_id") or 0) == spec.new_proxy_id
        and int(state.get("proxy_id") or 0) == spec.new_proxy_id
        and str(state.get("expected_egress_ip") or "") == spec.expected_egress_ip
        and str(state.get("observed_egress_ip") or "") == spec.observed_egress_ip
    )


def _earnapp_proxy_rollback_complete(
    status: Mapping[str, Any], evidence: Mapping[str, Any], old_egress_ip: str
) -> bool:
    """Recognize a clean rollback without treating a failed egress probe as drift."""
    if (
        status.get("binding_version")
        or status.get("candidate_present") is True
        or status.get("previous_present") is True
        or evidence.get("running") is not True
        or not old_egress_ip
    ):
        return False
    observed = str(evidence.get("observed_egress_ip") or "").strip()
    if evidence.get("probe_ok") is True:
        return observed == old_egress_ip
    return not observed


async def _earnapp_proxy_runtime_snapshot(
    logical_node_id: str,
    state: dict[str, Any],
    *,
    generation: int,
    device_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    backend = str(state.get("runtime_backend") or "docker").strip().lower()
    if backend == "lxd":
        status = await asyncio.to_thread(
            earnapp_lxd_runtime.proxy_binding_status,
            logical_node_id,
            generation=generation,
            device_id=device_id,
        )
        evidence = await asyncio.to_thread(
            earnapp_lxd_runtime.node_evidence,
            logical_node_id,
            generation=generation,
            device_id=device_id,
        )
    else:
        status = await asyncio.to_thread(orchestrator.proxy_binding_status, logical_node_id)
        evidence = await asyncio.to_thread(orchestrator.probe_service_egress, logical_node_id)
    return status, evidence


async def _discard_earnapp_proxy_candidate(
    logical_node_id: str,
    state: dict[str, Any],
    *,
    generation: int,
    device_id: str,
    expected_proxy_id: int,
    binding_version: str,
) -> dict[str, Any]:
    backend = str(state.get("runtime_backend") or "docker").strip().lower()
    if backend == "lxd":
        return await asyncio.to_thread(
            earnapp_lxd_runtime.discard_proxy_binding,
            logical_node_id,
            generation=generation,
            device_id=device_id,
            expected_proxy_id=expected_proxy_id,
            binding_version=binding_version,
        )
    return await asyncio.to_thread(orchestrator.discard_proxy_binding, logical_node_id, binding_version)


def _validate_earnapp_lxd_cas(state: dict[str, Any], spec: EarnAppNodeCasSpec) -> None:
    expected = (int(state.get("generation") or 0), str(state.get("device_id") or ""))
    if expected != (spec.generation, spec.device_id):
        raise HTTPException(status_code=409, detail="EarnApp node assignment conflict")


@app.post("/api/earnapp/nodes/{logical_node_id}/deploy")
async def api_deploy_earnapp_lxd_node(
    request: Request,
    logical_node_id: str,
    spec: EarnAppLxdDeploySpec,
) -> dict[str, Any]:
    """Deploy one official Ubuntu EarnApp runtime through the restricted helper."""
    _verify_api_key(request)
    _reject_earnapp_runtime_mutation(logical_node_id, platform="ubuntu", runtime_backend="lxd")
    if not earnapp_runtime.runtime_deployment_allowed("ubuntu", "lxd"):
        raise HTTPException(status_code=409, detail=provider_runtime.EARNAPP_PLATFORM_BLOCK_MESSAGE)
    try:
        result = await asyncio.to_thread(
            earnapp_lxd_runtime.deploy_node,
            logical_node_id,
            generation=spec.generation,
            account_id=spec.account_id,
            device_id=spec.device_id,
            identity=spec.identity,
            proxy=spec.proxy,
            settings={"cpu": spec.lxd_cpu, "memory_mib": spec.lxd_memory_mib},
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    state = {
        "logical_node_id": logical_node_id,
        "generation": spec.generation,
        "account_id": spec.account_id,
        "device_id": spec.device_id,
        "proxy_id": spec.proxy_id,
        "expected_egress_ip": str(spec.proxy.get("exit_ip") or ""),
        "observed_egress_ip": "",
        "proxy_health": "unknown",
        "proxy_health_reason": "",
        "platform": "ubuntu",
        "runtime_backend": "lxd",
        "runtime_status": "running" if result.get("running") is True else "unknown",
        "instance_id": str(result.get("instance_id") or ""),
        "lxd_cpu": spec.lxd_cpu,
        "lxd_memory_mib": spec.lxd_memory_mib,
        "evidence": earnapp_runtime.redacted_evidence(result),
    }
    _save_earnapp_state(logical_node_id, state)
    return {"status": "deployed", "logical_node_id": logical_node_id, **earnapp_runtime.redacted_evidence(result)}


@app.post("/api/earnapp/nodes/{logical_node_id}/suspend")
async def api_suspend_earnapp_lxd_node(
    request: Request, logical_node_id: str, spec: EarnAppNodeCasSpec
) -> dict[str, Any]:
    _verify_api_key(request)
    _reject_earnapp_runtime_mutation(logical_node_id, platform="ubuntu", runtime_backend="lxd")
    state = _earnapp_lxd_state(logical_node_id)
    _validate_earnapp_lxd_cas(state, spec)
    result = await asyncio.to_thread(
        earnapp_lxd_runtime.suspend_node,
        logical_node_id,
        generation=spec.generation,
        device_id=spec.device_id,
    )
    state["runtime_status"] = "stopped"
    state["evidence"] = earnapp_runtime.redacted_evidence(result)
    _save_earnapp_state(logical_node_id, state)
    return {"status": "suspended", **earnapp_runtime.redacted_evidence(result)}


@app.post("/api/earnapp/nodes/{logical_node_id}/resume")
async def api_resume_earnapp_lxd_node(
    request: Request, logical_node_id: str, spec: EarnAppNodeCasSpec
) -> dict[str, Any]:
    _verify_api_key(request)
    _reject_earnapp_runtime_mutation(logical_node_id, platform="ubuntu", runtime_backend="lxd")
    state = _earnapp_lxd_state(logical_node_id)
    _validate_earnapp_lxd_cas(state, spec)
    result = await asyncio.to_thread(
        earnapp_lxd_runtime.resume_node,
        logical_node_id,
        generation=spec.generation,
        device_id=spec.device_id,
    )
    state["runtime_status"] = "running"
    state["evidence"] = earnapp_runtime.redacted_evidence(result)
    _save_earnapp_state(logical_node_id, state)
    return {"status": "resumed", **earnapp_runtime.redacted_evidence(result)}


@app.get("/api/earnapp/nodes/{logical_node_id}/evidence")
async def api_earnapp_lxd_node_evidence(
    request: Request, logical_node_id: str, generation: int, device_id: str
) -> dict[str, Any]:
    _verify_api_key(request)
    state = _earnapp_lxd_state(logical_node_id)
    spec = EarnAppNodeCasSpec(generation=generation, device_id=device_id)
    _validate_earnapp_lxd_cas(state, spec)
    result = await asyncio.to_thread(
        earnapp_lxd_runtime.node_evidence,
        logical_node_id,
        generation=generation,
        device_id=device_id,
    )
    state["evidence"] = earnapp_runtime.redacted_evidence(result)
    state["runtime_status"] = "running" if result.get("running") is True else "stopped"
    _save_earnapp_state(logical_node_id, state)
    return earnapp_runtime.redacted_evidence(result)


@app.post("/api/earnapp/nodes/{logical_node_id}/presence")
async def api_earnapp_lxd_node_presence(
    request: Request, logical_node_id: str, spec: EarnAppNodeCasSpec
) -> dict[str, Any]:
    """Check the exact LXD assignment even if the worker state file is gone."""
    _verify_api_key(request)
    try:
        return await asyncio.to_thread(
            earnapp_lxd_runtime.node_presence,
            logical_node_id,
            generation=spec.generation,
            device_id=spec.device_id,
        )
    except earnapp_lxd_runtime.EarnAppLxdHelperError as exc:
        status = exc.status_code if exc.status_code in {404, 409} else 503
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@app.delete("/api/earnapp/nodes/{logical_node_id}")
async def api_remove_earnapp_lxd_node(
    request: Request, logical_node_id: str, spec: EarnAppNodeCasSpec
) -> dict[str, Any]:
    _verify_api_key(request)
    _reject_earnapp_runtime_mutation(logical_node_id, platform="ubuntu", runtime_backend="lxd")
    try:
        state = _earnapp_lxd_state(logical_node_id)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
    else:
        _validate_earnapp_lxd_cas(state, spec)
    try:
        result = await asyncio.to_thread(
            earnapp_lxd_runtime.remove_node,
            logical_node_id,
            generation=spec.generation,
            device_id=spec.device_id,
        )
    except earnapp_lxd_runtime.EarnAppLxdHelperError as exc:
        if exc.status_code != 404:
            status = 409 if exc.status_code == 409 else 503
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        result = {"idempotent": True}
    _remove_earnapp_state(logical_node_id)
    return {"status": "removed", "logical_node_id": logical_node_id, **earnapp_runtime.redacted_evidence(result)}


@app.delete("/api/earnapp/docker-nodes/{slug}")
async def api_remove_earnapp_docker_node(
    request: Request,
    slug: str,
    spec: EarnAppDockerNodeCasSpec,
) -> dict[str, Any]:
    """Remove both Docker components before acknowledging local EarnApp cleanup."""
    _verify_api_key(request)
    if earnapp_policy.is_protected_logical_node(slug):
        raise HTTPException(status_code=409, detail="Protected EarnApp node is inspection-only")
    state = _earnapp_node_state(slug)
    platform = str(state.get("platform") or "").strip().lower()
    if not platform:
        platform = "ios" if str(state.get("device_id") or "").startswith("sdk-ios-") else "macos"
    _reject_earnapp_runtime_mutation(slug, platform=platform, runtime_backend="docker")
    expected = (int(state.get("generation") or 0), str(state.get("device_id") or ""))
    if expected != (spec.generation, spec.device_id):
        raise HTTPException(status_code=409, detail="EarnApp node assignment conflict")
    try:
        result = await asyncio.to_thread(orchestrator.remove_earnapp_service, slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result.get("main_present") is not False or result.get("sidecar_present") is not False:
        raise HTTPException(status_code=409, detail="EarnApp Docker cleanup is incomplete")
    with contextlib.suppress(ValueError):
        _remove_earnapp_state(slug)
    return {"status": "removed", **result}


@app.get("/api/earnapp/docker-nodes/{slug}/runtime-authority")
@_serialize_earnapp_node_mutation
async def api_earnapp_node_runtime_authority(
    request: Request,
    slug: str,
    generation: int,
    device_id: str,
    expected_proxy_id: int,
) -> dict[str, Any]:
    """Return a read-only, CAS-scoped snapshot for server-side repair."""
    state = _earnapp_node_state(slug)
    _validate_earnapp_proxy_cas(
        state,
        generation=generation,
        device_id=device_id,
        expected_proxy_id=expected_proxy_id,
    )
    if str(state.get("runtime_backend") or "").strip().lower() != "docker":
        raise HTTPException(status_code=409, detail="EarnApp runtime authority supports Docker nodes only")
    try:
        authority = await asyncio.to_thread(orchestrator.earnapp_runtime_authority, slug)
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=409, detail="EarnApp runtime authority is unavailable") from exc
    state_platform = str(state.get("platform") or "").strip().lower()
    authority_platform = str(authority.get("platform") or "").strip().lower()
    state_platform = {"darwin": "macos", "linux": "ubuntu"}.get(state_platform, state_platform)
    authority_platform = {"darwin": "macos", "linux": "ubuntu"}.get(authority_platform, authority_platform)
    if (
        str(authority.get("logical_node_id") or "") != slug
        or int(authority.get("generation") or 0) != generation
        or str(authority.get("device_id") or "") != device_id
        or state_platform not in {"macos", "ios", "ubuntu"}
        or authority_platform != state_platform
    ):
        raise HTTPException(status_code=409, detail="EarnApp runtime authority conflicts with worker state")
    return {
        **authority,
        "platform": authority_platform,
        "generation": int(state.get("generation") or 0),
        "proxy_id": int(state.get("proxy_id") or 0),
        "expected_egress_ip": str(state.get("expected_egress_ip") or ""),
    }


@app.post("/api/earnapp/docker-nodes/{slug}/deploy")
async def api_deploy_earnapp_docker_node(request: Request, slug: str, spec: DeploySpec) -> dict[str, Any]:
    """Deploy a validated MacOS/iOS/Ubuntu EarnApp runtime through its dedicated lane."""
    _verify_api_key(request)
    platform = str((spec.runtime_contract or {}).get("platform") or "").strip().lower()
    if platform == "darwin":
        platform = "macos"
    _reject_earnapp_runtime_mutation(slug, platform=platform, runtime_backend="docker")
    if str(spec.provider_slug or "").strip().lower() != "earnapp":
        raise HTTPException(status_code=400, detail="EarnApp provider is required")
    if platform not in {"macos", "ios", "linux"}:
        raise HTTPException(status_code=400, detail="Dedicated Docker route supports only MacOS, iOS, or Ubuntu")
    logical_node_id = str(spec.labels.get("cashpilot.earnapp.logical_node_id") or slug)
    if logical_node_id != slug:
        raise HTTPException(status_code=409, detail="EarnApp logical node does not match the Docker route")
    try:
        _validate_deploy_spec(spec, slug=slug)
        if platform == "linux" and spec.require_fresh_volume:
            await asyncio.to_thread(orchestrator.assert_fresh_earnapp_runtime, slug, spec.volumes)
        await _materialize_runtime_assets(slug, spec)
        try:
            container_id = await asyncio.to_thread(
                orchestrator.deploy_raw,
                slug=slug,
                provider_slug="earnapp",
                image=spec.image,
                env=spec.env,
                ports=spec.ports,
                volumes=spec.volumes,
                network_mode=spec.network_mode,
                cap_add=spec.cap_add,
                devices=spec.devices,
                command=spec.command,
                hostname=spec.hostname,
                labels=spec.labels,
                resources=spec.resources,
                runtime=spec.runtime,
                installer_manifest_url=spec.installer_manifest_url,
                installer_platform=spec.installer_platform,
                deploy_credentials=spec.deploy_credentials,
                user=spec.user,
                host_runtime=spec.host_runtime,
                image_delivery=spec.image_delivery,
                proxy=spec.proxy,
                sysctls=spec.sysctls,
                shm_size=spec.shm_size,
            )
        except Exception as exc:
            # The fresh-state guard ran before mutation. If Docker failed after
            # creating a component, remove only this fresh Ubuntu service and
            # retain its named identity volume for diagnosis/retry.
            if platform == "linux" and spec.require_fresh_volume:
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(orchestrator.remove_earnapp_service, slug)
                with contextlib.suppress(ValueError):
                    _remove_earnapp_state(logical_node_id)
                if isinstance(exc, RuntimeError):
                    raise HTTPException(status_code=409, detail=str(exc)) from exc
                logger.exception("Dedicated EarnApp Docker deployment failed for %s", slug)
                raise HTTPException(status_code=500, detail="EarnApp Docker deployment failed") from exc
            raise
    except HTTPException:
        raise
    except RuntimeError as exc:
        if platform == "linux" and spec.require_fresh_volume:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        logger.exception("Dedicated EarnApp Docker deploy failed for %s", slug)
        raise HTTPException(status_code=500, detail="EarnApp Docker deployment failed") from exc
    except Exception as exc:
        logger.exception("Dedicated EarnApp Docker deploy failed for %s", slug)
        raise HTTPException(status_code=500, detail="EarnApp Docker deployment failed") from exc
    proxy = dict(spec.proxy or {})
    device_id = str(spec.labels.get("cashpilot.earnapp.device_id") or "")
    if platform == "linux":
        try:
            device_id = await asyncio.to_thread(orchestrator.wait_for_earnapp_device_id, slug)
            expected_device_id = str(spec.expected_device_id or "")
            if expected_device_id and expected_device_id != device_id:
                raise RuntimeError("EarnApp Ubuntu runtime identity does not match assignment")
        except RuntimeError as exc:
            # The exact Docker runtime was created by this request, but its UUID
            # never became authoritative. Remove only its containers and retain
            # the named volume for diagnosis; never delete identity state here.
            with contextlib.suppress(Exception):
                await asyncio.to_thread(orchestrator.remove_earnapp_service, slug)
            with contextlib.suppress(ValueError):
                _remove_earnapp_state(logical_node_id)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    _save_earnapp_state(
        logical_node_id,
        {
            "logical_node_id": logical_node_id,
            "generation": int(spec.labels.get("cashpilot.earnapp.generation") or 0),
            "device_id": device_id,
            "platform": platform,
            "runtime_backend": "docker",
            "proxy_id": int(proxy.get("proxy_id") or proxy.get("id") or 0),
            "expected_egress_ip": str(proxy.get("exit_ip") or ""),
            "runtime_status": "running",
            "container_id": container_id,
            "evidence": {"running": True, "online": False},
        },
    )
    return {
        "status": "deployed",
        "container_id": container_id,
        "logical_node_id": logical_node_id,
        "device_id": device_id,
    }


@app.post("/api/earnapp/docker-nodes/{slug}/recreate")
async def api_recreate_earnapp_docker_node(
    request: Request,
    slug: str,
    spec: EarnAppDockerNodeCasSpec,
) -> dict[str, Any]:
    """Recreate one assigned main runtime without linking or changing identity."""
    _verify_api_key(request)
    state = _earnapp_node_state(slug)
    platform = str(state.get("platform") or "").strip().lower()
    _reject_earnapp_runtime_mutation(slug, platform=platform, runtime_backend="docker")
    expected = (int(state.get("generation") or 0), str(state.get("device_id") or ""))
    if expected != (spec.generation, spec.device_id):
        raise HTTPException(status_code=409, detail="EarnApp node assignment conflict")
    identity_asset_host_path: str | None = None
    if platform in {"macos", "ios"}:
        asset_kind = "mac_identity_profile" if platform == "macos" else "ios_identity_profile"
        payload = await _fetch_runtime_asset("earnapp", asset_kind, asset_id=slug)
        asset_root = _RUNTIME_ASSET_DIR / uuid.uuid4().hex
        asset_root.mkdir(parents=True, exist_ok=True)
        asset_path = asset_root / "asset"
        try:
            asset_path.write_bytes(base64.b64decode(payload, validate=True))
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=409, detail="EarnApp identity asset is invalid") from exc
        with contextlib.suppress(OSError):
            asset_path.chmod(0o644)
        identity_asset_host_path = str(_docker_host_path(asset_path))
    try:
        container_id = await asyncio.to_thread(
            orchestrator.recreate_earnapp_main,
            slug,
            identity_asset_host_path=identity_asset_host_path,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    state.update(container_id=container_id, runtime_status="running")
    _save_earnapp_state(slug, state)
    return {"status": "recreated", "container_id": container_id}


@app.post("/api/earnapp/docker-nodes/{slug}/restart")
async def api_restart_earnapp_docker_node(
    request: Request,
    slug: str,
    spec: EarnAppDockerNodeCasSpec,
) -> dict[str, Any]:
    """Restart one assigned main runtime without replacing its container."""
    _verify_api_key(request)
    state = _earnapp_node_state(slug)
    platform = str(state.get("platform") or "").strip().lower()
    _reject_earnapp_runtime_mutation(slug, platform=platform, runtime_backend="docker")
    expected = (int(state.get("generation") or 0), str(state.get("device_id") or ""))
    if expected != (spec.generation, spec.device_id):
        raise HTTPException(status_code=409, detail="EarnApp node assignment conflict")
    try:
        container_id = await asyncio.to_thread(orchestrator.restart_earnapp_main, slug)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    state.update(runtime_status="running", container_id=container_id)
    _save_earnapp_state(slug, state)
    return {"status": "restarted", "container_id": container_id}


@app.post("/api/earnapp/nodes/{logical_node_id}/proxy/apply")
@_serialize_earnapp_node_mutation
async def api_apply_earnapp_node_proxy(
    request: Request, logical_node_id: str, spec: EarnAppProxyApplySpec
) -> dict[str, Any]:
    """Stage one candidate proxy and require egress evidence before server CAS."""
    state = _earnapp_node_state(logical_node_id)
    _reject_earnapp_runtime_mutation(
        logical_node_id,
        platform=str(state.get("platform") or ""),
        runtime_backend=str(state.get("runtime_backend") or ""),
    )
    _validate_earnapp_proxy_cas(
        state,
        generation=spec.generation,
        device_id=spec.device_id,
        expected_proxy_id=spec.expected_proxy_id,
    )
    if state.get("pending_binding_version") not in (None, "", spec.binding_version):
        raise HTTPException(status_code=409, detail="EarnApp proxy binding already in progress")
    proxy_id = int(spec.proxy.get("proxy_id") or spec.proxy.get("id") or 0)
    expected_egress_ip = str(spec.proxy.get("exit_ip") or "").strip()
    backend = str(state.get("runtime_backend") or "docker").strip().lower()
    pending = (
        str(state.get("pending_binding_version") or ""),
        int(state.get("pending_proxy_id") or 0),
        str(state.get("pending_expected_egress_ip") or ""),
    )
    if pending[0]:
        if pending != (spec.binding_version, proxy_id, expected_egress_ip):
            raise HTTPException(status_code=409, detail="EarnApp proxy binding already in progress")
        observed = str(state.get("pending_observed_egress_ip") or "")
        if observed == expected_egress_ip:
            try:
                runtime_status, runtime_evidence = await _earnapp_proxy_runtime_snapshot(
                    logical_node_id,
                    state,
                    generation=spec.generation,
                    device_id=spec.device_id,
                )
                if (
                    str(runtime_status.get("binding_version") or "") != spec.binding_version
                    or runtime_status.get("candidate_present") is True
                    or runtime_evidence.get("running") is not True
                    or runtime_evidence.get("probe_ok") is not True
                    or str(runtime_evidence.get("observed_egress_ip") or "") != expected_egress_ip
                ):
                    raise HTTPException(status_code=409, detail="EarnApp proxy binding reconciliation required")
            except HTTPException:
                raise
            except (ValueError, RuntimeError, OSError) as exc:
                raise HTTPException(status_code=409, detail="EarnApp proxy binding reconciliation required") from exc
            return {
                "ok": True,
                "binding_version": spec.binding_version,
                "proxy_id": proxy_id,
                "observed_egress_ip": observed,
                "container_id": str(state.get("container_id") or ""),
                "idempotent": True,
            }
        raise HTTPException(status_code=409, detail="EarnApp proxy binding reconciliation required")
    state.update(
        pending_binding_version=spec.binding_version,
        pending_proxy_id=proxy_id,
        pending_expected_egress_ip=expected_egress_ip,
        pending_observed_egress_ip="",
    )
    _save_earnapp_state(logical_node_id, state)
    main_proxy_staged = False
    try:
        if backend == "lxd":
            result = await asyncio.to_thread(
                earnapp_lxd_runtime.apply_proxy_binding,
                logical_node_id,
                generation=spec.generation,
                device_id=spec.device_id,
                expected_proxy_id=spec.expected_proxy_id,
                binding_version=spec.binding_version,
                proxy=spec.proxy,
            )
        else:
            try:
                applied = await asyncio.to_thread(
                    orchestrator.apply_proxy_binding_batch, [logical_node_id], spec.proxy, spec.binding_version
                )
            except Exception as exc:  # noqa: BLE001 - Docker NotFound is the main-only signal
                if "sidecar" not in str(exc).lower() and exc.__class__.__name__.lower() != "notfound":
                    raise
                main_proxy_staged = True
                applied = await asyncio.to_thread(
                    orchestrator.stage_earnapp_main_proxy, logical_node_id, spec.proxy, spec.binding_version
                )
            if main_proxy_staged:
                evidence = await asyncio.to_thread(
                    orchestrator.wait_for_service_egress,
                    logical_node_id,
                    expected_egress_ip,
                )
            else:
                evidence = await asyncio.to_thread(orchestrator.probe_service_egress, logical_node_id)
            observed = str(evidence.get("observed_egress_ip") or "")
            if observed != expected_egress_ip:
                if main_proxy_staged:
                    await asyncio.to_thread(
                        orchestrator.finalize_earnapp_main_proxy,
                        logical_node_id,
                        spec.binding_version,
                        commit=False,
                    )
                else:
                    await asyncio.to_thread(
                        orchestrator.finalize_proxy_binding_batch,
                        [logical_node_id],
                        spec.binding_version,
                        commit=False,
                    )
                for key in (
                    "pending_binding_version",
                    "pending_proxy_id",
                    "pending_expected_egress_ip",
                    "pending_observed_egress_ip",
                ):
                    state.pop(key, None)
                state.update(proxy_health="unhealthy", proxy_health_reason="candidate_egress_mismatch")
                _save_earnapp_state(logical_node_id, state)
                raise HTTPException(status_code=409, detail="EarnApp candidate proxy egress mismatch")
            result = {
                "binding_version": spec.binding_version,
                "proxy_id": proxy_id,
                "observed_egress_ip": observed,
                "probe_ok": True,
                "applied_instances": list(applied.get("applied_instances") or []),
                "recreated_main_ids": dict(applied.get("recreated_main_ids") or {}),
            }
    except HTTPException:
        raise
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail="EarnApp proxy apply failed") from exc
    observed_egress_ip = str(result.get("observed_egress_ip") or "")
    if (
        str(result.get("binding_version") or "") != spec.binding_version
        or int(result.get("proxy_id") or 0) != proxy_id
        or observed_egress_ip != expected_egress_ip
    ):
        raise HTTPException(status_code=409, detail="EarnApp proxy apply acknowledgement mismatch")
    state["pending_observed_egress_ip"] = observed_egress_ip
    recreated = result.get("recreated_main_ids") if isinstance(result, dict) else None
    if isinstance(recreated, dict) and recreated.get(logical_node_id):
        state["container_id"] = str(recreated[logical_node_id])
    elif isinstance(result, dict) and result.get("container_id"):
        state["container_id"] = str(result["container_id"])
    _save_earnapp_state(logical_node_id, state)
    return {
        "ok": True,
        "binding_version": spec.binding_version,
        "proxy_id": proxy_id,
        "observed_egress_ip": observed_egress_ip,
        "container_id": str(state.get("container_id") or ""),
    }


@app.post("/api/earnapp/nodes/{logical_node_id}/proxy/finalize")
@_serialize_earnapp_node_mutation
async def api_finalize_earnapp_node_proxy(
    request: Request, logical_node_id: str, spec: EarnAppProxyFinalizeSpec
) -> dict[str, Any]:
    """Confirm or roll back the exact proxy binding staged for one node."""
    state = _earnapp_node_state(logical_node_id)
    _reject_earnapp_runtime_mutation(
        logical_node_id,
        platform=str(state.get("platform") or ""),
        runtime_backend=str(state.get("runtime_backend") or ""),
    )
    if _earnapp_proxy_finalize_replay(state, spec):
        return {
            "ok": True,
            "binding_version": spec.binding_version,
            "action": "confirmed",
            "proxy_id": spec.new_proxy_id,
            "idempotent": True,
        }
    _validate_earnapp_proxy_cas(
        state,
        generation=spec.generation,
        device_id=spec.device_id,
        expected_proxy_id=spec.expected_proxy_id,
    )
    pending = (
        str(state.get("pending_binding_version") or ""),
        int(state.get("pending_proxy_id") or 0),
    )
    if pending != (spec.binding_version, spec.new_proxy_id):
        raise HTTPException(status_code=409, detail="EarnApp proxy binding version conflict")
    backend = str(state.get("runtime_backend") or "docker").strip().lower()
    idempotent = False
    try:
        if backend == "lxd":
            result = await asyncio.to_thread(
                earnapp_lxd_runtime.finalize_proxy_binding,
                logical_node_id,
                generation=spec.generation,
                device_id=spec.device_id,
                expected_proxy_id=spec.expected_proxy_id,
                new_proxy_id=spec.new_proxy_id,
                binding_version=spec.binding_version,
                commit=spec.commit,
                expected_egress_ip=spec.expected_egress_ip,
                observed_egress_ip=spec.observed_egress_ip,
            )
        else:
            try:
                finalized = await asyncio.to_thread(
                    orchestrator.finalize_proxy_binding_batch,
                    [logical_node_id],
                    spec.binding_version,
                    commit=spec.commit,
                    expected_egress_ip=spec.expected_egress_ip
                    if spec.commit
                    else str(state.get("expected_egress_ip") or ""),
                )
            except Exception as exc:  # noqa: BLE001 - Docker NotFound is the main-only signal
                if "sidecar" not in str(exc).lower() and exc.__class__.__name__.lower() != "notfound":
                    raise
                finalized = await asyncio.to_thread(
                    orchestrator.finalize_earnapp_main_proxy, logical_node_id, spec.binding_version, commit=spec.commit
                )
            result = {
                "binding_version": spec.binding_version,
                "action": str(finalized.get("action") or ""),
                "proxy_id": spec.new_proxy_id if spec.commit else spec.expected_proxy_id,
            }
    except (ValueError, RuntimeError) as exc:
        if spec.commit:
            raise HTTPException(status_code=409, detail="EarnApp proxy finalization failed") from exc
        try:
            status, evidence = await _earnapp_proxy_runtime_snapshot(
                logical_node_id,
                state,
                generation=spec.generation,
                device_id=spec.device_id,
            )
            old_egress_ip = str(state.get("expected_egress_ip") or "").strip()
            if not _earnapp_proxy_rollback_complete(status, evidence, old_egress_ip):
                raise RuntimeError("EarnApp old proxy route is not authoritative")
            discarded = await _discard_earnapp_proxy_candidate(
                logical_node_id,
                state,
                generation=spec.generation,
                device_id=spec.device_id,
                expected_proxy_id=spec.expected_proxy_id,
                binding_version=spec.binding_version,
            )
        except (ValueError, RuntimeError, OSError) as cleanup_exc:
            raise HTTPException(status_code=409, detail="EarnApp proxy finalization failed") from cleanup_exc
        if (
            str(discarded.get("binding_version") or "") != spec.binding_version
            or str(discarded.get("action") or "") != "rolled_back"
        ):
            raise HTTPException(status_code=409, detail="EarnApp proxy finalization failed") from exc
        result = {**discarded, "proxy_id": spec.expected_proxy_id}
        idempotent = True
    expected_action = "confirmed" if spec.commit else "rolled_back"
    if str(result.get("action") or "") != expected_action:
        raise HTTPException(status_code=409, detail="EarnApp proxy finalization acknowledgement mismatch")
    if spec.commit:
        try:
            status, evidence = await _earnapp_proxy_runtime_snapshot(
                logical_node_id,
                state,
                generation=spec.generation,
                device_id=spec.device_id,
            )
        except (ValueError, RuntimeError, OSError, TimeoutError) as exc:
            raise HTTPException(status_code=409, detail="EarnApp proxy finalization failed") from exc
        if (
            str(status.get("binding_version") or "") != spec.binding_version
            or status.get("previous_present") is True
            or status.get("candidate_present") is True
            or evidence.get("running") is not True
            or evidence.get("probe_ok") is not True
            or str(evidence.get("observed_egress_ip") or "").strip() != spec.expected_egress_ip
        ):
            raise HTTPException(status_code=409, detail="EarnApp proxy finalization failed")
    if not spec.commit:
        try:
            status, evidence = await _earnapp_proxy_runtime_snapshot(
                logical_node_id,
                state,
                generation=spec.generation,
                device_id=spec.device_id,
            )
        except (ValueError, RuntimeError, OSError) as exc:
            raise HTTPException(status_code=409, detail="EarnApp proxy finalization failed") from exc
        old_egress_ip = str(state.get("expected_egress_ip") or "").strip()
        if not _earnapp_proxy_rollback_complete(status, evidence, old_egress_ip):
            raise HTTPException(status_code=409, detail="EarnApp proxy finalization failed")
    for key in (
        "pending_binding_version",
        "pending_proxy_id",
        "pending_expected_egress_ip",
        "pending_observed_egress_ip",
    ):
        state.pop(key, None)
    if spec.commit:
        state.update(
            proxy_id=spec.new_proxy_id,
            expected_egress_ip=spec.expected_egress_ip,
            observed_egress_ip=spec.observed_egress_ip,
            proxy_health="healthy",
            proxy_health_reason="",
            last_binding_version=spec.binding_version,
            last_binding_generation=spec.generation,
            last_binding_device_id=spec.device_id,
            last_binding_expected_proxy_id=spec.expected_proxy_id,
            last_binding_proxy_id=spec.new_proxy_id,
        )
    _save_earnapp_state(logical_node_id, state)
    response = {
        "ok": True,
        "binding_version": spec.binding_version,
        "action": expected_action,
        "proxy_id": spec.new_proxy_id if spec.commit else spec.expected_proxy_id,
    }
    if idempotent:
        response["idempotent"] = True
    return response


@app.post("/api/containers/{slug}/deploy")
async def api_deploy_container(request: Request, slug: str, spec: DeploySpec) -> dict[str, str]:
    """Deploy a container from spec sent by UI."""
    _verify_api_key(request)
    _reject_protected_runtime_alias(slug)
    runtime = provider_runtime.deployment_block(slug, spec.model_dump())
    if runtime:
        raise HTTPException(status_code=409, detail=runtime.policy_message)
    _validate_deploy_spec(spec, slug=slug)
    try:
        await _materialize_runtime_assets(slug, spec)
        container_id = await asyncio.to_thread(
            orchestrator.deploy_raw,
            slug=slug,
            provider_slug=spec.provider_slug,
            image=spec.image,
            env=spec.env,
            ports=spec.ports,
            volumes=spec.volumes,
            network_mode=spec.network_mode,
            cap_add=spec.cap_add,
            devices=spec.devices,
            # spec.privileged is rejected outright by _validate_deploy_spec above, and
            # deploy_raw no longer accepts it at all — containers are never privileged.
            command=spec.command,
            hostname=spec.hostname,
            labels=spec.labels,
            resources=spec.resources,
            runtime=spec.runtime,
            installer_manifest_url=spec.installer_manifest_url,
            installer_platform=spec.installer_platform,
            deploy_credentials=spec.deploy_credentials,
            user=spec.user,
            host_runtime=spec.host_runtime,
            image_delivery=spec.image_delivery,
            proxy=spec.proxy,
            sysctls=spec.sysctls,
            shm_size=spec.shm_size,
        )
        if (spec.provider_slug or slug) == "earnapp":
            proxy = dict(spec.proxy or {})
            expected_egress_ip = str(proxy.get("exit_ip") or "")
            _save_earnapp_state(
                str(spec.labels.get("cashpilot.earnapp.logical_node_id") or slug),
                {
                    "logical_node_id": str(spec.labels.get("cashpilot.earnapp.logical_node_id") or slug),
                    "generation": int(spec.labels.get("cashpilot.earnapp.generation") or 0),
                    "device_id": str(spec.labels.get("cashpilot.earnapp.device_id") or ""),
                    "platform": str(spec.labels.get("cashpilot.earnapp.platform") or "unknown"),
                    "runtime_backend": "docker",
                    "proxy_id": int(proxy.get("proxy_id") or proxy.get("id") or 0),
                    "expected_egress_ip": expected_egress_ip,
                    "observed_egress_ip": "",
                    "proxy_health": "unknown",
                    "proxy_health_reason": "",
                    "runtime_status": "running",
                    "container_id": container_id,
                    "evidence": {"running": True, "online": False},
                },
            )
        if (spec.provider_slug or slug) == "mysterium":
            try:
                await _sync_myst_wallet_after_deploy(spec.deploy_credentials, container_id)
            except Exception as exc:
                logger.warning("MYST wallet heartbeat failed after deploy: %s", exc)
        return {"status": "deployed", "container_id": container_id}
    except Exception:
        logger.exception("Deploy failed for %s", slug)
        raise HTTPException(status_code=500, detail="Container deployment failed")


@app.post("/api/proxy/probe-targets")
async def api_probe_proxy_targets(request: Request, spec: ProxyTargetProbeSpec) -> dict[str, Any]:
    _verify_api_key(request)
    if spec.targets and spec.targets != _DEFAULT_PROXY_PROBE_TARGETS:
        raise HTTPException(status_code=400, detail="custom proxy probe targets are not allowed")
    targets = _DEFAULT_PROXY_PROBE_TARGETS
    result = await _probe_proxy_targets(spec.proxy, targets)
    return {"ok": result["ok"], "results": result["results"]}


@app.post("/api/egress/bindings/apply")
async def api_apply_proxy_binding(request: Request, spec: ProxyBindingApplySpec) -> dict[str, Any]:
    _verify_api_key(request)
    _reject_protected_proxy_binding_instances(spec.instances)
    probe = await _probe_proxy_targets(spec.proxy, _PROXY_BINDING_PROBE_TARGETS)
    if not probe.get("ok"):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "proxy_unreachable_from_worker",
                "binding_version": spec.binding_version,
                "proxy_id": int(spec.proxy.get("proxy_id") or spec.proxy.get("id") or 0),
            },
        )
    try:
        applied = await asyncio.to_thread(
            orchestrator.apply_proxy_binding_batch,
            spec.instances,
            spec.proxy,
            spec.binding_version,
        )
    except (RuntimeError, ValueError) as exc:
        logger.warning("Proxy binding apply failed for %s: %s", spec.instances, exc)
        raise HTTPException(
            status_code=409,
            detail={
                "error": "proxy_binding_apply_failed",
                "binding_version": spec.binding_version,
                "proxy_id": int(spec.proxy.get("proxy_id") or spec.proxy.get("id") or 0),
            },
        ) from exc
    return {
        "ok": True,
        "binding_version": spec.binding_version,
        "proxy_id": int(spec.proxy.get("proxy_id") or spec.proxy.get("id") or 0),
        "observed_exit_ip": str(probe.get("observed_exit_ip") or ""),
        "applied_instances": list(applied.get("applied_instances") or []),
        "config_sha256": str(applied.get("config_sha256") or ""),
    }


class ProxyBindingFinalizeSpec(BaseModel):
    binding_version: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    instances: list[str] = Field(min_length=1, max_length=256)
    commit: bool = True


@app.post("/api/egress/bindings/finalize")
async def api_finalize_proxy_binding(request: Request, spec: ProxyBindingFinalizeSpec) -> dict[str, Any]:
    _verify_api_key(request)
    _reject_protected_proxy_binding_instances(spec.instances)
    try:
        result = await asyncio.to_thread(
            orchestrator.finalize_proxy_binding_batch,
            spec.instances,
            spec.binding_version,
            commit=spec.commit,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "proxy_binding_finalize_failed", "binding_version": spec.binding_version},
        ) from exc
    return {
        "ok": True,
        "binding_version": spec.binding_version,
        "action": str(result.get("action") or ""),
        "finalized_instances": list(result.get("finalized_instances") or []),
    }


@app.post("/api/containers/{slug}/restart")
async def api_restart_container(request: Request, slug: str) -> dict[str, str]:
    _verify_api_key(request)
    _reject_protected_runtime_alias(slug)
    if provider_runtime.is_runtime_instance(slug):
        raise HTTPException(status_code=409, detail="Existing EarnApp runtimes are inspection-only")
    try:
        await asyncio.to_thread(orchestrator.restart_service, slug)
        return {"status": "restarted"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/api/containers/{slug}/stop")
async def api_stop_container(request: Request, slug: str) -> dict[str, str]:
    _verify_api_key(request)
    _reject_protected_runtime_alias(slug)
    if provider_runtime.is_runtime_instance(slug):
        raise HTTPException(status_code=409, detail="Existing EarnApp runtimes are inspection-only")
    try:
        await asyncio.to_thread(orchestrator.stop_service, slug)
        return {"status": "stopped"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/api/containers/{slug}/start")
async def api_start_container(request: Request, slug: str) -> dict[str, str]:
    _verify_api_key(request)
    _reject_protected_runtime_alias(slug)
    if provider_runtime.is_runtime_instance(slug):
        raise HTTPException(status_code=409, detail="Existing EarnApp runtimes are inspection-only")
    try:
        await asyncio.to_thread(orchestrator.start_service, slug)
        return {"status": "started"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.delete("/api/containers/{slug}")
async def api_remove_container(
    request: Request,
    slug: str,
    delete_volumes: bool = False,
    allow_delete_critical: bool = False,
) -> dict[str, Any]:
    _verify_api_key(request)
    _reject_protected_runtime_alias(slug)
    if provider_runtime.is_runtime_instance(slug):
        raise HTTPException(status_code=409, detail="Existing EarnApp runtimes are inspection-only")
    try:
        result = await asyncio.to_thread(
            orchestrator.remove_service,
            slug,
            delete_volumes=delete_volumes,
            allow_delete_critical=allow_delete_critical,
        )
        return {"status": "removed", **result}
    except orchestrator.CriticalVolumeError as exc:
        # 409, not 400: the request is well-formed, the state is what refuses.
        # The container is left running - nothing has been destroyed yet.
        raise HTTPException(
            status_code=409,
            detail={
                "error": "critical_volume",
                "message": str(exc),
                "blocked": exc.blocked,
                "hint": (
                    "Nothing was removed. Back up the listed volumes first. To proceed "
                    "anyway, repeat the request with allow_delete_critical=true."
                ),
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/containers/{slug}/logs")
async def api_container_logs(request: Request, slug: str, lines: int = 50) -> dict[str, str]:
    _verify_api_key(request)
    try:
        logs = await asyncio.to_thread(orchestrator.get_service_logs, slug, lines=min(lines, 1000))
        return {"logs": logs}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


class BackupRequest(BaseModel):
    """Target for an export. Exactly one of the two must be supplied.

    A passphrase arrives, is used to derive a key, and is discarded with the
    request. It is never written to disk, never logged, and never returned.
    """

    passphrase: str | None = None
    recipient_public_key: str | None = None


class VerifyRequest(BackupRequest):
    """A bundle to check against the state currently on disk.

    Recipient-mode verification needs the PRIVATE half — decryption happens in
    memory on the worker and the key is discarded with the request. This is the
    one moment recipient mode is not key-free, so the field says so rather than
    letting someone paste a private key into something named `_public_key`
    without noticing what they just did. Verify from a host you trust, or use
    passphrase mode if that is not acceptable.
    """

    bundle_b64: str = ""
    recipient_private_key: str | None = None


@app.post("/api/containers/{slug}/backup")
async def api_backup(slug: str, body: BackupRequest, request: Request) -> dict[str, Any]:
    """Export this service's irreplaceable state, encrypted HERE.

    Encryption happens on the worker so the UI only ever handles ciphertext:
    plaintext key material must not cross the wire even inside the fleet, and it
    must not sit in the UI's memory where a different compromise would reach it.

    The bundle is returned in THIS response and nowhere else. There is
    deliberately no upload, sync or webhook path in the code — the absence is
    what makes the guarantee checkable, rather than a policy nobody audits.
    """
    _verify_api_key(request)
    try:
        payload, targets = await asyncio.to_thread(orchestrator.read_critical_state, slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Backup read failed for %s: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Could not read this service's state") from exc

    try:
        bundle = await asyncio.to_thread(
            lambda: state_backup.seal(
                payload,
                passphrase=body.passphrase,
                recipient_public_key=body.recipient_public_key,
                metadata={"slug": slug, "worker": WORKER_NAME, "targets": targets},
            )
        )
    except state_backup.BackupError as exc:
        # Safe to surface: these messages are about the CALLER's inputs and
        # deliberately contain neither the passphrase nor any state.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "slug": slug,
        "targets": targets,
        "bytes": len(bundle),
        "bundle_b64": base64.b64encode(bundle).decode("ascii"),
    }


@app.post("/api/containers/{slug}/backup/verify")
async def api_backup_verify(slug: str, body: VerifyRequest, request: Request) -> dict[str, Any]:
    """Does this bundle still match what is on disk?

    "I have a backup file" and "I have a backup that works" are different
    claims. Believing the first is how people find a dead node and an unusable
    file on the same afternoon.

    Decryption happens in memory on the worker and nothing is written anywhere;
    only digests are compared, so no plaintext is produced for the caller.
    """
    _verify_api_key(request)
    try:
        bundle = base64.b64decode(body.bundle_b64 or "", validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Bundle is not valid base64") from exc
    if not state_backup.looks_like_bundle(bundle):
        raise HTTPException(status_code=400, detail="That file is not a CashPilot backup bundle")

    try:
        payload, _targets = await asyncio.to_thread(orchestrator.read_critical_state, slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Backup verify read failed for %s: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Could not read this service's state") from exc

    return await asyncio.to_thread(
        lambda: state_backup.verify(
            bundle,
            payload,
            passphrase=body.passphrase,
            recipient_private_key=body.recipient_private_key,
        )
    )


@app.get("/api/runtimes")
async def api_runtimes(request: Request) -> dict[str, Any]:
    """Container runtimes this host actually provides.

    Advanced and unsupported. CashPilot never selects one: the default runtime
    is what every service is tested against, and the alternatives cost real
    throughput on a workload that is pure network I/O.
    """
    _verify_api_key(request)
    available = sorted(await asyncio.to_thread(orchestrator.available_runtimes))
    return {
        "available": available,
        "default": None,
        "supported": False,
        "note": (
            "Selecting a non-default runtime is an advanced, unsupported choice. It is not a "
            "hardening recommendation — see the docs for why."
        ),
    }


@app.get("/api/health")
async def api_health() -> dict[str, str]:
    """Health check endpoint (no auth required)."""
    return {"status": "ok", "worker": WORKER_NAME}


@app.get("/api/egress/status")
async def api_egress_status(request: Request) -> dict[str, Any]:
    _verify_api_key(request)
    return {"configured": _EGRESS_CONFIG_FILE.is_file(), "path": str(_EGRESS_CONFIG_FILE)}


@app.post("/api/egress/apply")
async def api_egress_apply(request: Request, body: EgressApplySpec) -> dict[str, Any]:
    _verify_api_key(request)
    _EGRESS_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    mode = proxy_egress.choose_mode(body.mode, body.service_udp, body.proxy)
    if mode == proxy_egress.DIRECT or not body.proxy:
        config = {
            "log": {"level": "info"},
            "inbounds": [],
            "outbounds": [{"type": "direct", "tag": "direct"}],
            "route": {"final": "direct"},
        }
    else:
        config = singbox_config.render_tun_proxy_config(body.proxy, worker_name=body.worker_name or WORKER_NAME)
    _EGRESS_CONFIG_FILE.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")
    with contextlib.suppress(OSError):
        _EGRESS_CONFIG_FILE.chmod(0o600)
    return {"status": "ok", "mode": mode, "path": str(_EGRESS_CONFIG_FILE)}
