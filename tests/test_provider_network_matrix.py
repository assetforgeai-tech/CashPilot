from app import provider_runtime, singbox_config


def test_proxy_provider_policy_declares_fail_closed_contract():
    proxy_slugs = [slug for slug, spec in provider_runtime.PROVIDERS.items() if "proxy" in spec.modes]
    assert proxy_slugs
    for slug in proxy_slugs:
        spec = provider_runtime.get(slug)
        contract = spec.network_contract_for("proxy")
        assert contract["fallback"] == "none", slug
        assert contract["dns"] == "tunneled", slug
        assert contract["fail_closed"] is True, slug
        assert spec.proxy_udp_direct is False, slug


def test_proxy_renderer_has_common_fail_closed_controls():
    config = singbox_config.render_tun_proxy_config(
        {"host": "proxy.example", "port": 1080, "protocol": "socks5"},
        worker_name="matrix",
    )
    inbound = config["inbounds"][0]
    assert inbound["type"] == "tun"
    assert inbound["auto_route"] is True
    assert inbound["auto_redirect"] is True
    assert inbound["strict_route"] is True
    assert config["route"]["final"] == "proxy-out"
    assert {"port": 53, "action": "hijack-dns"} in config["route"]["rules"]
    assert config["dns"]["strategy"] == "ipv4_only"
    assert config["dns"]["servers"][0]["detour"] == "proxy-out"


def test_proxy_udp_exception_is_explicit_and_narrow():
    assert provider_runtime.proxy_udp_direct("traffmonetizer") is False
    assert provider_runtime.proxy_udp_direct("packetstream") is False
    assert provider_runtime.proxy_udp_direct("proxies-sx") is False
    assert provider_runtime.proxy_udp_direct("mysterium") is True


def test_every_provider_declares_the_active_proxy_transport():
    for slug, spec in provider_runtime.PROVIDERS.items():
        if "proxy" in spec.modes:
            assert spec.proxy_transport in {"in_container", "singbox_compat"}, slug
        else:
            assert spec.proxy_transport == "direct_only", slug

    assert provider_runtime.proxy_transport("earnapp") == "in_container"
    assert provider_runtime.proxy_transport("mysterium") == "direct_only"
    assert provider_runtime.proxy_transport("nkn") == "direct_only"
