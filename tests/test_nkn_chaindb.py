from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from app import nkn_chaindb


def _manifest(**overrides):
    now = datetime.now(UTC).replace(microsecond=0)
    data = {
        "schema_version": 1,
        "provider": "nkn",
        "network": "mainnet",
        "sha256": "a" * 64,
        "size_bytes": 123,
        "block_height": 9684184,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "image": "nknorg/nkn@sha256:" + "b" * 64,
        "chain_db_root": "ChainDB",
    }
    data.update(overrides)
    if "archive_key" not in overrides:
        data["archive_key"] = nkn_chaindb.snapshot_object_key(
            "nkn/chaindb",
            block_height=data["block_height"],
            created_at=data["created_at"],
            sha256=data["sha256"],
        )
    return data


def test_snapshot_object_key_is_immutable_and_digest_addressed():
    key = nkn_chaindb.snapshot_object_key(
        "nkn/chaindb",
        block_height=42,
        created_at="2026-08-23T12:00:00Z",
        sha256="a" * 64,
    )
    assert key == "nkn/chaindb/snapshots/42-20260823T120000Z-" + "a" * 64 + ".tar.zst"


def test_manifest_validation_accepts_current_snapshot_and_returns_copy():
    manifest = _manifest()
    validated = nkn_chaindb.validate_manifest(manifest)
    assert validated == manifest
    assert validated is not manifest


def test_manifest_validation_drops_no_unknown_or_secret_fields():
    with pytest.raises(ValueError, match="unsupported"):
        nkn_chaindb.validate_manifest({**_manifest(), "secret": "must-not-leak"})


@pytest.mark.parametrize(
    "change",
    [
        {"provider": "myst"},
        {"sha256": "not-a-digest"},
        {"size_bytes": 0},
        {"block_height": -1},
        {"archive_key": "nkn/chaindb/latest.tar.zst"},
        {"chain_db_root": "wallet.json"},
    ],
)
def test_manifest_validation_rejects_invalid_contract(change):
    with pytest.raises(ValueError):
        nkn_chaindb.validate_manifest({**_manifest(), **change})


def test_manifest_validation_rejects_stale_snapshot():
    old = datetime.now(UTC) - timedelta(days=3)
    manifest = _manifest(created_at=old.isoformat().replace("+00:00", "Z"))
    with pytest.raises(ValueError, match="old"):
        nkn_chaindb.validate_manifest(manifest, max_age_seconds=24 * 60 * 60)


@pytest.mark.parametrize(
    "names",
    [
        ["../wallet.json"],
        ["ChainDB/../../wallet.json"],
        ["/absolute/path"],
        ["ChainDB", "ChainDB/ok", "wallet.json"],
    ],
)
def test_archive_members_are_limited_to_chaindb(names):
    with pytest.raises(ValueError):
        nkn_chaindb.validate_archive_members(names)


def test_archive_members_accept_chain_db_files():
    nkn_chaindb.validate_archive_members(["ChainDB", "ChainDB/000001.ldb", "ChainDB/MANIFEST-1"])


def test_archive_entries_reject_links_and_special_files():
    class Entry:
        def __init__(self, name, *, link=False, device=False):
            self.name = name
            self.linkname = "../../wallet.json" if link else ""
            self._link = link
            self._device = device

        def issym(self):
            return self._link

        def islnk(self):
            return False

        def isdev(self):
            return self._device

        def isfifo(self):
            return False

    with pytest.raises(ValueError, match="link"):
        nkn_chaindb.validate_archive_entries([Entry("ChainDB/link", link=True)])
    with pytest.raises(ValueError, match="special"):
        nkn_chaindb.validate_archive_entries([Entry("ChainDB/device", device=True)])


def test_verify_file_checks_digest_and_size(tmp_path):
    payload = b"chain data"
    path = tmp_path / "snapshot.tar.zst"
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    result = nkn_chaindb.verify_file(path, expected_sha256=digest, expected_size=len(payload))
    assert result == {"sha256": digest, "size_bytes": len(payload)}


def test_verify_file_rejects_mismatch(tmp_path):
    path = tmp_path / "snapshot.tar.zst"
    path.write_bytes(b"chain data")
    with pytest.raises(ValueError, match="sha256"):
        nkn_chaindb.verify_file(path, expected_sha256="b" * 64, expected_size=10)


def test_retention_keeps_newest_immutable_keys():
    keys = [
        "nkn/chaindb/snapshots/1-20260820T000000Z-" + "a" * 64 + ".tar.zst",
        "nkn/chaindb/snapshots/2-20260821T000000Z-" + "b" * 64 + ".tar.zst",
        "nkn/chaindb/snapshots/3-20260822T000000Z-" + "c" * 64 + ".tar.zst",
    ]
    assert nkn_chaindb.retained_snapshot_keys(keys, keep=2) == keys[1:]
