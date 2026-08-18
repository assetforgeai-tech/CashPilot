from __future__ import annotations


def parse_account_line(line: str) -> dict[str, str]:
    parts = [part.strip() for part in str(line or "").strip().split("|")]
    if len(parts) < 3:
        return {}
    email, oauth_refresh_token, xsrf_token = parts[:3]
    if not email or not oauth_refresh_token or not xsrf_token:
        return {}
    return {
        "email": email,
        "oauth_refresh_token": oauth_refresh_token,
        "xsrf_token": xsrf_token,
    }
