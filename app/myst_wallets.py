"""MYST wallet inventory helpers."""

from __future__ import annotations

import hashlib
import re
from typing import Iterable


def normalize_wallet_lines(raw: str) -> list[str]:
    return [line.strip() for line in re.split(r"[\r\n]+", raw) if line.strip()]


def fingerprint_wallet(raw_wallet: str) -> str:
    return hashlib.sha256(raw_wallet.strip().encode()).hexdigest()[:16]


def wallet_address_hint(raw_wallet: str) -> str:
    value = raw_wallet.strip()
    if not value:
        return ""
    return value[-12:]


def iter_wallet_records(raw: str) -> Iterable[dict[str, str]]:
    for wallet in normalize_wallet_lines(raw):
        yield {
            "raw_wallet": wallet,
            "wallet_fingerprint": fingerprint_wallet(wallet),
            "address": wallet_address_hint(wallet),
        }
