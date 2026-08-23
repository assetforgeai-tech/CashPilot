from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from app import nkn_chaindb_r2


def test_presign_get_contains_sigv4_query_without_secret():
    url = nkn_chaindb_r2.presign_get(
        "https://acct.r2.cloudflarestorage.com",
        "private-bucket",
        "nkn/chaindb/manifests/latest.json",
        access_key="AKIAEXAMPLE",
        secret_key="super-secret-key",
        expires=300,
        now=nkn_chaindb_r2.datetime(2026, 8, 23, 12, 0, tzinfo=nkn_chaindb_r2.UTC),
    )
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.path.endswith("/private-bucket/nkn/chaindb/manifests/latest.json")
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert query["X-Amz-Expires"] == ["300"]
    assert "super-secret-key" not in url


def test_presign_get_default_lifetime_covers_slow_bootstrap():
    url = nkn_chaindb_r2.presign_get(
        "https://acct.r2.cloudflarestorage.com",
        "private-bucket",
        "nkn/chaindb/snapshots/archive.tar.zst",
        access_key="AKIAEXAMPLE",
        secret_key="super-secret-key",
        now=nkn_chaindb_r2.datetime(2026, 8, 23, 12, 0, tzinfo=nkn_chaindb_r2.UTC),
    )
    assert parse_qs(urlsplit(url).query)["X-Amz-Expires"] == [str(6 * 60 * 60)]


def test_presign_rejects_invalid_endpoint_or_expiry():
    with pytest.raises(ValueError):
        nkn_chaindb_r2.presign_get("http://acct.example", "bucket", "key", "a", "b", 300)
    with pytest.raises(ValueError):
        nkn_chaindb_r2.presign_get("https://acct.example", "bucket", "key", "a", "b", 0)


def test_object_url_keeps_bucket_and_encoded_key():
    assert (
        nkn_chaindb_r2.object_url(
            "https://acct.r2.cloudflarestorage.com/",
            "bucket",
            "nkn/chaindb/snapshots/a b.tar.zst",
        )
        == "https://acct.r2.cloudflarestorage.com/bucket/nkn/chaindb/snapshots/a%20b.tar.zst"
    )
