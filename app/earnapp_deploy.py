"""Sequential EarnApp node planning, provisioning, and worker dispatch."""

from __future__ import annotations

import logging
import secrets
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from app import database, earnapp_canary, earnapp_identity, earnapp_policy, earnapp_runtime

logger = logging.getLogger(__name__)

DockerDeploy = Callable[[int, str, dict[str, Any]], Awaitable[dict[str, Any]]]
LxdDeploy = Callable[[int, str, dict[str, Any]], Awaitable[dict[str, Any]]]
VerifyNode = Callable[[str], Awaitable[Mapping[str, Any]]]
PlatformChoice = Callable[[], str]


@dataclass(frozen=True)
class EarnAppNodePlan:
    worker_id: int
    slot_id: str
    logical_node_id: str


@dataclass
class PreparedEarnAppNode:
    worker_id: int
    slot_id: str
    logical_node_id: str
    platform: str
    account_id: int
    device_id: str
    generation: int
    proxy: dict[str, Any] = field(repr=False)
    identity: dict[str, Any] = field(default_factory=dict, repr=False)
    identity_asset_id: str = ""

    @classmethod
    def from_plan(
        cls,
        plan: EarnAppNodePlan,
        *,
        platform: str,
        account_id: int,
        device_id: str,
        proxy: Mapping[str, Any],
        generation: int = 1,
        identity: Mapping[str, Any] | None = None,
        identity_asset_id: str = "",
    ) -> PreparedEarnAppNode:
        return cls(
            worker_id=plan.worker_id,
            slot_id=plan.slot_id,
            logical_node_id=plan.logical_node_id,
            platform=str(platform).strip().lower(),
            account_id=int(account_id),
            device_id=str(device_id),
            generation=max(1, int(generation)),
            proxy=dict(proxy),
            identity=dict(identity or {}),
            identity_asset_id=identity_asset_id or plan.logical_node_id,
        )


def _slot_id(value: Any, index: int) -> str:
    raw = value.get("slot_id") if isinstance(value, Mapping) else value
    text = str(raw or f"ipv4-{index:03d}").strip().lower()
    if not __import__("re").fullmatch(r"ipv4-\d{3,6}", text):
        raise ValueError("invalid EarnApp public IPv4 slot")
    return text


def plan_worker_nodes(worker_id: int, public_ipv4_slots: int | list[Any] | tuple[Any, ...]) -> list[EarnAppNodePlan]:
    """Build deterministic one-node-per-ready-slot plans without mutating state."""
    if int(worker_id) <= 0:
        raise ValueError("invalid EarnApp worker id")
    if isinstance(public_ipv4_slots, int):
        if public_ipv4_slots < 0:
            raise ValueError("public IPv4 slot count cannot be negative")
        raw_slots: list[Any] = [f"ipv4-{index:03d}" for index in range(1, public_ipv4_slots + 1)]
    else:
        raw_slots = list(public_ipv4_slots or [])
    seen: set[str] = set()
    slots: list[str] = []
    for index, raw in enumerate(raw_slots, start=1):
        if isinstance(raw, Mapping) and raw.get("route_ready") is False:
            continue
        slot = _slot_id(raw, index)
        if slot not in seen:
            seen.add(slot)
            slots.append(slot)
    slots.sort(key=lambda item: int(item.split("-", 1)[1]))
    return [EarnAppNodePlan(int(worker_id), slot, f"earnapp-proxy-w{int(worker_id)}-{slot}") for slot in slots]


