from app import catalog, provider_modes, provider_runtime


def test_provider_modes_cover_16_runtime_providers_including_earnapp_and_nkn():
    providers = provider_modes.BOTH | provider_modes.PROXY_ONLY | provider_modes.DIRECT_ONLY
    active = {svc["slug"] for svc in catalog.get_services()}
    assert len(providers) == 16
    assert providers == active == set(provider_runtime.ACTIVE_SLUGS)
    assert "adnade" not in providers
    assert "dawn" not in providers
    assert "titan" not in providers
    assert providers == active
    assert provider_modes.supported_modes("nkn") == {"direct"}
    assert provider_modes.supported_modes("earnapp") == {"proxy"}


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


def test_earnapp_runtime_policy_allows_dedicated_multiplatform_lanes_without_changing_other_providers():
    earnapp = provider_runtime.get("earnapp")
    earnfm = provider_runtime.get("earnfm")

    assert earnapp is not None
    assert earnapp.deployment_allowed is True
    assert earnapp.deployment_policy == "platform_restricted"
    assert earnapp.allowed_platforms == ("macos", "ios", "ubuntu")
    assert earnapp.blocked_platforms == ()
    assert earnfm is not None and earnfm.deployment_allowed is True

    catalog_policy = provider_runtime.catalog_runtime("earnapp")
    assert catalog_policy["deployment_allowed"] is True
    assert catalog_policy["deployment_policy"] == "platform_restricted"
    assert catalog_policy["policy_message"] == earnapp.policy_message
