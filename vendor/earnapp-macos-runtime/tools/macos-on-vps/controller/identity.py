from __future__ import annotations

import json
import os
import re
import secrets
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, TextIO

from apple_profile import validate_opencore_identity, OpenCoreIdentity

try:
    import fcntl
except ImportError:  # Windows unit tests use the in-process lock below.
    fcntl = None


INSTANCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
HOSTNAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_PROCESS_REGISTRY_LOCK = threading.Lock()
_MANIFEST_FIELDS = (
    "instance_id",
    "model",
    "serial",
    "mlb",
    "uuid",
    "mac",
    "rom",
    "hostname",
    "coverage_status",
    "created_utc",
)


def _validate_instance_id(instance_id: str) -> None:
    if not INSTANCE_ID_RE.fullmatch(instance_id):
        raise ValueError("instance id must contain only lowercase letters, digits, and hyphens")


def _mac_address() -> str:
    octets = bytearray(secrets.token_bytes(6))
    octets[0] = (octets[0] | 0x02) & 0xFE
    return ":".join(f"{value:02x}" for value in octets)


def _hostname(instance_id: str) -> str:
    suffix = secrets.token_hex(4)
    prefix = instance_id[:48].rstrip("-")
    hostname = f"macos-{prefix}-{suffix}"
    if not HOSTNAME_RE.fullmatch(hostname):
        raise RuntimeError("generated hostname is invalid")
    return hostname


def _fallback_smbios() -> tuple[str, str]:
    serial = "C" + secrets.token_hex(6).upper()[:11]
    mlb = "C" + secrets.token_hex(8).upper()[:16]
    return serial, mlb


def _candidate(
    instance_id: str, smbios: tuple[str, str] | None = None
) -> dict[str, str]:
    _validate_instance_id(instance_id)
    serial, mlb = smbios or _fallback_smbios()
    candidate_uuid = str(uuid.uuid4())
    candidate_mac = _mac_address()
    return {
        "instance_id": instance_id,
        "model": "iMacPro1,1",
        "serial": serial,
        "sn": serial,
        "mlb": mlb,
        "uuid": candidate_uuid,
        "mac": candidate_mac,
        "rom": candidate_mac.replace(":", ""),
        "hostname": _hostname(instance_id),
        "coverage_status": "not_queried",
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }


def preview_identity(instance_id: str) -> dict[str, str]:
    return _candidate(instance_id)


def _load_entries(handle: TextIO) -> list[dict[str, str]]:
    handle.seek(0)
    entries: list[dict[str, str]] = []
    for line_number, line in enumerate(handle, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid registry JSON on line {line_number}") from error
        if not isinstance(value, dict):
            raise ValueError(f"invalid registry entry on line {line_number}")
        entries.append({str(key): str(item) for key, item in value.items()})
    return entries


def generate_identity(
    instance_id: str,
    registry_path: Path,
    smbios: tuple[str, str] | None = None,
    *,
    reuse_existing: bool = False,
) -> dict[str, str]:
    _validate_instance_id(instance_id)
    registry_path = Path(registry_path)
    registry_path.parent.mkdir(parents=True, exist_ok=True)

    with _PROCESS_REGISTRY_LOCK:
        with registry_path.open("a+", encoding="utf-8", newline="\n") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                entries = _load_entries(handle)
                existing = next(
                    (entry for entry in entries if entry.get("instance_id") == instance_id),
                    None,
                )
                if existing is not None:
                    if not reuse_existing:
                        raise ValueError(f"instance id already exists: {instance_id}")
                    if smbios is not None and (
                        existing.get("serial"), existing.get("mlb")
                    ) != smbios:
                        raise ValueError("existing instance SMBIOS does not match the claim")
                    candidate = existing
                else:
                    occupied = {
                        field: {entry.get(field) for entry in entries}
                        for field in ("serial", "mlb", "uuid", "mac", "hostname")
                    }
                    if smbios is not None:
                        serial, mlb = smbios
                        if serial in occupied["serial"] or mlb in occupied["mlb"]:
                            raise ValueError("serial or MLB already exists in identity registry")
                    for _ in range(64):
                        candidate = _candidate(instance_id, smbios)
                        try:
                            validate_opencore_identity(OpenCoreIdentity(**{
                                key: candidate[key]
                                for key in (
                                    "instance_id", "model", "serial", "mlb", "uuid",
                                    "mac", "rom", "hostname", "coverage_status"
                                )
                            }))
                        except ValueError:
                            if smbios is not None:
                                raise
                            continue
                        if all(candidate[field] not in occupied[field] for field in occupied):
                            break
                    else:
                        raise RuntimeError("could not generate a collision-free identity")

                    handle.seek(0, os.SEEK_END)
                    handle.write(json.dumps(candidate, sort_keys=True, separators=(",", ":")) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    try:
        os.chmod(registry_path, 0o600)
    except OSError:
        pass
    return candidate


def specialization_manifest(identity: Mapping[str, str]) -> str:
    required = ("instance_id", "uuid", "mac", "hostname")
    missing = [field for field in required if not identity.get(field)]
    if missing:
        raise ValueError(f"identity is missing required fields: {', '.join(missing)}")
    manifest = {
        "schema": 1,
        **{field: identity[field] for field in _MANIFEST_FIELDS if identity.get(field)},
        "ssh_host_key_policy": "regenerate-in-guest",
    }
    return json.dumps(manifest, sort_keys=True, indent=2) + "\n"
