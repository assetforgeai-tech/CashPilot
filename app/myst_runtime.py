"""MYST direct-wallet runtime helpers."""

from __future__ import annotations

import io
import json
import re
import tarfile
from datetime import UTC, datetime
from typing import Any

_ADDR_RE = re.compile(r"0x[a-fA-F0-9]{40}")

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
    match = _ADDR_RE.search(text)
    if match:
        return match.group(0).lower()
    raise ValueError("MYST wallet material does not contain a 0x address")

def _tar_add(tf: tarfile.TarFile, name: str, data: bytes, mode: int = 0o600) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = mode
    tf.addfile(info, io.BytesIO(data))

def state_archive(raw_wallet: str, *, mmn_api_key: str, identity_passphrase: str = "") -> bytes:
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
    return buf.getvalue()

def _sh_single(value: str) -> str:
    return "'" + str(value).replace("'", "'\"'\"'") + "'"

def _set_dashboard_password(container: Any, password: str, *, port: int = 4449) -> None:
    if not password:
        return
    script = (
        "tmp=$(mktemp); "
        "for old in \"$NEW_PASSWORD\" mystberry; do "
        "curl -sS -m 10 -c $tmp -b $tmp -o /dev/null -w '%{http_code}' "
        "-X POST http://127.0.0.1:$PORT/tequilapi/auth/login "
        "-H 'Content-Type: application/json' "
        "-d \"{\\\"username\\\":\\\"myst\\\",\\\"password\\\":\\\"$old\\\"}\" | grep -Eq '^(200|204)$' && break; "
        "done; "
        "curl -fsS -m 10 -c $tmp -b $tmp "
        "-X PUT http://127.0.0.1:$PORT/tequilapi/auth/password "
        "-H 'Content-Type: application/json' "
        "-d \"{\\\"username\\\":\\\"myst\\\",\\\"old_password\\\":\\\"mystberry\\\",\\\"new_password\\\":\\\"$NEW_PASSWORD\\\"}\" >/dev/null || true; "
        "rm -f $tmp"
    )
    container.exec_run(["sh", "-lc", f"PORT={int(port)} NEW_PASSWORD={_sh_single(password)} {script}"])

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
    archive = state_archive(raw_wallet, mmn_api_key=mmn_api_key, identity_passphrase=identity_passphrase)
    container.stop(timeout=30)
    container.put_archive("/var/lib/mysterium-node", archive)
    container.restart(timeout=30)
    container.exec_run(["sh", "-lc", f"myst cli identities unlock {address} {_sh_single(identity_passphrase)} >/dev/null 2>&1 || true"])
    _set_dashboard_password(container, dashboard_password)
    if mmn_api_key:
        container.exec_run(["sh", "-lc", f"myst cli mmn {_sh_single(mmn_api_key)} >/dev/null 2>&1 || true"])
    return address
