from app import catalog, provider_modes, provider_runtime


def test_provider_modes_cover_15_runtime_providers_including_nkn():
    providers = provider_modes.BOTH | provider_modes.PROXY_ONLY | provider_modes.DIRECT_ONLY
    active = {svc["slug"] for svc in catalog.get_services()}
    assert len(providers) == 15
    assert providers == active == set(provider_runtime.ACTIVE_SLUGS)
    assert "adnade" not in providers
    assert "dawn" not in providers
    assert "titan" not in providers
    assert providers == active
    assert provider_modes.supported_modes("nkn") == {"direct"}


def test_uprock_is_proxy_only():
    assert provider_modes.supported_modes("uprock") == {"proxy"}
    assert provider_modes.default_deploy_mode("uprock") == "proxy"


def test_sample_scripts_mode_matrix_is_locked():
    assert provider_modes.supported_modes("earnfm") == {"direct", "proxy"}
    assert provider_modes.supported_modes("iproyal") == {"proxy"}
    assert provider_modes.supported_modes("mysterium") == {"direct"}
    assert provider_modes.supported_modes("repocket") == {"direct", "proxy"}


def test_default_deploy_mode_matches_provider_capability():
    assert provider_modes.default_deploy_mode("earnfm") == "both"
    assert provider_modes.default_deploy_mode("mysterium") == "direct"
    assert provider_modes.default_deploy_mode("wipter") == "proxy"


def test_missing_mode_expands_to_provider_default_not_legacy():
    assert provider_modes.expand_requested("earnfm", None) == ["direct", "proxy"]


def test_runtime_matrix_labels_count_only_and_manual_only_providers():
    assert provider_runtime.get("proxybase-xyz").count_only is True
    assert provider_runtime.get("uprock").manual_only is True
