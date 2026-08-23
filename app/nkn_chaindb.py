"""Pure integrity contract for NKN ChainDB snapshots.

This module deliberately performs no network, Docker, LXD, or R2 operations.
Both the server and the standalone publisher/restore tools can therefore share
one strict manifest and archive contract without gaining extra privileges.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_MAX_AGE_SECONDS = 48 * 60 * 60
CHAIN_DB_ROOT = "ChainDB"
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_RE = re.compile(r"^nknorg/nkn(?::[A-Za-z0-9._-]+|@sha256:[0-9a-f]{64})$")
_SNAPSHOT_KEY_RE = re.compile(
    r"^(?P<prefix>[A-Za-z0-9._/-]+)/snapshots/"
    r"(?P<height>\d+)-(?P<timestamp>\d{8}T\d{6}Z)-(?P<sha256>[0-9a-f]{64})\.tar\.zst$"
)
_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "provider",
        "network",
        "archive_key",
        "sha256",
        "size_bytes",
        "block_height",
        "created_at",
        "image",
        "chain_db_root",
    }
)


def _utc_timestamp(value: str | datetime) -> tuple[datetime, str]:
    if isinstance(value, datetime):
        instant = value
    else:
        text = str(value or "").strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            instant = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError("created_at must be an ISO-8601 timestamp") from exc
    if instant.tzinfo is None:
        raise ValueError("created_at must include a timezone")
    instant = instant.astimezone(UTC).replace(microsecond=0)
    return instant, instant.strftime("%Y%m%dT%H%M%SZ")


def _clean_prefix(prefix: str) -> str:
    value = str(prefix or "").strip().strip("/")
    if not value or "//" in value:
        raise ValueError("snapshot prefix is invalid")
    parts = PurePosixPath(value).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("snapshot prefix is invalid")
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", value):
        raise ValueError("snapshot prefix is invalid")
    return value


def snapshot_object_key(
    prefix: str,
    *,
    block_height: int,
    created_at: str | datetime,
    sha256: str,
) -> str:
    """Return the immutable, content-addressed R2 object key."""
    clean_prefix = _clean_prefix(prefix)
    height = int(block_height)
    digest = str(sha256 or "").strip().lower()
    if height < 0:
        raise ValueError("block_height must be non-negative")
    if not _DIGEST_RE.fullmatch(digest):
        raise ValueError("sha256 must be a lowercase hexadecimal digest")
    _, timestamp = _utc_timestamp(created_at)
    return f"{clean_prefix}/snapshots/{height}-{timestamp}-{digest}.tar.zst"


def build_manifest(
    *,
    prefix: str,
    sha256: str,
    size_bytes: int,
    block_height: int,
    created_at: str | datetime,
    image: str,
    network: str = "mainnet",
) -> dict[str, Any]:
    """Build a manifest whose object key is derived from its immutable fields."""
    instant, _ = _utc_timestamp(created_at)
    digest = str(sha256 or "").strip().lower()
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "provider": "nkn",
        "network": str(network or "").strip(),
        "archive_key": snapshot_object_key(
            prefix,
            block_height=int(block_height),
            created_at=instant,
            sha256=digest,
        ),
        "sha256": digest,
        "size_bytes": int(size_bytes),
        "block_height": int(block_height),
        "created_at": instant.isoformat().replace("+00:00", "Z"),
        "image": str(image or "").strip(),
        "chain_db_root": CHAIN_DB_ROOT,
    }
    return validate_manifest(manifest, now=instant, max_age_seconds=None)


def validate_manifest(
    manifest: Mapping[str, Any],
    *,
    now: datetime | None = None,
    max_age_seconds: int | None = DEFAULT_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Validate a snapshot manifest and return a detached normalized copy."""
    if not isinstance(manifest, Mapping):
        raise ValueError("snapshot manifest must be an object")
    if _MANIFEST_FIELDS - set(manifest):
        raise ValueError("snapshot manifest is missing required fields")
    if set(manifest) - _MANIFEST_FIELDS:
        raise ValueError("snapshot manifest contains unsupported fields")

    data = dict(manifest)
    if data["schema_version"] != SCHEMA_VERSION:
        raise ValueError("snapshot schema_version is unsupported")
    if data["provider"] != "nkn" or data["network"] != "mainnet":
        raise ValueError("snapshot provider/network is invalid")
    if data["chain_db_root"] != CHAIN_DB_ROOT:
        raise ValueError("snapshot may contain ChainDB only")

    digest = str(data["sha256"] or "").strip().lower()
    if not _DIGEST_RE.fullmatch(digest):
        raise ValueError("snapshot sha256 is invalid")
    if isinstance(data["size_bytes"], bool) or int(data["size_bytes"]) <= 0:
        raise ValueError("snapshot size_bytes must be positive")
    if isinstance(data["block_height"], bool) or int(data["block_height"]) < 0:
        raise ValueError("snapshot block_height must be non-negative")
    image = str(data["image"] or "").strip()
    if not _IMAGE_RE.fullmatch(image):
        raise ValueError("snapshot image is not an official NKN image")

    created, key_timestamp = _utc_timestamp(str(data["created_at"] or ""))
    key = str(data["archive_key"] or "").strip()
    match = _SNAPSHOT_KEY_RE.fullmatch(key)
    if not match:
        raise ValueError("snapshot archive_key is not immutable")
    if int(match.group("height")) != int(data["block_height"]):
        raise ValueError("snapshot archive_key height does not match manifest")
    if match.group("timestamp") != key_timestamp:
        raise ValueError("snapshot archive_key timestamp does not match manifest")
    if match.group("sha256") != digest:
        raise ValueError("snapshot archive_key digest does not match manifest")

    current = (now or datetime.now(UTC)).astimezone(UTC)
    if created > current and (created - current).total_seconds() > 300:
        raise ValueError("snapshot created_at is in the future")
    if max_age_seconds is not None:
        max_age = int(max_age_seconds)
        if max_age <= 0:
            raise ValueError("max_age_seconds must be positive")
        if (current - created).total_seconds() > max_age:
            raise ValueError("snapshot is too old")

    data.update(
        {
            "sha256": digest,
            "size_bytes": int(data["size_bytes"]),
            "block_height": int(data["block_height"]),
            "created_at": created.isoformat().replace("+00:00", "Z"),
            "image": image,
        }
    )
    return data


