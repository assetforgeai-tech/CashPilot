import asyncio

from app.routers import proxies


def test_http_proxy_never_claims_udp_support():
    assert asyncio.run(proxies._probe_proxy_udp_capability("127.0.0.1", 8080, protocol="http")) is False


def test_socks5_udp_associate_success_is_detected():
    async def run():
        async def handler(reader, writer):
            assert await reader.readexactly(3) == b"\x05\x01\x00"
            writer.write(b"\x05\x00")
            await writer.drain()
            request = await reader.readexactly(10)
            assert request[:4] == b"\x05\x03\x00\x01"
            writer.write(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x1f\x90")
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            assert await proxies._probe_proxy_udp_capability("127.0.0.1", port, protocol="socks5") is True
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(run())
