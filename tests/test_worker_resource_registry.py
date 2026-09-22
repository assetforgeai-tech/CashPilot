import pytest

from app.worker_resource_registry import (
    REQUIRED_RESOURCE_FAMILIES,
    ResourceDisposition,
    get_worker_resource_registry,
    validate_registry,
)


def test_registry_lists_every_worker_bound_authority():
    registry = get_worker_resource_registry()
    assert set(registry) == set(REQUIRED_RESOURCE_FAMILIES)
    for family in REQUIRED_RESOURCE_FAMILIES:
        assert registry[family].table
        assert registry[family].release_action
        assert registry[family].release_reason == "worker_lost"
        assert registry[family].post_release_state


def test_registry_marks_ownership_that_survives_worker_loss():
    registry = get_worker_resource_registry()
    assert registry["proxy_leases"].preserve == (
        "proxy_identity",
        "sticky_egress_ownership",
        "proxy_health",
    )
    assert registry["nkn_wallets"].preserve == ("wallet_identity", "credential", "history")
    assert registry["myst_wallets"].preserve == ("wallet_identity", "credential", "history")


def test_direct_only_has_no_proxy_lease():
    registry = get_worker_resource_registry()
    assert registry["direct_only"].disposition is ResourceDisposition.RETIRE
    assert registry["direct_only"].table == "provider_instances"
    assert registry["direct_only"].release_action == "retire_runtime_assignment"


def test_registry_rejects_missing_required_family():
    registry = get_worker_resource_registry()
    registry.pop("capacity_reservations")
    with pytest.raises(ValueError, match="capacity_reservations"):
        validate_registry(registry)
