"""EarnApp account-pool validation and secret-safe public views."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app import database

COOKIE_ALLOWLIST = frozenset(
    {
        "auth",
        "auth-method",
        "oauth-refresh-token",
        "oauth-token",
        "xsrf-token",
        "brd_sess_id",
        "cg_uuid",
    }
)


class AccountDeletionDenied(RuntimeError):
    """Raised when an operator tries to delete an account that is not locked."""


def _iso_from_timestamp(value: Any) -> str | None:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _jwt_exp(value: str) -> int | None:
    parts = str(value or "").split(".")
    if len(parts) != 3:
        return None
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
        exp = int(data.get("exp"))
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return exp if exp > 0 else None


def _normalize_cookies(raw: Any) -> tuple[dict[str, str], list[float]]:
    if not isinstance(raw, Mapping):
        raise ValueError("EarnApp cookies are required")
    cookies: dict[str, str] = {}
    expirations: list[float] = []
    for key in COOKIE_ALLOWLIST:
        item = raw.get(key)
        if isinstance(item, Mapping):
            value = str(item.get("value") or "").strip()
            expiration = item.get("expiration_date", item.get("expirationDate"))
        else:
            value = str(item or "").strip()
            expiration = None
        if not value:
            continue
        cookies[key] = value
        try:
            seconds = float(expiration)
        except (TypeError, ValueError):
            continue
        if seconds > 0:
            expirations.append(seconds)
    return cookies, expirations


async def import_account(payload: Mapping[str, Any]) -> int:
    profile_key = str(payload.get("profile_key") or "").strip()
    account_name = str(payload.get("account_name") or payload.get("email") or "").strip()
    email = str(payload.get("email") or "").strip()
    auth_method = str(payload.get("auth_method") or "").strip().lower()
    if auth_method not in {"google", "apple"}:
        raise ValueError("EarnApp auth method must be Google or Apple")
    cookies, cookie_expirations = _normalize_cookies(payload.get("cookies"))
    if "oauth-refresh-token" not in cookies or "xsrf-token" not in cookies:
        raise ValueError("oauth-refresh-token and xsrf-token are required")

    jwt_exp = _jwt_exp(cookies.get("oauth-refresh-token", ""))
    return await database.upsert_earnapp_account(
        profile_key=profile_key,
        account_name=account_name,
        email=email,
        auth_method=auth_method,
        credentials={"cookies": cookies},
        credential_keys=sorted(cookies),
        token_expires_at=_iso_from_timestamp(jwt_exp),
        cookie_expires_at=_iso_from_timestamp(min(cookie_expirations)) if cookie_expirations else None,
    )


async def list_accounts() -> list[dict[str, Any]]:
    rows = await database.list_earnapp_accounts()
    public: list[dict[str, Any]] = []
    for row in rows:
        try:
            keys = json.loads(str(row.get("credential_keys_json") or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            keys = []
        public.append(
            {
                "id": int(row["id"]),
                "profile_key": str(row.get("profile_key") or ""),
                "account_name": str(row.get("account_name") or ""),
                "email": str(row.get("email") or ""),
                "auth_method": str(row.get("auth_method") or ""),
                "state": str(row.get("state") or ""),
                "token_expires_at": row.get("token_expires_at"),
                "cookie_expires_at": row.get("cookie_expires_at"),
                "assigned_nodes": int(row.get("assigned_nodes") or 0),
                "credentials_present": {str(key): True for key in keys},
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
            }
        )
    return public


async def get_account_credentials(account_id: int) -> dict[str, Any] | None:
    row = await database.get_earnapp_account_credentials(account_id)
    if not row:
        return None
    credentials = row.pop("credentials", {})
    cookies = credentials.get("cookies", {}) if isinstance(credentials, Mapping) else {}
    row["cookies"] = dict(cookies) if isinstance(cookies, Mapping) else {}
    return row


async def assign_account(logical_node_id: str) -> dict[str, Any]:
    return await database.assign_earnapp_account(logical_node_id)


async def delete_account(account_id: int) -> bool:
    result = await database.delete_locked_earnapp_account(account_id)
    if result == "NOT_LOCKED":
        raise AccountDeletionDenied("EarnApp account must be ACCOUNT_LOCKED before deletion")
    return result == "DELETED"