async def target_worker_plans(
    worker_id: int, public_ipv4_slots: int | list[Any] | tuple[Any, ...]
) -> list[EarnAppNodePlan]:
    """Return retryable deterministic nodes while reserving legacy capacity."""
    plans = plan_worker_nodes(worker_id, public_ipv4_slots)
    if not plans:
        return []
    nodes = await database.list_earnapp_logical_nodes()
    planned_ids = {plan.logical_node_id for plan in plans}
    assigned = [
        node
        for node in nodes
        if int(node.get("assigned_worker_id") or 0) == int(worker_id) and str(node.get("state") or "") != "RETIRED"
    ]
    legacy_count = sum(1 for node in assigned if str(node.get("logical_node_id") or "") not in planned_ids)
    deterministic_nodes = {
        str(node.get("logical_node_id") or ""): node
        for node in nodes
        if str(node.get("logical_node_id") or "") in planned_ids and str(node.get("state") or "") != "RETIRED"
    }
    instances = {
        str(instance.get("instance_id") or ""): instance
        for instance in await database.list_provider_instances(slug="earnapp", worker_id=int(worker_id))
    }
    retry_ids: set[str] = set()
    for node_id, node in deterministic_nodes.items():
        assigned_worker_id = int(node.get("assigned_worker_id") or 0)
        if assigned_worker_id not in {0, int(worker_id)}:
            continue
        state = str(node.get("state") or "").upper()
        if state not in {"PLANNED", "ACTIVE"}:
            continue
        status = str((instances.get(node_id) or {}).get("status") or "").lower()
        if status not in {"running", "deployed"}:
            retry_ids.add(node_id)

    capacity = max(0, len(plans) - legacy_count)
    available_new = max(0, capacity - len(deterministic_nodes))
    new_ids = {plan.logical_node_id for plan in plans if plan.logical_node_id not in deterministic_nodes}
    selected_new_ids = set(
        list(node_id for node_id in (plan.logical_node_id for plan in plans) if node_id in new_ids)[:available_new]
    )
    return [plan for plan in plans if plan.logical_node_id in retry_ids or plan.logical_node_id in selected_new_ids]


def _platform_for_country(country_code: str, chooser: PlatformChoice) -> str:
    country = str(country_code or "").strip().upper()
    if len(country) != 2:
        raise ValueError("EarnApp proxy country is required")
    if country == "VN":
        selected = str(chooser() or "").strip().lower()
        if selected not in {"macos", "ios"}:
            raise ValueError("EarnApp VN platform choice is invalid")
        return selected
    return "ubuntu"


def _platform_country_filter(platform: str) -> tuple[str, str]:
    selected = str(platform or "").strip().lower()
    if selected in {"macos", "ios"}:
        return "VN", ""
    if selected == "ubuntu":
        return "", "VN"
    return "", ""


async def _proxy_for_id(proxy_id: int) -> dict[str, Any]:
    proxy = await database.get_proxy_endpoint(int(proxy_id))
    if not proxy:
        raise RuntimeError("EarnApp leased proxy disappeared")
    # Endpoint reads use ``id`` while lease payloads use ``proxy_id``.
    proxy.setdefault("proxy_id", int(proxy_id))
    return proxy


