from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading

from apple_profile import MLB_RE, PLACEHOLDER_MLBS, PLACEHOLDER_SERIALS, SERIAL_RE

try:
    import fcntl
except ImportError:  # Windows tests use the in-process lock.
    fcntl = None


INSTANCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
UUID_RE = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)
MAC_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
ROM_RE = re.compile(r"^[0-9A-Fa-f]{12}$")
_PROCESS_LOCK = threading.Lock()


def claim_smbios(
    pool_path: Path,
    claims_path: Path,
    *,
    instance_id: str,
    enforce_permissions: bool | None = None,
) -> tuple[str, str]:
    if not INSTANCE_ID_RE.fullmatch(instance_id):
        raise ValueError("instance_id must contain lowercase letters, digits, and hyphens")
    pool_path = Path(pool_path)
    claims_path = Path(claims_path)
    enforce = os.name != "nt" if enforce_permissions is None else enforce_permissions
    _require_secure_file(pool_path, "serial pool", enforce=enforce)
    candidates = _load_candidates(pool_path)

    claims_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(claims_path.parent, 0o700)
    claims_path.touch(mode=0o600, exist_ok=True)
    os.chmod(claims_path, 0o600)
    if enforce:
        _require_secure_file(claims_path, "serial claims", enforce=True)

    with _PROCESS_LOCK:
        with claims_path.open("r+", encoding="utf-8", newline="\n") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                claims = _load_claims(handle)
                existing = next(
                    (claim for claim in claims if claim["instance_id"] == instance_id),
                    None,
                )
                if existing is not None:
                    return existing["serial"], existing["mlb"]

                used_serials = {claim["serial"] for claim in claims}
                used_mlbs = {claim["mlb"] for claim in claims}
                selected = next(
                    (
                        candidate
                        for candidate in candidates
                        if candidate[0] not in used_serials and candidate[1] not in used_mlbs
                    ),
                    None,
                )
                if selected is None:
                    raise RuntimeError("serial pool is exhausted")

                record = {
                    "schema": 1,
                    "instance_id": instance_id,
                    "serial": selected[0],
                    "mlb": selected[1],
                    "claimed_at": datetime.now(timezone.utc).isoformat(),
                }
                handle.seek(0, os.SEEK_END)
                handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
                return selected
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _load_candidates(path: Path) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    seen_serials: set[str] = set()
    seen_mlbs: set[str] = set()
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError("serial pool is missing, unreadable, or non-ASCII") from error
    for line_number, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        values = raw_line.rstrip().split("|")
        if len(values) != 9 or values[-1] != "":
            raise ValueError(f"invalid serial pool row {line_number}")
        model, serial, mlb, candidate_uuid, mac, rom, width, height, _empty = values
        if (
            model != "iMacPro1,1"
            or not SERIAL_RE.fullmatch(serial)
            or not MLB_RE.fullmatch(mlb)
            or serial in PLACEHOLDER_SERIALS
            or mlb in PLACEHOLDER_MLBS
            or not UUID_RE.fullmatch(candidate_uuid)
            or not MAC_RE.fullmatch(mac)
            or not ROM_RE.fullmatch(rom)
            or rom.lower() != mac.replace(":", "").lower()
            or width != "1920"
            or height != "1080"
        ):
            raise ValueError(f"invalid serial pool row {line_number}")
        if serial in seen_serials or mlb in seen_mlbs:
            continue
        seen_serials.add(serial)
        seen_mlbs.add(mlb)
        candidates.append((serial, mlb))
    if not candidates:
        raise ValueError("serial pool contains no usable identities")
    return candidates


def _load_claims(handle) -> list[dict[str, str]]:
    handle.seek(0)
    claims: list[dict[str, str]] = []
    for line_number, line in enumerate(handle, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid serial claim on line {line_number}") from error
        if (
            not isinstance(value, dict)
            or value.get("schema") != 1
            or not INSTANCE_ID_RE.fullmatch(str(value.get("instance_id") or ""))
            or not SERIAL_RE.fullmatch(str(value.get("serial") or ""))
            or not MLB_RE.fullmatch(str(value.get("mlb") or ""))
        ):
            raise ValueError(f"invalid serial claim on line {line_number}")
        claims.append(
            {
                "instance_id": str(value["instance_id"]),
                "serial": str(value["serial"]),
                "mlb": str(value["mlb"]),
            }
        )
    return claims


def _require_secure_file(path: Path, name: str, *, enforce: bool) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{name} file is missing: {path}")
    if not enforce:
        return
    stat = path.stat()
    if stat.st_uid != 0:
        raise PermissionError(f"{name} must be root-owned")
    if stat.st_mode & 0o077:
        raise PermissionError(f"{name} permissions must be 0600 or stricter")
