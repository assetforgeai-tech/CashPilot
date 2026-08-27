"""EarnApp-only client for the restricted host LXD helper."""

from __future__ import annotations

import json
import os
import socket
from collections.abc import Mapping
from typing import Any

SOCKET_PATH = os.getenv("CASHPILOT_EARNAPP_AGENT_SOCKET", "/run/cashpilot-earnapp-agent/agent.sock")
_ALLOWED_RESULT = {
    "instance_id",
    "logical_node_id",
    "running",
    "online",
    "device_id",
    "version",
    "earnapp_active",
    "proxy_active",
    "runtime_backend",
    "binding_version",
    "action",
    "proxy_id",
    "observed_egress_ip",
    "probe_ok",
    "present",
    "previous_present",
    "candidate_present",
}


class EarnAppLxdHelperError(RuntimeError):
    """Structured host-helper failure with its HTTP status preserved."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = int(status_code)


def _redacted(value: Mapping[str, Any] | None) -> dict[str, Any]:
    source = value if isinstance(value, Mapping) else {}
    return {key: source[key] for key in _ALLOWED_RESULT if key in source}


def _request(
    method: str,
    path: str,
    *,
    payload: Mapping[str, Any] | None = None,
    timeout: float = 900,
) -> dict[str, Any]:
    body = json.dumps(dict(payload or {}), separators=(",", ":")).encode()
    request = (
        f"{method} {path} HTTP/1.1\r\n"
        "Host: localhost\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n\r\n"
    ).encode("ascii") + body
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(float(timeout))
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
        raise RuntimeError("EarnApp LXD helper returned an invalid HTTP response")
    status_line = headers.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
    try:
        status = int(status_line.split()[1])
        response = json.loads(response_body.decode())
    except (IndexError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("EarnApp LXD helper returned an invalid response") from exc
    if not isinstance(response, dict):
        raise RuntimeError("EarnApp LXD helper returned an invalid response")
    if status >= 400:
        raise EarnAppLxdHelperError(
            str(response.get("error") or f"EarnApp LXD helper failed with HTTP {status}"),
            status,
        )
    return response


def _cas(logical_node_id: str, generation: int, device_id: str) -> dict[str, Any]:
    return {
        "logical_node_id": str(logical_node_id),
        "generation": int(generation),
        "device_id": str(device_id),
    }


def deploy_node(
    logical_node_id: str,
    *,
    generation: int,
    account_id: int,
    device_id: str,
    identity: Mapping[str, Any],
    proxy: Mapping[str, Any],
    settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    limits = dict(settings or {})
    payload = {
        **_cas(logical_node_id, generation, device_id),
        "account_id": int(account_id),
        "identity": dict(identity),
        "proxy": dict(proxy),
        "lxd_cpu": int(limits.get("cpu") or 1),
        "lxd_memory_mib": int(limits.get("memory_mib") or 1024),
    }
    result = _request("POST", f"/v1/nodes/{logical_node_id}", payload=payload, timeout=1800)
    return _redacted(result)


def suspend_node(logical_node_id: str, *, generation: int, device_id: str) -> dict[str, Any]:
    return _redacted(
        _request(
            "POST",
            f"/v1/nodes/{logical_node_id}/suspend",
            payload=_cas(logical_node_id, generation, device_id),
        )
    )


def resume_node(logical_node_id: str, *, generation: int, device_id: str) -> dict[str, Any]:
    return _redacted(
        _request(
            "POST",
            f"/v1/nodes/{logical_node_id}/resume",
            payload=_cas(logical_node_id, generation, device_id),
        )
    )


def remove_node(logical_node_id: str, *, generation: int, device_id: str) -> dict[str, Any]:
    return _redacted(
        _request(
            "DELETE",
            f"/v1/nodes/{logical_node_id}",
            payload=_cas(logical_node_id, generation, device_id),
        )
    )


def node_evidence(logical_node_id: str, *, generation: int, device_id: str) -> dict[str, Any]:
    return _redacted(
        _request(
            "POST",
            f"/v1/nodes/{logical_node_id}/evidence",
            payload=_cas(logical_node_id, generation, device_id),
        )
    )


def node_presence(logical_node_id: str, *, generation: int, device_id: str) -> dict[str, Any]:
    """Check the host's exact LXD instance without relying on worker state."""
    return _redacted(
        _request(
            "POST",
            f"/v1/nodes/{logical_node_id}/presence",
            payload=_cas(logical_node_id, generation, device_id),
            timeout=30,
        )
    )


def proxy_binding_status(logical_node_id: str, *, generation: int, device_id: str) -> dict[str, Any]:
    """Read staged proxy artifacts from the exact LXD guest."""
    return _redacted(
        _request(
            "POST",
            f"/v1/nodes/{logical_node_id}/proxy/status",
            payload=_cas(logical_node_id, generation, device_id),
            timeout=30,
        )
    )


def discard_proxy_binding(
    logical_node_id: str,
    *,
    generation: int,
    device_id: str,
    expected_proxy_id: int,
    binding_version: str,
) -> dict[str, Any]:
    """Remove only an inactive staged candidate from the exact LXD guest."""
    return _redacted(
        _request(
            "POST",
            f"/v1/nodes/{logical_node_id}/proxy/discard",
            payload={
                **_cas(logical_node_id, generation, device_id),
                "expected_proxy_id": int(expected_proxy_id),
                "binding_version": str(binding_version),
            },
            timeout=60,
        )
    )


def apply_proxy_binding(
    logical_node_id: str,
    *,
    generation: int,
    device_id: str,
    expected_proxy_id: int,
    binding_version: str,
    proxy: Mapping[str, Any],
) -> dict[str, Any]:
    """Stage and restart one LXD node with a CAS-scoped proxy binding."""
    payload = {
        **_cas(logical_node_id, generation, device_id),
        "expected_proxy_id": int(expected_proxy_id),
        "binding_version": str(binding_version),
        "proxy": dict(proxy),
    }
    return _redacted(_request("POST", f"/v1/nodes/{logical_node_id}/proxy/apply", payload=payload, timeout=180))


def finalize_proxy_binding(
    logical_node_id: str,
    *,
    generation: int,
    device_id: str,
    expected_proxy_id: int,
    new_proxy_id: int,
    binding_version: str,
    commit: bool,
    expected_egress_ip: str = "",
    observed_egress_ip: str = "",
) -> dict[str, Any]:
    """Confirm or roll back a staged LXD proxy binding."""
    payload = {
        **_cas(logical_node_id, generation, device_id),
        "expected_proxy_id": int(expected_proxy_id),
        "new_proxy_id": int(new_proxy_id),
        "binding_version": str(binding_version),
        "commit": bool(commit),
        "expected_egress_ip": str(expected_egress_ip),
        "observed_egress_ip": str(observed_egress_ip),
    }
    return _redacted(_request("POST", f"/v1/nodes/{logical_node_id}/proxy/finalize", payload=payload, timeout=180))