async def prepare_node(
    plan: EarnAppNodePlan,
    *,
    vn_platform_choice: PlatformChoice | None = None,
    required_platform: str | None = None,
) -> PreparedEarnAppNode:
    """Bind an account, exclusive proxy, immutable platform, and identity."""
    if earnapp_policy.is_protected_logical_node(plan.logical_node_id):
        raise RuntimeError("protected EarnApp node is inspection-only")
    node = await database.get_earnapp_logical_node(plan.logical_node_id)
    if not node:
        await database.assign_earnapp_account(plan.logical_node_id)
        node = await database.get_earnapp_logical_node(plan.logical_node_id)
    if not node:
        raise RuntimeError("EarnApp logical node could not be created")
    existing_platform = str(node.get("platform") or "").strip().lower()
    if existing_platform == "unknown":
        existing_platform = ""
    required = str(required_platform or "").strip().lower()
    if required and required not in earnapp_identity.SUPPORTED_PLATFORMS:
        raise ValueError("EarnApp required platform is invalid")
    if existing_platform and required and existing_platform != required:
        raise RuntimeError("EarnApp logical node platform is disabled by runtime policy")
    requested_country, excluded_country = _platform_country_filter(existing_platform or required)

    lease: dict[str, Any] | None = None
    active = await database.get_active_provider_proxy_lease("earnapp", plan.worker_id, plan.logical_node_id)
    if active:
        lease = await database.lease_proxy_for_provider_instance(
            "earnapp",
            plan.worker_id,
            plan.logical_node_id,
            country_code=requested_country,
            exclude_country_code=excluded_country,
        )
        if not lease:
            raise RuntimeError("EarnApp node proxy is unhealthy and requires isolated rotation")
    else:
        control = await database.get_earnapp_account_control_route(int(node["account_id"]), healthy_only=True)
        if control:
            control_country = str(control.get("country_code") or "").strip().upper()
            if (requested_country and control_country != requested_country) or (
                excluded_country and control_country == excluded_country
            ):
                await database.release_earnapp_account_control_route(
                    int(node["account_id"]),
                    expected_proxy_id=int(control["proxy_id"]),
                    reason="EARNAPP_PLATFORM_COUNTRY_MISMATCH",
                )
                control = None
        if control:
            transferred = await database.transfer_earnapp_control_route_to_node(
                int(node["account_id"]),
                plan.logical_node_id,
                worker_id=plan.worker_id,
                country_code=str(control.get("country_code") or "").upper(),
            )
            if transferred:
                lease = await _proxy_for_id(int(transferred["proxy_id"]))
        if not lease:
            lease = await database.lease_proxy_for_provider_instance(
                "earnapp",
                plan.worker_id,
                plan.logical_node_id,
                country_code=requested_country,
                exclude_country_code=excluded_country,
            )
    if not lease:
        raise RuntimeError("no eligible residential EarnApp proxy available")

    country = str(lease.get("country_code") or "").strip().upper()
    platform = (
        existing_platform
        or required
        or _platform_for_country(country, vn_platform_choice or (lambda: secrets.choice(("macos", "ios"))))
    )
    if platform in {"macos", "ios"} and country != "VN":
        raise RuntimeError("EarnApp Mac/iOS node requires a VN proxy")
    if platform == "ubuntu" and country == "VN":
        raise RuntimeError("EarnApp Ubuntu node requires a non-VN proxy")
    if existing_platform and existing_platform != platform:
        raise RuntimeError("EarnApp logical node platform is immutable")
    await database.assign_earnapp_account(plan.logical_node_id, platform=platform)
    profile = await earnapp_identity.ensure_identity_profile(plan.logical_node_id, platform)
    if platform == "ubuntu":
        identity = earnapp_identity.validate_and_decode_ubuntu_profile(profile["value"])
    else:
        identity = earnapp_identity.decrypt_profile(profile["value"], platform)
    current = await database.get_earnapp_logical_node(plan.logical_node_id)
    generation = int(current.get("generation") or 1) if current else 1
    if not current or int(current.get("current_proxy_id") or 0) != int(lease["proxy_id"]):
        await database.bind_earnapp_node_runtime(
            plan.logical_node_id,
            plan.worker_id,
            device_id=profile["device_id"],
            proxy_id=int(lease["proxy_id"]),
        )
        current = await database.get_earnapp_logical_node(plan.logical_node_id)
        generation = int(current.get("generation") or generation) if current else generation
    return PreparedEarnAppNode.from_plan(
        plan,
        platform=platform,
        account_id=int(current["account_id"] if current else node["account_id"]),
        device_id=profile["device_id"],
        proxy=lease,
        generation=generation,
        identity=identity,
        identity_asset_id=profile["asset_id"],
    )


