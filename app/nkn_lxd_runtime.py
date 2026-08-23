"""NKN-only client for the restricted host LXD helper.

The worker never receives a general LXD socket. This module speaks a tiny
localhost Unix-socket protocol and keeps the wallet assignment CAS in every
request so a stale heartbeat cannot affect a newer node.
"""

from __future__ import annotations

import json
import os
import socket
from collections.abc import Mapping
from typing import Any

SOCKET_PATH = os.getenv("CASHPILOT_NKN_AGENT_SOCKET", "/run/cashpilot-nkn-agent/agent.sock")


def _request(method: str, path: str, *, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    body = json.dumps(dict(payload or {}), separators=(",", ":")).encode("utf-8")
    request = (
        f"{method} {path} HTTP/1.1\r\n"
        "Host: localhost\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n\r\n"
    ).encode("ascii") + body
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(900)
        client.connect(SOCKET_PATH)
        client.sendall(request)
        chunks: list[bytes] = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    raw = b"".join(chunks)
    headers, separator, response_body = raw.partition(b"\r\n\r\n")
    if not separator:
        raise RuntimeError("NKN LXD helper returned an invalid HTTP response")
    status_line = headers.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
    try:
        status = int(status_line.split()[1])
    except (IndexError, ValueError) as exc:
        raise RuntimeError("NKN LXD helper returned an invalid HTTP status") from exc
    try:
        response = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("NKN LXD helper returned invalid JSON") from exc
    if not isinstance(response, dict):
        raise RuntimeError("NKN LXD helper returned an invalid response")
    if status >= 400:
        raise RuntimeError(str(response.get("error") or f"NKN LXD helper failed with HTTP {status}"))
    return response


def _cas(slot_id: str, wallet_id: int, wallet_assignment_version: int, lease_client_id: str) -> dict[str, Any]:
    return {
        "slot_id": slot_id,
        "wallet_id": int(wallet_id),
        "wallet_assignment_version": int(wallet_assignment_version),
        "lease_client_id": str(lease_client_id),
    }


def deploy_slot(
    slot: Mapping[str, Any],
    assignment: Mapping[str, Any],
    *,
    settings: Mapping[str, Any],
) -> dict[str, Any]:
    slot_id = str(slot.get("slot_id") or "")
    payload = {
        "slot_id": slot_id,
        "public_ip": str(slot.get("public_ip") or ""),
        "private_ip": str(slot.get("private_ip") or ""),
        "interface": str(slot.get("interface") or ""),
        "subnet": str(slot.get("subnet") or ""),
        "gateway": str(slot.get("gateway") or ""),
        "bridge_subnet": str(slot.get("bridge_subnet") or ""),
        "bridge_gateway": str(slot.get("bridge_gateway") or ""),
        "wallet_id": int(assignment["wallet_id"]),
        "wallet_assignment_version": int(assignment["wallet_assignment_version"]),
        "lease_client_id": str(assignment["lease_client_id"]),
        "wallet_json": str(assignment["wallet_json"]),
        "wallet_pswd": str(assignment["wallet_pswd"]),
        "beneficiary_address": str(assignment["beneficiary_address"]),
        "lxd_cpu": int(settings["cpu"]),
        "lxd_memory_mib": int(settings["memory_mib"]),
    }
    return _request("POST", f"/v1/slots/{slot_id}", payload=payload)


def suspend_slot(
    slot_id: str, *, wallet_id: int, wallet_assignment_version: int, lease_client_id: str
) -> dict[str, Any]:
    return _request(
        "POST",
        f"/v1/slots/{slot_id}/suspend",
        payload=_cas(slot_id, wallet_id, wallet_assignment_version, lease_client_id),
    )


def resume_slot(
    slot_id: str, *, wallet_id: int, wallet_assignment_version: int, lease_client_id: str
) -> dict[str, Any]:
    return _request(
        "POST",
        f"/v1/slots/{slot_id}/resume",
        payload=_cas(slot_id, wallet_id, wallet_assignment_version, lease_client_id),
    )


def remove_slot(
    slot_id: str,
    *,
    wallet_id: int,
    wallet_assignment_version: int,
    lease_client_id: str,
    delete_volume: bool = True,
) -> dict[str, Any]:
    payload = _cas(slot_id, wallet_id, wallet_assignment_version, lease_client_id)
    payload["delete_volume"] = bool(delete_volume)
    return _request("DELETE", f"/v1/slots/{slot_id}", payload=payload)


def node_evidence(state: Mapping[str, Any]) -> dict[str, Any]:
    slot_id = str(state.get("slot_id") or "")
    payload = _cas(
        slot_id,
        int(state.get("wallet_id") or 0),
        int(state.get("wallet_assignment_version") or 0),
        str(state.get("lease_client_id") or ""),
    )
    result = _request("POST", f"/v1/slots/{slot_id}/evidence", payload=payload)
    allowed = {"running", "online", "sync_state", "node_id", "rpc_reachable", "runtime_backend"}
    return {key: result[key] for key in allowed if key in result}