def validate_archive_members(names: Iterable[str]) -> None:
    """Reject archive entries outside the single top-level ChainDB directory."""
    found = False
    for raw_name in names:
        name = str(raw_name or "").replace("\\", "/")
        path = PurePosixPath(name)
        if not name or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("snapshot archive contains an unsafe path")
        if path.parts[0] != CHAIN_DB_ROOT:
            raise ValueError("snapshot archive may contain ChainDB only")
        found = True
    if not found:
        raise ValueError("snapshot archive is empty")


def validate_archive_entries(entries: Iterable[Any]) -> None:
    """Reject links and special files before an archive is extracted."""
    materialized = list(entries)
    validate_archive_members(getattr(entry, "name", "") for entry in materialized)
    for entry in materialized:
        if entry.issym() or entry.islnk():
            raise ValueError("snapshot archive link entries are not allowed")
        if entry.isdev() or entry.isfifo():
            raise ValueError("snapshot archive special entries are not allowed")


def verify_file(path: str | Path, *, expected_sha256: str, expected_size: int) -> dict[str, Any]:
    """Verify an archive without reading the whole file into memory."""
    digest_expected = str(expected_sha256 or "").strip().lower()
    if not _DIGEST_RE.fullmatch(digest_expected):
        raise ValueError("expected sha256 is invalid")
    size_expected = int(expected_size)
    if size_expected <= 0:
        raise ValueError("expected size must be positive")

    file_path = Path(path)
    size = file_path.stat().st_size
    if size != size_expected:
        raise ValueError("snapshot size does not match manifest")
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != digest_expected:
        raise ValueError("snapshot sha256 does not match manifest")
    return {"sha256": actual, "size_bytes": size}


def retained_snapshot_keys(keys: Iterable[str], *, keep: int) -> list[str]:
    """Return the newest valid immutable snapshot keys in chronological order."""
    count = int(keep)
    if count < 1:
        raise ValueError("keep must be at least one")
    parsed: list[tuple[str, int, str]] = []
    for key in keys:
        match = _SNAPSHOT_KEY_RE.fullmatch(str(key or "").strip())
        if match:
            parsed.append((match.group("timestamp"), int(match.group("height")), str(key)))
    parsed.sort()
    return [item[2] for item in parsed[-count:]]
