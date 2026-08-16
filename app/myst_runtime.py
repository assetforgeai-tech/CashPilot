"""MYST direct-wallet runtime helpers."""

from __future__ import annotations

import io
import json
import logging
import re
import tarfile
from datetime import UTC, datetime
from typing import Any

import bcrypt

logger = logging.getLogger(__name__)
_ADDR_RE = re.compile(r"0x[a-fA-F0-9]{40}")
_BARE_ADDR_RE = re.compile(r"[a-fA-F0-9]{40}")
_ACTIVE_SERVICES = "wireguard,dvpn,data_transfer,monitoring,scraping"

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
) -> bytes:
    address = wallet_address(raw_wallet)
    short = address.removeprefix("0x")
    wallet_name = f"keystore/UTC--{datetime.now(UTC).strftime('%Y-%m-%dT%H-%M-%S.000000000Z')}--{short}"
    config = (
        f'active-services = "{_ACTIVE_SERVICES}"\n\n'
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
    return buf.getvalue()

def _sh_single(value: str) -> str:
    return "'" + str(value).replace("'", "'\"'\"'") + "'"

def nodeui_password_hash(password: str) -> str:
    if not password:
        return ""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=10, prefix=b"2a")).decode()

def _nodeui_password_archive(password: str) -> bytes:
    if not password:
        return b""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        _tar_add(tf, "nodeui-pass", (nodeui_password_hash(password) + "\n").encode())
    return buf.getvalue()

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
        },
    )
    container.stop(timeout=30)
    container.put_archive("/var/lib/mysterium-node", archive)
    if dashboard_password:
        container.put_archive("/var/lib/mysterium-node", _nodeui_password_archive(dashboard_password))
    container.restart(timeout=30)
    container.exec_run(["sh", "-lc", f"myst cli identities unlock {address} {_sh_single(identity_passphrase)} >/dev/null 2>&1 || true"])
    if mmn_api_key:
        container.exec_run(["sh", "-lc", f"myst cli mmn {_sh_single(mmn_api_key)} >/dev/null 2>&1 || true"])
    container.exec_run(
        [
            "sh",
            "-lc",
            "myst cli service list 2>/dev/null | grep -qi 'Type: wireguard' || "
            f"myst cli service start {address} wireguard >/dev/null 2>&1 || true",
        ]
    )
    return address

def registration_status(container: Any, address: str) -> str:
    if not address:
        return ""
    try:
        result = container.exec_run(["sh", "-lc", f"myst cli identities get {address} 2>/dev/null || true"])
        output = result.output.decode("utf-8", "ignore") if getattr(result, "output", None) else ""
    except Exception:
        return ""
    for line in output.splitlines():
        if "registration status" not in line.lower():
            continue
        _, _, value = line.partition(":")
        return value.strip()
    return ""
