import pytest

from app.proxy_probe_profiles import earnfm


def test_earnfm_probe_uses_both_socket_hosts_on_port_8443():
    assert earnfm.PROBE_TARGETS == (
        ("socket-prod.earn.fm", 8443),
        ("socket-backup.earn.fm", 8443),
    )


@pytest.mark.asyncio
async def test_earnfm_probe_is_eligible_when_one_socket_path_carries_tls(monkeypatch):
    calls = []

    async def fake_resolve():
        return (
            ("socket-prod.earn.fm", "192.0.2.10", 8443),
            ("socket-backup.earn.fm", "192.0.2.20", 8443),
        )

    async def fake_connect(
        *, proxy_host, proxy_port, target_host, target_port, server_hostname, protocol, username, password, timeout
    ):
        calls.append((target_host, target_port, server_hostname, protocol))
        if target_host == "192.0.2.10":
            raise ConnectionError("502 Bad Gateway")
        return {"host": target_host, "port": target_port, "latency_ms": 12}

    monkeypatch.setattr(earnfm, "resolve_socket_targets", fake_resolve)
    monkeypatch.setattr(earnfm, "_probe_target", fake_connect)
    result = await earnfm.probe_earnfm_proxy("proxy.example", 1080, protocol="http")

    assert result["eligibility"] == "eligible"
    assert result["successful_target"] == "socket-backup.earn.fm"
    assert calls == [
        ("192.0.2.10", 8443, "socket-prod.earn.fm", "http"),
        ("192.0.2.20", 8443, "socket-backup.earn.fm", "http"),
    ]


@pytest.mark.asyncio
async def test_earnfm_probe_rejects_proxy_that_cannot_carry_either_socket(monkeypatch):
    async def fake_resolve():
        return (("socket-prod.earn.fm", "192.0.2.10", 8443),)

    async def fake_connect(**_kwargs):
        raise ConnectionError("502 Bad Gateway")

    monkeypatch.setattr(earnfm, "resolve_socket_targets", fake_resolve)
    monkeypatch.setattr(earnfm, "_probe_target", fake_connect)
    result = await earnfm.probe_earnfm_proxy("proxy.example", 1080, protocol="http")

    assert result["eligibility"] == "quality_rejected"
    assert result["reason"] == "earnfm_socket_8443_unreachable"
