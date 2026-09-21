from app import catalog, provider_modes, provider_runtime


def test_proxies_sx_uses_provider_proxy_egress():
    runtime = provider_runtime.get("proxies-sx")
    assert runtime is not None
    assert runtime.modes == ("proxy",)
    assert runtime.topology == "slot_proxy"
    assert runtime.network_contract_for("proxy")["fallback"] == "none"


def test_proxies_sx_catalog_requires_cashpilot_proxy_sidecar():
    service = catalog.get_service("proxies-sx")
    assert catalog.service_egress_mode(service) == "proxy"
    assert (service.get("egress") or {}).get("fallback") == "none"


def test_proxies_sx_rejects_direct_deploy_requests():
    try:
        provider_modes.expand_requested("proxies-sx", "direct")
    except ValueError as exc:
        assert "does not support direct mode" in str(exc)
    else:
        raise AssertionError("Proxies.sx must never accept a direct deployment lane")


def test_proxies_sx_rejects_legacy_direct_compatibility_path():
    try:
        provider_modes.expand_requested("proxies-sx", "legacy")
    except ValueError as exc:
        assert "does not support legacy mode" in str(exc)
    else:
        raise AssertionError("Proxies.sx legacy mode must not bypass proxy-only policy")
