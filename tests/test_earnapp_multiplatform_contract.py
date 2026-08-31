from __future__ import annotations

import pytest

from app import provider_runtime, worker_api


def test_earnapp_platform_policy_allows_dedicated_apple_and_ubuntu_lanes():
    assert provider_runtime.platform_deployment_allowed("earnapp", "macos", "docker") is True
    assert provider_runtime.platform_deployment_allowed("earnapp", "ios", "docker") is True
    assert provider_runtime.platform_deployment_allowed("earnapp", "ubuntu", "lxd") is True


@pytest.mark.parametrize(
    ("country_code", "ip_type", "expected"),
    [
        ("VN", "residential", {"macos", "ios"}),
        ("US", "residential", {"ubuntu"}),
        ("DE", "residential", {"ubuntu"}),
        ("VN", "datacenter", set()),
        ("", "residential", set()),
    ],
)
def test_earnapp_proxy_geo_selects_only_compatible_platforms(country_code, ip_type, expected):
    assert provider_runtime.earnapp_platforms_for_proxy(country_code, ip_type) == expected


def test_earnapp_generic_route_remains_closed_even_when_platform_is_allowed():
    assert (
        provider_runtime.deployment_block(
            "earnapp-macos-node",
            {"provider_slug": "earnapp", "platform": "macos", "runtime_backend": "docker"},
        )
        is not None
    )


def test_worker_has_a_dedicated_apple_deploy_route():
    assert hasattr(worker_api, "api_deploy_earnapp_docker_node")
