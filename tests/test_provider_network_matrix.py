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


def test_proxy_renderer_pins_doh_bootstrap_without_direct_dns():
    config = singbox_config.render_tun_proxy_config(
        {"host": "14.243.204.216", "port": 24356, "protocol": "http"},
        worker_name="matrix",
    )
    doh = config["dns"]["servers"][0]
    assert doh["server"] == "1.1.1.1"
    assert doh["tls"] == {"enabled": True, "server_name": "cloudflare-dns.com"}
    assert doh["detour"] == "proxy-out"
    assert len(config["dns"]["servers"]) == 1


def test_proxy_renderer_bypasses_tun_only_for_pinned_proxy_endpoint():
    config = singbox_config.render_tun_proxy_config(
        {"host": "14.243.204.216", "port": 24356, "protocol": "http"},
        worker_name="matrix",
    )
    assert {
        "ip_cidr": ["14.243.204.216/32"],
        "outbound": "direct",
    } in config["route"]["rules"]
    assert config["inbounds"][0]["route_exclude_address"] == ["14.243.204.216/32"]


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


def test_proxy_transport_exceptions_are_explicit_in_provider_matrix():
    assert provider_runtime.get("earnapp").proxy_transport_exception == ""
    assert "in-container migration pending" in provider_runtime.get("proxies-sx").proxy_transport_exception
    assert provider_runtime.get("mysterium").proxy_transport_exception == ""


def test_proxy_providers_share_the_versioned_fail_closed_contract():
    proxy_slugs = [slug for slug, spec in provider_runtime.PROVIDERS.items() if "proxy" in spec.modes]
    assert provider_runtime.proxy_contract("earnapp") == "earnapp-style-v1"
    for slug in proxy_slugs:
        assert provider_runtime.proxy_contract(slug) == "earnapp-style-v1", slug


def test_direct_only_providers_do_not_claim_proxy_contract():
    assert provider_runtime.proxy_contract("mysterium") == "direct-only"
    assert provider_runtime.proxy_contract("nkn") == "direct-only"


def test_capability_matrix_is_explicit_for_every_provider_lane():
    for slug, spec in provider_runtime.PROVIDERS.items():
        matrix = provider_runtime.capability_matrix(slug)
        assert set(matrix) == {"direct", "proxy"} & set(spec.modes)
        for mode, capabilities in matrix.items():
            assert capabilities["dns"] in {"provider_native", "tunneled"}
            assert capabilities["ipv6"] in {"explicit", "disabled_or_tunneled"}
            assert capabilities["udp"] in {"explicit", "blocked_by_default", "direct_exception"}
            assert capabilities["direct_fallback"] is False
            assert capabilities["watchdog"] is (mode == "proxy")
            assert capabilities["restart"] in {"observe", "restart", "rotate"}


def test_unsupported_capability_matrix_lane_is_rejected():
    import pytest

    with pytest.raises(ValueError, match="unsupported egress lane"):
        provider_runtime.capability_matrix("nkn", mode="proxy")


def test_catalog_runtime_publishes_the_same_capability_matrix():
    assert provider_runtime.catalog_runtime("earnfm")["capabilities"] == provider_runtime.capability_matrix("earnfm")
