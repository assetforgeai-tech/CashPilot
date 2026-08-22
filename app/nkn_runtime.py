"""Worker-local lifecycle for official direct NKN nodes.

NKN is intentionally isolated from the generic provider deploy path. The
server supplies an already-authorized wallet assignment; this module owns the
small, deterministic Docker contract needed to turn one bootstrap IP slot into
one node without changing other provider behavior.
"""

from __future__ import annotations

import io
import json
import re
import tarfile
import uuid
from collections.abc import Mapping
from contextlib import suppress
from typing import Any

from docker.errors import NotFound

IMAGE = "nknorg/nkn:latest"
DATA_TARGET = "/nkn/data"
PORTS = tuple(range(30000, 30006))
NANO_CPUS = 1_000_000_000
MEM_LIMIT = "1g"
PIDS_LIMIT = 512
_SLOT_RE = re.compile(r"^ipv4-\d{3,6}$")
_ADDRESS_RE = re.compile(r"^NKN[1-9A-HJ-NP-Za-km-z]{8,}$")


class NknAssignmentConflict(RuntimeError):
    """An existing node/volume belongs to a different wallet assignment."""


def instance_id(slot_id: str) -> str:
    if not _SLOT_RE.fullmatch(str(slot_id or "")):
        raise ValueError("invalid NKN slot id")
    return f"nkn-direct-{slot_id}"


def volume_name(slot_id: str) -> str:
    if not _SLOT_RE.fullmatch(str(slot_id or "")):
        raise ValueError("invalid NKN slot id")
    return f"cashpilot-nkn-{slot_id}-data"


def _required_text(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"NKN {field} is required")
    return text


