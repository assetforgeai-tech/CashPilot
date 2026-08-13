"""MYST wallet inventory helpers."""

from __future__ import annotations

import hashlib
import json
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

    def normalize(address: str) -> str:
        address = str(address or "").strip().lower()
        if re.fullmatch(r"(0x)?[a-f0-9]{40}", address):
            return address.removeprefix("0x")
        return ""

    def find_address(node) -> str:
        if isinstance(node, dict):
            for key, item in node.items():
                if str(key).lower() == "address":
                    found = normalize(str(item))
                    if found:
                        return found
            for item in node.values():
                found = find_address(item)
                if found:
                    return found
        if isinstance(node, list):
            for item in node:
                found = find_address(item)
                if found:
                    return found
        return ""

    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        data = None
    found = find_address(data)
    if found:
        return found
    match = re.search(r'"address"\s*:\s*"(0x)?([a-fA-F0-9]{40})"', value)
    if match:
        return match.group(2).lower()
    return value[-12:]


def iter_wallet_records(raw: str) -> Iterable[dict[str, str]]:
    for wallet in normalize_wallet_lines(raw):
        yield {
            "raw_wallet": wallet,
            "wallet_fingerprint": fingerprint_wallet(wallet),
            "address": wallet_address_hint(wallet),
        }
