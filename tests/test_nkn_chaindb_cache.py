from __future__ import annotations

import hashlib
import io
import os
import stat
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import get_context

import pytest

from scripts import nkn_chaindb_cache


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _hold_process_cache_lock(cache_root: str, barrier, queue) -> None:
    from pathlib import Path

    from scripts import nkn_chaindb_cache as cache

    barrier.wait()
    root = Path(cache_root)
    root.mkdir(parents=True, exist_ok=True)
    with cache._cache_lock(root):
        entered = time.monotonic()
        time.sleep(0.15)
        queue.put((entered, time.monotonic()))


def test_cache_downloads_one_digest_once_and_uses_atomic_partial_file(tmp_path, monkeypatch):
    payload = b"verified-chain-db"
    digest = _digest(payload)
    calls = []
    replacements = []
    original_replace = os.replace

    def urlopen(url, **_kwargs):
        calls.append(url)
        return io.BytesIO(payload)

    def replace(source, target):
        replacements.append((str(source), str(target)))
        original_replace(source, target)

    monkeypatch.setattr(nkn_chaindb_cache.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(nkn_chaindb_cache.os, "replace", replace)

    first = nkn_chaindb_cache.ensure_cached_archive(
        "https://r2.example.invalid/object?X-Amz-Signature=secret-value",
        expected_sha256=digest,
        expected_size=len(payload),
        cache_root=tmp_path,
    )
    second = nkn_chaindb_cache.ensure_cached_archive(
        "https://r2.example.invalid/object?X-Amz-Signature=another-secret",
        expected_sha256=digest,
        expected_size=len(payload),
        cache_root=tmp_path,
    )

    assert calls == ["https://r2.example.invalid/object?X-Amz-Signature=secret-value"]
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert first.path == second.path == tmp_path / f"{digest}.tar.zst"
    assert first.path.read_bytes() == payload
    assert replacements == [(str(tmp_path / f"{digest}.tar.zst.partial"), str(first.path))]
    assert not list(tmp_path.glob("*.partial"))
    assert "secret" not in repr(first).lower()
    assert all("secret" not in path.name.lower() for path in tmp_path.iterdir())
    if os.name != "nt":
        assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o755
        assert stat.S_IMODE(first.path.stat().st_mode) == 0o644


def test_cache_repairs_existing_directory_and_archive_handoff_permissions(tmp_path, monkeypatch):
    payload = b"verified-chain-db"
    digest = _digest(payload)
    archive = tmp_path / f"{digest}.tar.zst"
    archive.write_bytes(payload)
    os.chmod(tmp_path, 0o700)
    os.chmod(archive, 0o600)
    chowns = []
    monkeypatch.setattr(nkn_chaindb_cache.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(
        nkn_chaindb_cache.os,
        "chown",
        lambda path, uid, gid: chowns.append((str(path), uid, gid)),
        raising=False,
    )

    result = nkn_chaindb_cache.ensure_cached_archive(
        "https://r2.example.invalid/object",
        expected_sha256=digest,
        expected_size=len(payload),
        cache_root=tmp_path,
    )

    assert result.cache_hit is True
    if os.name != "nt":
        assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o755
        assert stat.S_IMODE(archive.stat().st_mode) == 0o644
    assert (str(tmp_path.resolve()), 0, 0) in chowns
    assert (str(archive.resolve()), 0, 0) in chowns


def test_cache_serializes_concurrent_requests_for_the_same_digest(tmp_path, monkeypatch):
    payload = b"one-network-transfer"
    digest = _digest(payload)
    calls = 0
    calls_lock = threading.Lock()

    def urlopen(_url, **_kwargs):
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.05)
        return io.BytesIO(payload)

    monkeypatch.setattr(nkn_chaindb_cache.urllib.request, "urlopen", urlopen)

    def populate():
        return nkn_chaindb_cache.ensure_cached_archive(
            "https://r2.example.invalid/object",
            expected_sha256=digest,
            expected_size=len(payload),
            cache_root=tmp_path,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _item: populate(), range(2)))

    assert calls == 1
    assert sorted(result.cache_hit for result in results) == [False, True]