def _wallet_address(wallet_json: str) -> str:
    try:
        payload = json.loads(wallet_json)
    except json.JSONDecodeError as exc:
        raise ValueError("NKN wallet JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("NKN wallet JSON must be an object")
    address = str(payload.get("Address") or payload.get("address") or "").strip()
    if not address:
        raise ValueError("NKN wallet address is missing")
    return address


def _validate_address(value: object, field: str) -> str:
    address = _required_text(value, field)
    # Keep compatibility with wallet fixtures and future test networks while
    # rejecting accidental secrets/URLs. Mainnet addresses always begin NKN.
    if not address.startswith("NKN") or not _ADDRESS_RE.fullmatch(address):
        raise ValueError(f"NKN {field} is not a valid address")
    return address


def _tar_entry(name: str, payload: bytes, mode: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mode = mode
    info.uid = 0
    info.gid = 0
    return info


def seed_archive(wallet_json: str, wallet_pswd: str, beneficiary_address: str) -> bytes:
    """Build a secret-bearing archive only in memory for Docker volume seeding."""
    wallet_json = _required_text(wallet_json, "wallet_json")
    wallet_pswd = _required_text(wallet_pswd, "wallet_pswd")
    _wallet_address(wallet_json)
    beneficiary = _validate_address(beneficiary_address, "beneficiary_address")
    config = {
        "BeneficiaryAddr": beneficiary,
        "beneficiaryAddr": beneficiary,
        "SyncMode": "light",
        "PasswordFile": "wallet.pswd",
        # Keep the official light-node config within the 1 GiB container cap.
        # The image otherwise sizes sync caches from host RAM, not its cgroup.
        "SyncStateMaxThread": 8,
        "SyncHeaderMaxMemorySize": 8,
        "SyncBatchWindowSize": 8,
        "SyncBlocksMaxMemorySize": 32,
        "TxPoolMaxMemorySize": 8,
        "ClientMsgCacheSize": 8,
    }
    files = {
        "config.json": (json.dumps(config, indent=2).encode("utf-8"), 0o644),
        "wallet.json": (wallet_json.encode("utf-8"), 0o600),
        "wallet.pswd": (wallet_pswd.encode("utf-8"), 0o600),
    }
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:") as archive:
        for name in ("config.json", "wallet.json", "wallet.pswd"):
            payload, mode = files[name]
            archive.addfile(_tar_entry(name, payload, mode), io.BytesIO(payload))
    return output.getvalue()


def _assignment_labels(assignment: Mapping[str, Any]) -> dict[str, str]:
    wallet_id = int(assignment.get("wallet_id") or 0)
    version = int(assignment.get("wallet_assignment_version") or 0)
    client_id = _required_text(assignment.get("lease_client_id"), "lease_client_id")
    if wallet_id <= 0 or version <= 0:
        raise ValueError("NKN wallet assignment id/version is invalid")
    return {
        "cashpilot.nkn.wallet_id": str(wallet_id),
        "cashpilot.nkn.wallet_assignment_version": str(version),
        "cashpilot.nkn.lease_client_id": client_id,
    }


def _same_assignment(labels: Mapping[str, Any] | None, expected: Mapping[str, str]) -> bool:
    labels = labels or {}
    return all(str(labels.get(key) or "") == value for key, value in expected.items())


def _slot_value(slot: Mapping[str, Any], key: str) -> str:
    return _required_text(slot.get(key), f"slot.{key}")


def _assert_slot(slot: Mapping[str, Any]) -> tuple[str, str, str, str]:
    slot_id = _slot_value(slot, "slot_id")
    if not _SLOT_RE.fullmatch(slot_id):
        raise ValueError("invalid NKN slot id")
    if slot.get("route_ready") is not True:
        raise ValueError("NKN slot is not route-ready")
    public_ip = _slot_value(slot, "public_ip")
    private_ip = _slot_value(slot, "private_ip")
    network = _slot_value(slot, "docker_network")
    if network != f"cashpilot-direct-{slot_id}":
        raise ValueError("NKN slot network does not match slot id")
    return slot_id, public_ip, private_ip, network


def _seed_volume(client: Any, image: str, volume: Any, archive: bytes, name: str) -> None:
    helper_name = f"{name}-seed-{uuid.uuid4().hex[:12]}"
    helper = client.containers.create(
        image=image,
        name=helper_name,
        entrypoint=["/bin/sh", "-c"],
        command=["sleep 60"],
        volumes={volume.name: {"bind": DATA_TARGET, "mode": "rw"}},
        network_mode="none",
        labels={"cashpilot.managed": "true", "cashpilot.nkn.role": "seed"},
    )
    helper.start()
    try:
        if not helper.put_archive(DATA_TARGET, archive):
            raise RuntimeError("NKN wallet/config seed failed")
    finally:
        with suppress(Exception):
            helper.remove(force=True)


def deploy_slot(slot: Mapping[str, Any], assignment: Mapping[str, Any], *, client: Any) -> dict[str, str]:
    """Seed and start one official NKN node for one public-IP slot."""
    slot_id, public_ip, private_ip, network = _assert_slot(slot)
    name = instance_id(slot_id)
    volume = volume_name(slot_id)
    labels = {
        "cashpilot.managed": "true",
        "cashpilot.provider": "nkn",
        "cashpilot.instance_id": name,
        "cashpilot.instance_mode": "direct",
        "cashpilot.nkn.slot_id": slot_id,
        "cashpilot.nkn.public_ip": public_ip,
        **_assignment_labels(assignment),
    }
    try:
        client.networks.get(network)
    except NotFound as exc:
        raise ValueError(f"NKN slot network {network!r} is not prepared") from exc

    try:
        existing = client.containers.get(name)
    except NotFound:
        existing = None
    if existing is not None:
        assignment_labels = _assignment_labels(assignment)
        if not _same_assignment(existing.labels, assignment_labels):
            raise NknAssignmentConflict(f"NKN container {name} belongs to another assignment")
        if str(getattr(existing, "status", "")).lower() == "running":
            return {"container_id": str(existing.id), "instance_id": name, "slot_id": slot_id}
        existing.stop(timeout=30)
        existing.remove(force=True)

    client.images.pull(IMAGE)
    created_volume = False
    try:
        volume_obj = client.volumes.get(volume)
    except NotFound:
        volume_obj = client.volumes.create(
            name=volume,
            labels={**labels, "cashpilot.nkn.volume": "true"},
        )
        created_volume = True
    if not created_volume and not _same_assignment(volume_obj.attrs.get("Labels"), labels):
        raise NknAssignmentConflict(f"NKN volume {volume} belongs to another assignment")

    if created_volume:
        try:
            archive = seed_archive(
                str(assignment.get("wallet_json") or ""),
                str(assignment.get("wallet_pswd") or ""),
                str(assignment.get("beneficiary_address") or ""),
            )
            _seed_volume(client, IMAGE, volume_obj, archive, name)
        except Exception:
            # A half-seeded volume has no recoverable identity and would make a
            # retry look like an assignment conflict. Remove only the volume
            # created by this invocation; pre-existing volumes are preserved.
            with suppress(Exception):
                volume_obj.remove(force=True)
            raise
    ports = {f"{port}/{protocol}": (private_ip, port) for port in PORTS for protocol in ("tcp", "udp")}
    container = client.containers.run(
        image=IMAGE,
        name=name,
        volumes={volume: {"bind": DATA_TARGET, "mode": "rw"}},
        network=network,
        ports=ports,
        cap_drop=["ALL"],
        security_opt=["no-new-privileges:true"],
        privileged=False,
        pids_limit=PIDS_LIMIT,
        nano_cpus=NANO_CPUS,
        mem_limit=MEM_LIMIT,
        labels=labels,
        hostname=name,
        detach=True,
        restart_policy={"Name": "always"},
    )
    return {"container_id": str(container.id), "instance_id": name, "slot_id": slot_id}


def remove_slot(
    slot_id: str,
    *,
    wallet_id: int,
    wallet_assignment_version: int,
    lease_client_id: str,
    client: Any,
    delete_volume: bool = True,
) -> dict[str, Any]:
    """Remove one NKN node only when its assignment version matches."""
    name = instance_id(slot_id)
    volume = volume_name(slot_id)
    expected = {
        "cashpilot.nkn.wallet_id": str(int(wallet_id)),
        "cashpilot.nkn.wallet_assignment_version": str(int(wallet_assignment_version)),
        "cashpilot.nkn.lease_client_id": _required_text(lease_client_id, "lease_client_id"),
    }
    try:
        container = client.containers.get(name)
    except NotFound:
        container = None
    if container is not None:
        if not _same_assignment(container.labels, expected):
            raise NknAssignmentConflict(f"NKN container {name} assignment does not match")
        container.stop(timeout=30)
        container.remove(force=True)
    deleted = False
    if delete_volume:
        try:
            volume_obj = client.volumes.get(volume)
        except NotFound:
            volume_obj = None
        if volume_obj is not None:
            if not _same_assignment(volume_obj.attrs.get("Labels"), expected):
                raise NknAssignmentConflict(f"NKN volume {volume} assignment does not match")
            volume_obj.remove(force=True)
            deleted = True
    return {"instance_id": name, "slot_id": slot_id, "deleted_volume": deleted}


def _assignment_container(
    slot_id: str,
    *,
    wallet_id: int,
    wallet_assignment_version: int,
    lease_client_id: str,
    client: Any,
) -> Any | None:
    name = instance_id(slot_id)
    expected = {
        "cashpilot.nkn.wallet_id": str(int(wallet_id)),
        "cashpilot.nkn.wallet_assignment_version": str(int(wallet_assignment_version)),
        "cashpilot.nkn.lease_client_id": _required_text(lease_client_id, "lease_client_id"),
    }
    try:
        container = client.containers.get(name)
    except NotFound:
        return None
    if not _same_assignment(container.labels, expected):
        raise NknAssignmentConflict(f"NKN container {name} assignment does not match")
    return container


def suspend_slot(
    slot_id: str,
    *,
    wallet_id: int,
    wallet_assignment_version: int,
    lease_client_id: str,
    client: Any,
) -> dict[str, str]:
    """Stop one assignment without deleting its container or identity volume."""
    container = _assignment_container(
        slot_id,
        wallet_id=wallet_id,
        wallet_assignment_version=wallet_assignment_version,
        lease_client_id=lease_client_id,
        client=client,
    )
    if container is not None:
        # A manual stop suppresses `always` only until the Docker daemon
        # restarts. Disable it while the lease is unconfirmed so a host reboot
        # cannot resurrect a reclaimed wallet assignment.
        container.update(restart_policy={"Name": "no"})
        if str(getattr(container, "status", "")).lower() == "running":
            container.stop(timeout=30)
    return {"instance_id": instance_id(slot_id), "slot_id": slot_id, "status": "stopped"}


def resume_slot(
    slot_id: str,
    *,
    wallet_id: int,
    wallet_assignment_version: int,
    lease_client_id: str,
    client: Any,
) -> dict[str, str]:
    """Start a suspended assignment only after its server lease is ACKed."""
    container = _assignment_container(
        slot_id,
        wallet_id=wallet_id,
        wallet_assignment_version=wallet_assignment_version,
        lease_client_id=lease_client_id,
        client=client,
    )
    if container is None:
        raise RuntimeError(f"NKN container {instance_id(slot_id)} is missing")
    container.update(restart_policy={"Name": "always"})
    if str(getattr(container, "status", "")).lower() != "running":
        container.start()
    return {"instance_id": instance_id(slot_id), "slot_id": slot_id, "status": "running"}


def node_evidence(container: Any) -> dict[str, Any]:
    """Read redacted local node state; unavailable tools produce unknown evidence."""
    evidence: dict[str, Any] = {"running": str(getattr(container, "status", "")).lower() == "running"}
    try:
        result = container.exec_run(
            [
                "/bin/sh",
                "-lc",
                "if command -v curl >/dev/null 2>&1; then "
                "curl -fsS --max-time 3 -H 'Content-Type: application/json' "
                '-d \'{"jsonrpc":"2.0","method":"getnodestate","params":{},"id":1}\' '
                "http://127.0.0.1:30003; "
                "elif command -v wget >/dev/null 2>&1; then "
                "wget -qO- --timeout=3 --header='Content-Type: application/json' "
                '--post-data=\'{"jsonrpc":"2.0","method":"getnodestate","params":{},"id":1}\' '
                "http://127.0.0.1:30003; else exit 127; fi",
            ]
        )
        raw = getattr(result, "output", b"") or b""
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        payload = json.loads(text)
        result_data = payload.get("result") if isinstance(payload, dict) else None
        if isinstance(result_data, dict):
            sync_state = str(result_data.get("syncState") or result_data.get("sync_state") or "")
            evidence["sync_state"] = sync_state
            evidence["online"] = evidence["running"] and sync_state == "PERSIST_FINISHED"
    except Exception:  # noqa: BLE001 - node evidence is best effort and redacted
        evidence["online"] = False
    return evidence
