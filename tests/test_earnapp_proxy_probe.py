import asyncio
import json
import ssl
from unittest.mock import patch

import httpx
import pytest

from app import proxy_intelligence
from app.proxy_probe_profiles import earnapp


def test_only_cid_set_is_earnapp_eligible():
    assert earnapp.classify_verdict("CID_SET", "cid-1") == "eligible"
    assert earnapp.classify_verdict("BLACKLIST", "earnapp_blacklist") == "blocked"
    assert earnapp.classify_verdict("DECLINE", "ip_quality.vpn") == "quality_rejected"
    assert earnapp.classify_verdict("TIMEOUT", "no response") == "unknown"
    assert earnapp.classify_verdict("WSS_FAIL", "connect failed") == "unknown"


def test_tunnel_identity_preserves_the_supplied_earnapp_contract():
    identity = earnapp.build_tunnel_identity(now_ms=1_700_000_000_000, uuid_hex="ab" * 16)

    assert identity["appid"] == "ios_com.brd.earnapp"
    assert identity["version"] == "1.617.813"
    assert identity["uuid"] == f"sdk-ios-{'ab' * 16}"
    assert identity["consent_ts"] == 1_700_000_000_000
    assert identity["status_send"] is True
    assert identity["ipv6_supported"] is False
    assert json.loads(identity["usage"]["app_bytes"])["wifi_connected"] is True


def test_earnapp_tls_context_matches_the_supplied_probe_certificate_contract():
    context = earnapp.build_tls_context()

    assert context.check_hostname is False
    assert context.verify_mode == ssl.CERT_NONE


def test_client_websocket_text_frames_are_masked_and_round_trip():
    frame = earnapp.encode_client_text_frame("hello", mask_key=b"\x01\x02\x03\x04")

    assert frame[:2] == b"\x81\x85"
    assert frame[2:6] == b"\x01\x02\x03\x04"
    assert bytes(value ^ b"\x01\x02\x03\x04"[index % 4] for index, value in enumerate(frame[6:])) == b"hello"


def test_client_websocket_control_frames_preserve_arbitrary_binary_payload():
    frame = earnapp.encode_client_frame(b"\xff\x00\xfe", opcode=10, mask_key=b"\x01\x02\x03\x04")

    assert frame[:2] == b"\x8a\x83"
    assert frame[2:6] == b"\x01\x02\x03\x04"
    assert bytes(value ^ b"\x01\x02\x03\x04"[index % 4] for index, value in enumerate(frame[6:])) == b"\xff\x00\xfe"


def test_server_websocket_frame_reader_handles_extended_payloads():
    async def run():
        payload = b"x" * 130
        reader = asyncio.StreamReader()
        reader.feed_data(b"\x81\x7e" + len(payload).to_bytes(2, "big") + payload)
        reader.feed_eof()
        return await earnapp.read_server_frame(reader, timeout=0.1)

    opcode, final, payload = asyncio.run(run())
    assert opcode == 1
    assert final is True
    assert payload == b"x" * 130


def test_ip_intelligence_uses_country_evidence_and_quality_flag_precedence():
    country = proxy_intelligence.normalize_ipwho_payload(
        {"success": True, "ip": "203.0.113.7", "country": "Singapore", "country_code": "SG"}
    )
    quality = proxy_intelligence.normalize_ipapi_payload(
        {
            "ip": "203.0.113.7",
            "cc": "SG",
            "is_datacenter": True,
            "is_proxy": True,
            "is_vpn": True,
        }
    )

    merged = proxy_intelligence.merge_intelligence("203.0.113.7", country=country, quality=quality)

    assert merged["country_code"] == "SG"
    assert merged["country_name"] == "Singapore"
    assert merged["location"] == "Singapore"
    assert merged["ip_type"] == "vpn"
    assert merged["geo_source"] == "ipwho.is"
    assert merged["ip_type_source"] == "ipapi.is"


def test_ip_intelligence_marks_an_unflagged_public_ip_as_residential_inference():
    merged = proxy_intelligence.merge_intelligence(
        "198.51.100.10",
        country={"country_code": "US", "country_name": "United States", "geo_source": "ipwho.is"},
        quality={
            "is_datacenter": False,
            "is_proxy": False,
            "is_vpn": False,
            "is_tor": False,
            "ip_type_source": "ipapi.is",
        },
    )

    assert merged["ip_type"] == "residential"
    assert merged["ip_type_confidence"] == "inferred"


@pytest.mark.asyncio
async def test_ip_intelligence_falls_back_to_reachable_regional_quality_endpoint():
    class Response:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url):
            if "ipwho.is" in url:
                return Response(200, {"success": True, "country": "Viet Nam", "country_code": "VN"})
            if "api.ipapi.is" in url:
                raise httpx.ConnectError("primary unreachable")
            return Response(
                200,
                {
                    "cc": "VN",
                    "is_datacenter": False,
                    "is_proxy": False,
                    "is_vpn": False,
                    "is_tor": False,
                },
            )

    with patch("app.proxy_intelligence.httpx.AsyncClient", return_value=Client()):
        result = await proxy_intelligence.lookup_ip_intelligence("8.8.8.8")

    assert result["country_code"] == "VN"
    assert result["ip_type"] == "residential"
    assert result["ip_type_source"] == "us.ipapi.is"


@pytest.mark.asyncio
async def test_ip_intelligence_does_not_bypass_a_quality_rate_limit_with_other_regions():
    calls = []

    class Response:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url):
            calls.append(url)
            if "ipwho.is" in url:
                return Response(200, {"success": True, "country": "Viet Nam", "country_code": "VN"})
            return Response(429, {})

    with patch("app.proxy_intelligence.httpx.AsyncClient", return_value=Client()):
        result = await proxy_intelligence.lookup_ip_intelligence("8.8.8.8")

    assert result["ip_type"] == "unknown"
    assert sum("ipapi.is" in url for url in calls) == 1
