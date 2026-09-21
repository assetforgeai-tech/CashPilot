"""Earn.fm proxy qualification.

Earn.fm opens a TLS/WebSocket socket on port 8443.  A generic HTTPS probe is
not sufficient: some endpoints accept ordinary HTTPS but return 502 when the
Earn.fm socket is CONNECTed.  Qualification therefore tests the exact socket
targets used by the client.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import socket
import ssl
import time
from typing import Any

PROBE_TARGETS = (("socket-prod.earn.fm", 8443), ("socket-backup.earn.fm", 8443))
PROBE_VERSION = "earnfm-socket-8443-v1"


async def resolve_socket_targets() -> tuple[tuple[str, str, int], ...]:
    """Mirror the client path: DNS first, then CONNECT the resolved IPv4."""
    resolved: list[tuple[str, str, int]] = []
    loop = asyncio.get_running_loop()
    for hostname, port in PROBE_TARGETS:
        infos = await loop.getaddrinfo(hostname, port, family=2, type=socket.SOCK_STREAM)
        for info in infos:
            candidate = (hostname, str(info[4][0]), port)
            if candidate not in resolved:
                resolved.append(candidate)
    return tuple(resolved)


async def _read_headers(reader: asyncio.StreamReader, timeout: float) -> str:
    raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout)
    if len(raw) > 65536:
        raise ValueError("proxy response headers too large")
    return raw.decode("iso-8859-1", "replace").split("\r\n", 1)[0]


async def _socks5_connect(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    target_host: str,
    target_port: int,
    username: str,
    password: str,
    timeout: float,
) -> None:
    methods = b"\x00" if not (username or password) else b"\x00\x02"
    writer.write(b"\x05" + bytes([len(methods)]) + methods)
    await writer.drain()
    selected = await asyncio.wait_for(reader.readexactly(2), timeout)
    if selected != b"\x05\x00" and selected != b"\x05\x02":
        raise ConnectionError("SOCKS5 authentication rejected")
    if selected == b"\x05\x02":
        user = username.encode("utf-8")
        secret = password.encode("utf-8")
        if len(user) > 255 or len(secret) > 255:
            raise ValueError("SOCKS5 credentials too long")
        writer.write(b"\x01" + bytes([len(user)]) + user + bytes([len(secret)]) + secret)
        await writer.drain()
        if await asyncio.wait_for(reader.readexactly(2), timeout) != b"\x01\x00":
            raise ConnectionError("SOCKS5 credentials rejected")
    encoded = target_host.encode("idna")
    writer.write(b"\x05\x01\x00\x03" + bytes([len(encoded)]) + encoded + int(target_port).to_bytes(2, "big"))
    await writer.drain()
    reply = await asyncio.wait_for(reader.readexactly(4), timeout)
    if reply[:2] != b"\x05\x00":
        raise ConnectionError(f"SOCKS5 CONNECT rejected: {reply[1]}")
    sizes = {1: 4, 4: 16}
    if reply[3] in sizes:
        await asyncio.wait_for(reader.readexactly(sizes[reply[3]] + 2), timeout)
    elif reply[3] == 3:
        length = (await asyncio.wait_for(reader.readexactly(1), timeout))[0]
        await asyncio.wait_for(reader.readexactly(length + 2), timeout)
    else:
        raise ConnectionError("SOCKS5 returned invalid address type")


async def _http_connect(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    target_host: str,
    target_port: int,
    username: str,
    password: str,
    timeout: float,
) -> None:
    headers = [
        f"CONNECT {target_host}:{target_port} HTTP/1.1",
        f"Host: {target_host}:{target_port}",
        "Proxy-Connection: keep-alive",
    ]
    if username or password:
        token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        headers.append(f"Proxy-Authorization: Basic {token}")
    writer.write(("\r\n".join(headers) + "\r\n\r\n").encode("ascii"))
    await writer.drain()
    status = await _read_headers(reader, timeout)
    if " 200 " not in f" {status} ":
        raise ConnectionError(f"HTTP CONNECT rejected: {status}")


async def _probe_target(
    *,
    proxy_host: str,
    proxy_port: int,
    target_host: str,
    target_port: int,
    server_hostname: str,
    protocol: str,
    username: str,
    password: str,
    timeout: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    reader, writer = await asyncio.wait_for(asyncio.open_connection(proxy_host, proxy_port), timeout=timeout)
    try:
        if protocol == "socks5":
            await _socks5_connect(
                reader,
                writer,
                target_host=target_host,
                target_port=target_port,
                username=username,
                password=password,
                timeout=timeout,
            )
        elif protocol == "http":
            await _http_connect(
                reader,
                writer,
                target_host=target_host,
                target_port=target_port,
                username=username,
                password=password,
                timeout=timeout,
            )
        else:
            raise ValueError("Earn.fm probe supports http and socks5")
        context = ssl.create_default_context()
        await asyncio.wait_for(writer.start_tls(context, server_hostname=server_hostname), timeout=timeout)
        return {"host": target_host, "port": target_port, "latency_ms": int((time.perf_counter() - started) * 1000)}
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


async def probe_earnfm_proxy(
    host: str,
    port: int,
    *,
    protocol: str,
    username: str = "",
    password: str = "",
    timeout_ms: int = 12000,
) -> dict[str, Any]:
    protocol = str(protocol or "").strip().lower()
    result: dict[str, Any] = {
        "eligibility": "unknown",
        "reason": "",
        "successful_target": "",
        "latency_ms": None,
        "probe_version": PROBE_VERSION,
    }
    timeout = max(4.0, min(15.0, float(timeout_ms or 12000) / 1000))
    failures: list[str] = []
    try:
        socket_targets = await resolve_socket_targets()
    except OSError:
        result.update(eligibility="unknown", reason="earnfm_dns_failed")
        return result
    for server_hostname, target_host, target_port in socket_targets:
        try:
            evidence = await _probe_target(
                proxy_host=str(host or "").strip(),
                proxy_port=int(port or 0),
                target_host=target_host,
                target_port=target_port,
                server_hostname=server_hostname,
                protocol=protocol,
                username=str(username or ""),
                password=str(password or ""),
                timeout=timeout,
            )
        except Exception as exc:  # qualification is fail-closed
            failures.append(type(exc).__name__)
            continue
        result.update(
            eligibility="eligible",
            successful_target=server_hostname,
            latency_ms=evidence.get("latency_ms"),
            reason="tls_connect_ok",
        )
        return result
    result.update(eligibility="quality_rejected", reason="earnfm_socket_8443_unreachable")
    if failures:
        result["errors"] = failures
    return result
