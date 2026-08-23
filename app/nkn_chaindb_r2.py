"""Small AWS SigV4 helper for private Cloudflare R2 objects.

R2 exposes an S3-compatible API, so CashPilot can issue short-lived presigned
URLs without adding boto3 or passing R2 credentials to a worker.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from urllib.parse import quote, urlencode, urlsplit

SERVICE = "s3"
REGION = "auto"
DEFAULT_PRESIGN_EXPIRES = 6 * 60 * 60


def _endpoint(endpoint: str) -> tuple[str, str]:
    parsed = urlsplit(str(endpoint or "").strip().rstrip("/"))
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("R2 endpoint must be an https URL without a query")
    return parsed.netloc, parsed.path.rstrip("/")


def _component(value: str) -> str:
    return quote(str(value), safe="-_.~/")


def object_url(endpoint: str, bucket: str, key: str) -> str:
    host, base = _endpoint(endpoint)
    bucket = str(bucket or "").strip()
    key = str(key or "").strip().lstrip("/")
    if not bucket or not key or ".." in key.split("/"):
        raise ValueError("R2 bucket and object key are required")
    return f"https://{host}{base}/{_component(bucket)}/{_component(key)}"


def _sign(key: bytes, value: str) -> bytes:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()


def _signature_key(secret: str, date: str) -> bytes:
    return _sign(_sign(_sign(_sign(("AWS4" + secret).encode("utf-8"), date), REGION), SERVICE), "aws4_request")


def _presign(
    method: str,
    endpoint: str,
    bucket: str,
    key: str,
    access_key: str,
    secret_key: str,
    expires: int,
    *,
    now: datetime | None = None,
) -> str:
    if not str(access_key or "").strip() or not str(secret_key or "").strip():
        raise ValueError("R2 credentials are required")
    if not 1 <= int(expires) <= 604800:
        raise ValueError("R2 presign expiry must be between 1 and 604800 seconds")
    url = object_url(endpoint, bucket, key)
    parsed = urlsplit(url)
    instant = (now or datetime.now(UTC)).astimezone(UTC)
    amz_date = instant.strftime("%Y%m%dT%H%M%SZ")
    date = instant.strftime("%Y%m%d")
    credential = f"{access_key}/{date}/{REGION}/{SERVICE}/aws4_request"
    params = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": credential,
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(int(expires)),
        "X-Amz-SignedHeaders": "host",
    }
    canonical_query = urlencode(sorted(params.items()), quote_via=quote, safe="-_.~")
    canonical_uri = parsed.path or "/"
    canonical_request = "\n".join(
        [method.upper(), canonical_uri, canonical_query, f"host:{parsed.netloc}\n", "host", "UNSIGNED-PAYLOAD"]
    )
    scope = f"{date}/{REGION}/{SERVICE}/aws4_request"
    string_to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical_request.encode()).hexdigest()]
    )
    signature = hmac.new(_signature_key(secret_key, date), string_to_sign.encode(), hashlib.sha256).hexdigest()
    return f"{url}?{canonical_query}&X-Amz-Signature={signature}"


def presign_get(
    endpoint: str,
    bucket: str,
    key: str,
    access_key: str,
    secret_key: str,
    expires: int = DEFAULT_PRESIGN_EXPIRES,
    *,
    now: datetime | None = None,
) -> str:
    return _presign("GET", endpoint, bucket, key, access_key, secret_key, expires, now=now)


def presign_put(
    endpoint: str,
    bucket: str,
    key: str,
    access_key: str,
    secret_key: str,
    expires: int = 900,
    *,
    now: datetime | None = None,
) -> str:
    return _presign("PUT", endpoint, bucket, key, access_key, secret_key, expires, now=now)
