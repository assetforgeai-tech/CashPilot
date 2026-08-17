#!/usr/bin/env python3
"""Create a Cloudflare R2 S3 GET presigned URL."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
from pathlib import Path
from urllib.parse import quote, urlsplit


def _load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    aliases = {
        "bucket": "R2_BUCKET",
        "account_id": "R2_ACCOUNT_ID",
        "access_key_id": "R2_ACCESS_KEY_ID",
        "secret_access_key": "R2_SECRET_ACCESS_KEY",
        "endpoint": "R2_ENDPOINT_URL",
    }
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        else:
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            key, value = parts
        key = key.strip()
        value = value.strip().strip("\"'")
        values[aliases.get(key.lower(), key)] = value
    required = {"R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"}
    missing = sorted(required - values.keys())
    if missing:
        raise SystemExit(f"missing R2 env fields: {', '.join(missing)}")
    return values


def _aws_quote(value: str, *, safe: str = "-_.~") -> str:
    return quote(value, safe=safe)


def _sign(key: bytes, value: str) -> bytes:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()


def presign(values: dict[str, str], key: str, expires: int, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.UTC)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    date = now.strftime("%Y%m%d")
    endpoint = values["R2_ENDPOINT_URL"].rstrip("/")
    parsed = urlsplit(endpoint)
    if not parsed.scheme or not parsed.netloc:
        raise SystemExit("R2_ENDPOINT_URL must be an absolute URL")
    expires = max(1, min(int(expires), 604800))
    bucket = values["R2_BUCKET"].strip("/")
    object_key = key.strip("/")
    region = "auto"
    service = "s3"
    scope = f"{date}/{region}/{service}/aws4_request"
    credential = f"{values['R2_ACCESS_KEY_ID']}/{scope}"
    canonical_uri = "/" + "/".join(_aws_quote(part) for part in f"{bucket}/{object_key}".split("/"))
    params = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": credential,
        "X-Amz-Date": stamp,
        "X-Amz-Expires": str(expires),
        "X-Amz-SignedHeaders": "host",
    }
    canonical_query = "&".join(
        f"{_aws_quote(name)}={_aws_quote(value)}" for name, value in sorted(params.items())
    )
    canonical_request = "\n".join(
        ["GET", canonical_uri, canonical_query, f"host:{parsed.netloc}\n", "host", "UNSIGNED-PAYLOAD"]
    )
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            stamp,
            scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    signing_key = _sign(_sign(_sign(_sign(("AWS4" + values["R2_SECRET_ACCESS_KEY"]).encode(), date), region), service), "aws4_request")
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{parsed.scheme}://{parsed.netloc}{canonical_uri}?{canonical_query}&X-Amz-Signature={signature}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--expires", type=int, default=604800)
    args = parser.parse_args()
    print(presign(_load_env(args.env_file), args.key, args.expires))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
