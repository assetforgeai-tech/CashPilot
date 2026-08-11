"""MYST direct-wallet runtime helpers."""

from __future__ import annotations

import io
import json
import re
import tarfile
from datetime import UTC, datetime
from typing import Any

import bcrypt

_ADDR_RE = re.compile(r"0x[a-fA-F0-9]{40}")
_BARE_ADDR_RE = re.compile(r"[a-fA-F0-9]{40}")

def wallet_address(raw_wallet: str) -> str:
    text = (raw_wallet or "").strip()
    if not text:
        raise ValueError("MYST wallet material is empty")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        for key in ("address", "Address", "wallet_address", "walletAddress"):
            value = str(data.get(key) or "").strip()
            if _ADDR_RE.fullmatch(value):
                return value.lower()
            if _BARE_ADDR_RE.fullmatch(value):
                return f"0x{value.lower()}"
    match = _ADDR_RE.search(text)
    if match:
        return match.group(0).lower()
    raise ValueError("MYST wallet material does not contain an address")

def _tar_add(tf: tarfile.TarFile, name: str, data: bytes, mode: int = 0o600) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = mode
    tf.addfile(info, io.BytesIO(data))

def state_archive(
    raw_wallet: str,
    *,
    mmn_api_key: str,
    identity_passphrase: str = "",
    dashboard_password: str = "",
) -> bytes:
    address = wallet_address(raw_wallet)
    short = address.removeprefix("0x")
    wallet_name = f"keystore/UTC--{datetime.now(UTC).strftime('%Y-%m-%dT%H-%M-%S.000000000Z')}--{short}"
    config = (
        'active-services = "dvpn,data_transfer,monitoring,scraping"\n\n'
        "[terms]\n"
        "  consumer-agreed = true\n"
        "  provider-agreed = true\n"
        '  version = "0.0.53"\n\n'
        "[mmn]\n"
        f"  api-key = {mmn_api_key!r}\n\n"
        "[identity]\n"
        f"  passphrase = {identity_passphrase!r}\n"
    )
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        _tar_add(tf, wallet_name, raw_wallet.strip().encode())
        _tar_add(tf, "keystore/remember.json", json.dumps({"identity": {"address": address}}, separators=(",", ":")).encode())
        _tar_add(tf, "config-mainnet.toml", config.encode())
        if dashboard_password:
            _tar_add(tf, "nodeui-pass", bcrypt.hashpw(dashboard_password.encode("utf-8"), bcrypt.gensalt()).decode("ascii").encode())
    return buf.getvalue()


def _sh_single(value: str) -> str:
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


def apply_direct_wallet(
    container: Any,
    wallet: dict[str, Any],
    *,
    dashboard_password: str,
    mmn_api_key: str,
    identity_passphrase: str = "",
) -> str:
    raw_wallet = str(wallet.get("raw_wallet") or wallet.get("myst_wallet_raw") or "")
    address = wallet_address(raw_wallet)
    archive = state_archive(
        raw_wallet,
        **{
            "mmn_api_key": mmn_api_key,
            "identity_passphrase": identity_passphrase,
            "dashboard_password": dashboard_password,
        },
    )
    container.stop(timeout=30)
    container.put_archive("/var/lib/mysterium-node", archive)
    container.restart(timeout=30)
    container.exec_run(["sh", "-lc", f"myst cli identities unlock {address} {_sh_single(identity_passphrase)} >/dev/null 2>&1 || true"])
    if mmn_api_key:
        container.exec_run(["sh", "-lc", f"myst cli mmn {_sh_single(mmn_api_key)} >/dev/null 2>&1 || true"])
    return address
