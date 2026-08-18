"""NKN wallet inventory helpers."""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Iterable


def wallet_address(wallet_json: str) -> str:
    try:
        data = json.loads(wallet_json)
    except json.JSONDecodeError:
        return ""
    return str(data.get("Address") or "").strip()


def iter_wallet_records_from_zip(raw_zip: bytes) -> Iterable[dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
        names = {name.replace("\\", "/"): name for name in zf.namelist() if not name.endswith("/")}
        folders = sorted({name.split("/", 1)[0] for name in names if "/" in name})
        for folder in folders:
            json_name = names.get(f"{folder}/wallet.json")
            pswd_name = names.get(f"{folder}/wallet.pswd")
            if not json_name or not pswd_name:
                continue
            wallet_json = zf.read(json_name).decode("utf-8").strip()
            wallet_pswd = zf.read(pswd_name).decode("utf-8").strip()
            address = wallet_address(wallet_json)
            if not address:
                continue
            yield {
                "folder_name": folder,
                "wallet_json": wallet_json,
                "wallet_pswd": wallet_pswd,
                "wallet_fingerprint": folder,
                "address": address,
            }


def normalize_wallet_record(record: dict[str, str]) -> dict[str, str] | None:
    folder = str(record.get("folder_name") or "").strip().strip("/\\")
    wallet_json = str(record.get("wallet_json") or "").strip()
    wallet_pswd = str(record.get("wallet_pswd") or "").strip()
    address = wallet_address(wallet_json)
    if not folder or not wallet_json or not wallet_pswd or not address:
        return None
    return {
        "folder_name": folder,
        "wallet_json": wallet_json,
        "wallet_pswd": wallet_pswd,
        "wallet_fingerprint": folder,
        "address": address,
    }
