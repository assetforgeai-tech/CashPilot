from app import provider_modes


def test_provider_modes_cover_18_runtime_providers():
    providers = provider_modes.BOTH | provider_modes.PROXY_ONLY | provider_modes.DIRECT_ONLY
    assert len(providers) == 18
    assert "adnade" not in providers
    assert "dawn" not in providers
    assert "titan" not in providers


def test_expand_both_only_for_dual_mode_provider():
    assert provider_modes.expand_requested("bitping", "both") == ["direct", "proxy"]


def test_earnapp_is_proxy_only():
    assert provider_modes.supported_modes("earnapp") == {"proxy"}