@pytest.mark.skipif(os.name == "nt", reason="Linux worker process-lock contract")
def test_cache_serializes_two_host_helper_processes_with_flock(tmp_path):
    context = get_context("fork")
    barrier = context.Barrier(2)
    queue = context.Queue()
    processes = [
        context.Process(target=_hold_process_cache_lock, args=(str(tmp_path / "cache"), barrier, queue))
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0
    intervals = sorted([queue.get(timeout=2), queue.get(timeout=2)])
    assert intervals[1][0] >= intervals[0][1]


def test_cache_replaces_a_corrupt_same_size_archive(tmp_path, monkeypatch):
    payload = b"correct-bytes"
    corrupt = b"wrong--bytes!"
    assert len(corrupt) == len(payload)
    digest = _digest(payload)
    final = tmp_path / f"{digest}.tar.zst"
    final.write_bytes(corrupt)
    calls = []
    monkeypatch.setattr(
        nkn_chaindb_cache.urllib.request,
        "urlopen",
        lambda url, **_kwargs: calls.append(url) or io.BytesIO(payload),
    )

    result = nkn_chaindb_cache.ensure_cached_archive(
        "https://r2.example.invalid/object",
        expected_sha256=digest,
        expected_size=len(payload),
        cache_root=tmp_path,
    )

    assert result.cache_hit is False
    assert calls == ["https://r2.example.invalid/object"]
    assert final.read_bytes() == payload


@pytest.mark.parametrize(
    ("downloaded", "expected_payload"),
    [
        (b"short", b"expected-size"),
        (b"wrong-content", b"right-content"),
    ],
)
def test_cache_rejects_invalid_download_and_removes_partial(tmp_path, monkeypatch, downloaded, expected_payload):
    digest = _digest(expected_payload)
    monkeypatch.setattr(
        nkn_chaindb_cache.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: io.BytesIO(downloaded),
    )

    with pytest.raises(nkn_chaindb_cache.CacheError):
        nkn_chaindb_cache.ensure_cached_archive(
            "https://r2.example.invalid/object",
            expected_sha256=digest,
            expected_size=len(expected_payload),
            cache_root=tmp_path,
        )

    assert not (tmp_path / f"{digest}.tar.zst").exists()
    assert not list(tmp_path.glob("*.partial"))


def test_cache_errors_do_not_expose_the_presigned_url(tmp_path, monkeypatch):
    url = "https://r2.example.invalid/object?X-Amz-Credential=sensitive-value"

    def fail(_url, **_kwargs):
        raise RuntimeError(f"network failed for {url}")

    monkeypatch.setattr(nkn_chaindb_cache.urllib.request, "urlopen", fail)

    with pytest.raises(nkn_chaindb_cache.CacheError) as exc:
        nkn_chaindb_cache.ensure_cached_archive(
            url,
            expected_sha256="a" * 64,
            expected_size=1,
            cache_root=tmp_path,
        )

    assert "sensitive-value" not in str(exc.value)
    assert url not in str(exc.value)


def test_cache_keeps_only_the_two_newest_complete_archives(tmp_path, monkeypatch):
    old_a = tmp_path / f"{'a' * 64}.tar.zst"
    old_b = tmp_path / f"{'b' * 64}.tar.zst"
    old_a.write_bytes(b"a")
    old_b.write_bytes(b"b")
    os.utime(old_a, (1, 1))
    os.utime(old_b, (2, 2))
    payload = b"current"
    digest = _digest(payload)
    monkeypatch.setattr(
        nkn_chaindb_cache.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: io.BytesIO(payload),
    )

    current = nkn_chaindb_cache.ensure_cached_archive(
        "https://r2.example.invalid/object",
        expected_sha256=digest,
        expected_size=len(payload),
        cache_root=tmp_path,
        keep=2,
    )

    assert current.path.exists()
    assert old_b.exists()
    assert not old_a.exists()
    assert len(list(tmp_path.glob("*.tar.zst"))) == 2


def test_cache_rejects_plain_http_without_opening_it(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(
        nkn_chaindb_cache.urllib.request,
        "urlopen",
        lambda *args, **kwargs: opened.append((args, kwargs)),
    )

    with pytest.raises(ValueError, match="HTTPS"):
        nkn_chaindb_cache.ensure_cached_archive(
            "http://r2.example.invalid/object",
            expected_sha256="a" * 64,
            expected_size=1,
            cache_root=tmp_path,
        )

    assert opened == []
