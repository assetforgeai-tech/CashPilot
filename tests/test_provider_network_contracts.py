from __future__ import annotations

from app import earnapp_runtime, provider_runtime


def test_active_provider_matrix_is_explicit_and_earnapp_is_docker_only():
    assert provider_runtime.ACTIVE_SLUGS
    assert provider_runtime.platform_deployment_allowed("earnapp", "macos", "docker")
    assert provider_runtime.platform_deployment_allowed("earnapp", "ios", "docker")
    assert provider_runtime.platform_deployment_allowed("earnapp", "ubuntu", "docker")
    assert not provider_runtime.platform_deployment_allowed("earnapp", "ubuntu", "lxd")
    assert not provider_runtime.platform_deployment_allowed("earnapp", "", "docker")


def test_earnapp_runtime_contract_contains_fail_closed_tcp_and_dns_rules():
    source = earnapp_runtime.__file__
    text = open(source, encoding="utf-8").read()
    assert "CP_EARNAPP_OUT" in text
    assert 'iptables -A CP_EARNAPP_OUT -j DROP' in text
    assert "CP_EARNAPP_DNS" in text
    assert "cloudflare-dns.com" in text