def _transport_spec(node: PreparedEarnAppNode, *, lxd_settings: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if node.platform == "ubuntu":
        settings = dict(lxd_settings or {})
        cpu = int(settings.get("cpu", 1) or 1)
        memory = int(settings.get("memory_mib", 1024) or 1024)
        return {
            "logical_node_id": node.logical_node_id,
            "generation": node.generation,
            "account_id": node.account_id,
            "device_id": node.device_id,
            "identity": node.identity,
            "proxy_id": int(node.proxy["proxy_id"]),
            "proxy": dict(node.proxy),
            "lxd_cpu": cpu,
            "lxd_memory_mib": memory,
        }
    spec = earnapp_canary.build_runtime_spec(
        node.logical_node_id,
        node.account_id,
        node.platform,
        node.device_id,
        node.proxy,
        generation=node.generation,
        identity_asset_id=node.identity_asset_id,
    )
    spec["proxy"] = earnapp_canary._proxy_metadata(node.proxy)
    return spec


def _persisted_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    return earnapp_runtime.redacted_evidence(dict(spec))


def _verification_ok(evidence: Mapping[str, Any] | None, *, device_id: str = "") -> bool:
    """Accept only authenticated workload evidence for this exact node."""
    if not isinstance(evidence, Mapping):
        return False
    if evidence.get("authenticated") is not True:
        return False
    if evidence.get("device_present") is not True or evidence.get("online") is not True:
        return False
    if evidence.get("banned") is True:
        return False
    observed_device = str(evidence.get("device_id") or "").strip()
    if not observed_device:
        return False
    if device_id and observed_device != device_id:
        return False
    return str(evidence.get("workload_state") or "").strip().lower() == "workload_verified"


def _spec_device_id(spec: Mapping[str, Any] | None) -> str:
    if not isinstance(spec, Mapping):
        return ""
    direct = str(spec.get("device_id") or "").strip()
    env = spec.get("env") if isinstance(spec.get("env"), Mapping) else {}
    return direct or str(env.get("EARNAPP_DEVICE_ID") or "").strip()


async def _default_verify_node(logical_node_id: str) -> Mapping[str, Any]:
    """Use the account-scoped dashboard verifier for every production deploy."""
    return await earnapp_canary.verify_canary(logical_node_id)


async def deploy_worker_nodes_sequentially(
    worker_id: int,
    public_ipv4_slots: int | list[Any] | tuple[Any, ...],
    *,
    docker_deploy: DockerDeploy,
    lxd_deploy: LxdDeploy,
    lxd_settings: Mapping[str, Any] | None = None,
    vn_platform_choice: PlatformChoice | None = None,
    verify_node: VerifyNode | None = None,
    required_platform: str | None = None,
) -> dict[str, list[str]]:
    """Deploy each planned node in order and require authenticated online evidence."""
    verifier = verify_node or _default_verify_node
    outcome: dict[str, list[str]] = {
        "deployed": [],
        "verified": [],
        "skipped": [],
        "pending": [],
        "failed": [],
    }
    for plan in await target_worker_plans(worker_id, public_ipv4_slots):
        prepared_node: PreparedEarnAppNode | None = None
        required = str(required_platform or "").strip().lower()
        if required:
            logical_node = await database.get_earnapp_logical_node(plan.logical_node_id)
            existing_platform = str((logical_node or {}).get("platform") or "unknown").strip().lower()
            if existing_platform not in {"", "unknown", required}:
                outcome["skipped"].append(plan.logical_node_id)
                continue
        existing = await database.get_provider_instance(plan.logical_node_id)
        if (
            existing
            and int(existing.get("worker_id") or 0) == int(worker_id)
            and str(existing.get("status") or "").lower() in {"running", "deployed", "verification_pending"}
        ):
            existing_spec = await database.get_provider_instance_spec(plan.logical_node_id)
            existing_evidence = (existing_spec or {}).get("earnapp_device_verification")
            expected_device_id = _spec_device_id(existing_spec)
            if _verification_ok(existing_evidence, device_id=expected_device_id):
                outcome["skipped"].append(plan.logical_node_id)
                outcome["verified"].append(plan.logical_node_id)
                continue
            try:
                evidence = earnapp_runtime.redacted_evidence(dict(await verifier(plan.logical_node_id)))
            except Exception as exc:  # noqa: BLE001 - verification is retryable
                logger.warning("EarnApp node %s verification unavailable: %s", plan.logical_node_id, type(exc).__name__)
                evidence = {"status": "pending", "error_kind": "verification_unavailable"}
            merged_spec = dict(existing_spec or {})
            merged_spec["earnapp_device_verification"] = evidence
            await database.save_provider_instance(
                "earnapp",
                plan.logical_node_id,
                worker_id=worker_id,
                mode=str(existing.get("mode") or "proxy"),
                container_id=str(existing.get("container_id") or "remote"),
                sidecar_id=str(existing.get("sidecar_id") or ""),
                proxy_id=int(existing.get("proxy_id") or 0) or None,
                status="running"
                if _verification_ok(evidence, device_id=expected_device_id)
                else "verification_pending",
                spec=_persisted_spec(merged_spec),
            )
            if _verification_ok(evidence, device_id=expected_device_id):
                outcome["skipped"].append(plan.logical_node_id)
                outcome["verified"].append(plan.logical_node_id)
            else:
                outcome["pending"].append(plan.logical_node_id)
            continue
        try:
            node = await prepare_node(
                plan,
                vn_platform_choice=vn_platform_choice,
                required_platform=required or None,
            )
            prepared_node = node
            spec = _transport_spec(node, lxd_settings=lxd_settings)
            if node.platform == "ubuntu":
                result = await lxd_deploy(worker_id, node.logical_node_id, spec)
            else:
                result = await docker_deploy(worker_id, node.logical_node_id, spec)
            container_id = str(result.get("container_id") or result.get("instance_id") or "remote")
            try:
                evidence = earnapp_runtime.redacted_evidence(dict(await verifier(node.logical_node_id)))
            except Exception as exc:  # noqa: BLE001 - verification is retryable
                logger.warning("EarnApp node %s verification unavailable: %s", node.logical_node_id, type(exc).__name__)
                evidence = {"status": "pending", "error_kind": "verification_unavailable"}
            persisted_spec = _persisted_spec(spec)
            persisted_spec["earnapp_device_verification"] = evidence
            verified = _verification_ok(evidence, device_id=node.device_id)
            await database.save_provider_instance(
                "earnapp",
                node.logical_node_id,
                worker_id=worker_id,
                mode="proxy",
                container_id=container_id,
                proxy_id=int(node.proxy["proxy_id"]),
                status="running" if verified else "verification_pending",
                spec=persisted_spec,
            )
            if verified:
                outcome["deployed"].append(node.logical_node_id)
                outcome["verified"].append(node.logical_node_id)
            else:
                outcome["pending"].append(node.logical_node_id)
        except Exception as exc:  # noqa: BLE001 - isolate one node from the queue
            outcome["failed"].append(plan.logical_node_id)
            with_context: dict[str, Any] = {
                "logical_node_id": plan.logical_node_id,
                "worker_id": int(worker_id),
                "error_type": type(exc).__name__,
            }
            proxy_id: int | None = None
            if prepared_node is not None:
                proxy_id = int(prepared_node.proxy.get("proxy_id") or 0) or None
                with_context.update(
                    platform=prepared_node.platform,
                    account_id=prepared_node.account_id,
                    device_id=prepared_node.device_id,
                    generation=prepared_node.generation,
                    proxy_id=proxy_id or 0,
                )
            with suppress(Exception):
                await database.save_provider_instance(
                    "earnapp",
                    plan.logical_node_id,
                    worker_id=worker_id,
                    mode="proxy",
                    proxy_id=proxy_id,
                    status="failed",
                    spec=with_context,
                )
    return outcome
