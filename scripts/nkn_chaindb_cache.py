#!/usr/bin/env python3
"""Persistent, integrity-verified host cache for NKN ChainDB snapshots."""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

try:  # Linux workers use a process-wide file lock; tests also run on Windows.
    import fcntl
except ImportError:  # pragma: no cover - exercised by the Windows test runner
    fcntl = None  # type: ignore[assignment]

CACHE_DOWNLOAD_TIMEOUT = 90 * 60
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ARCHIVE_RE = re.compile(r"^(?P<digest>[0-9a-f]{64})\.tar\.zst$")
_PROCESS_LOCK = threading.Lock()


class CacheError(RuntimeError):
    """A redacted snapshot-cache failure safe to return to the worker."""


@dataclass(frozen=True)
class CacheResult:
    path: Path
    sha256: str
    size_bytes: int
    cache_hit: bool


def _validated_inputs(url: str, expected_sha256: str, expected_size: int, keep: int) -> tuple[str, int, int]:
    parsed = urllib.parse.urlsplit(str(url or ""))
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("snapshot archive URL must be HTTPS")
    digest = str(expected_sha256 or "").strip().lower()
    if not _DIGEST_RE.fullmatch(digest):
        raise ValueError("expected sha256 is invalid")
    if isinstance(expected_size, bool) or int(expected_size) <= 0:
        raise ValueError("expected size must be positive")
    if isinstance(keep, bool) or int(keep) < 1:
        raise ValueError("cache retention must be at least one")
    return digest, int(expected_size), int(keep)


def _verify(path: Path, *, expected_sha256: str, expected_size: int) -> None:
    if path.stat().st_size != expected_size:
        raise CacheError("snapshot cache size validation failed")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256:
        raise CacheError("snapshot cache digest validation failed")


def _root_owned(path: Path, *, mode: int) -> None:
    """Keep the host cache readable by LXD but writable only by root."""
    try:
        path.chmod(mode)
        geteuid = getattr(os, "geteuid", lambda: 1)
        chown = getattr(os, "chown", None)
        if chown is not None and geteuid() == 0:
            chown(path, 0, 0)
    except OSError as exc:
        raise CacheError("snapshot cache permissions could not be enforced") from exc


@contextlib.contextmanager
def _cache_lock(cache_root: Path):
    lock_path = cache_root / ".cache.lock"
    with _PROCESS_LOCK, lock_path.open("a+b") as handle:
        _root_owned(lock_path, mode=0o644)
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _complete_archives(cache_root: Path, *, exclude: Path | None = None) -> list[Path]:
    archives = [
        path
        for path in cache_root.iterdir()
        if path.is_file() and _ARCHIVE_RE.fullmatch(path.name) and (exclude is None or path != exclude)
    ]
    return sorted(archives, key=lambda path: (path.stat().st_mtime_ns, path.name), reverse=True)


def _prune(cache_root: Path, *, keep: int, exclude: Path | None = None) -> None:
    retained_other = max(0, keep - (1 if exclude is not None and exclude.exists() else 0))
    for path in _complete_archives(cache_root, exclude=exclude)[retained_other:]:
        path.unlink(missing_ok=True)


def _download(url: str, partial: Path, *, expected_size: int) -> None:
    size = 0
    try:
        with (
            urllib.request.urlopen(str(url), timeout=CACHE_DOWNLOAD_TIMEOUT) as response,  # noqa: S310
            partial.open("wb") as output,
        ):
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > expected_size:
                    raise CacheError("snapshot cache download exceeded the manifest size")
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if size != expected_size:
            raise CacheError("snapshot cache download size validation failed")
    except CacheError:
        raise
    except Exception as exc:
        raise CacheError("snapshot cache download failed") from exc


def ensure_cached_archive(
    url: str,
    *,
    expected_sha256: str,
    expected_size: int,
    cache_root: str | Path,
    keep: int = 2,
) -> CacheResult:
    """Return one verified immutable archive without persisting its signed URL."""
    digest, size, retention = _validated_inputs(url, expected_sha256, expected_size, keep)
    root = Path(cache_root).resolve()
    root.mkdir(mode=0o755, parents=True, exist_ok=True)
    _root_owned(root, mode=0o755)
    final = root / f"{digest}.tar.zst"
    partial = root / f"{digest}.tar.zst.partial"

    with _cache_lock(root):
        if final.exists():
            try:
                _verify(final, expected_sha256=digest, expected_size=size)
            except (OSError, CacheError):
                final.unlink(missing_ok=True)
            else:
                _root_owned(final, mode=0o644)
                _prune(root, keep=retention, exclude=final)
                return CacheResult(path=final, sha256=digest, size_bytes=size, cache_hit=True)

        partial.unlink(missing_ok=True)
        try:
            _download(url, partial, expected_size=size)
            _verify(partial, expected_sha256=digest, expected_size=size)
            _root_owned(partial, mode=0o644)
            os.replace(partial, final)
            _root_owned(final, mode=0o644)
            _prune(root, keep=retention, exclude=final)
            return CacheResult(path=final, sha256=digest, size_bytes=size, cache_hit=False)
        except (OSError, CacheError) as exc:
            raise CacheError("snapshot cache population failed") from exc
        finally:
            partial.unlink(missing_ok=True)


def invalidate_cached_archive(path: str | Path, *, cache_root: str | Path) -> None:
    """Remove only a digest-named archive confined to the configured cache root."""
    root = Path(cache_root).resolve()
    candidate = Path(path).resolve()
    if candidate.parent != root or not _ARCHIVE_RE.fullmatch(candidate.name):
        raise ValueError("snapshot cache path is invalid")
    with _cache_lock(root):
        candidate.unlink(missing_ok=True)
