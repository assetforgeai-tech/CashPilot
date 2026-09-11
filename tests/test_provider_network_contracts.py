from __future__ import annotations

from pathlib import Path

from app import earnapp_runtime, provider_runtime
from app.provider_network_audit import audit_provider_network_inventory


def test_network_audit_reports_unverified_when_provider_has_no_live_inventory():
    report = audit_provider_network_inventory("packetstream", instances=[], containers=[], inventory_confirmed=False)
    assert report["status"] == "unverified"


def test_active_provider_matrix_is_explicit_and_earnapp_is_docker_only():
    assert provider_runtime.ACTIVE_SLUGS
    assert provider_runtime.platform_deployment_allowed("earnapp", "macos", "docker")
    assert provider_runtime.platform_deployment_allowed("earnapp", "ios", "docker")
    assert provider_runtime.platform_deployment_allowed("earnapp", "ubuntu", "docker")
    assert not provider_runtime.platform_deployment_allowed("earnapp", "ubuntu", "lxd")
    assert not provider_runtime.platform_deployment_allowed("earnapp", "", "docker")


def test_earnapp_runtime_contract_contains_fail_closed_tcp_and_dns_rules():
    source = earnapp_runtime.__file__
    text = Path(source).read_text(encoding="utf-8")
    assert "CP_EARNAPP_OUT" in text
    assert "iptables -A CP_EARNAPP_OUT -j DROP" in text
    assert "CP_EARNAPP_DNS" in text
    assert "cloudflare-dns.com" in text


def test_proxy_only_runtime_without_managed_sidecar_is_attention():
    report = audit_provider_network_inventory(
        "wipter",
        instances=[{"instance_id": "w-1", "status": "active"}],
        containers=[{"instance_slug": "w-1", "slug": "wipter", "status": "running", "network_mode": "bridge"}],
        inventory_confirmed=True,
    )
    assert report["status"] == "attention"
    assert report["missing_sidecar"] == ["w-1"]
    assert "direct egress risk" in report["findings"][0]


def test_earnapp_main_container_network_contract_does_not_require_sidecar():
    report = audit_provider_network_inventory(
        "earnapp",
        instances=[{"instance_id": "e-1", "status": "verification_pending"}],
        containers=[
            {
                "instance_slug": "e-1",
                "slug": "earnapp",
                "status": "running",
                "network_mode": "bridge",
            }
        ],
        inventory_confirmed=True,
    )
    assert report["status"] == "pass"
    assert report["missing_sidecar"] == []


def test_unconfirmed_inventory_does_not_claim_proxy_runtime_safe():
    report = audit_provider_network_inventory(
        "wipter", instances=[{"instance_id": "w-1", "status": "active"}], containers=[], inventory_confirmed=False
    )
    assert report["status"] == "unverified"
    assert report["missing_sidecar"] == []


def test_audit_ignores_retired_instances_and_accepts_container_namespace_sidecar():
    report = audit_provider_network_inventory(
        "wipter",
        instances=[
            {"instance_id": "retired", "status": "RETIRED"},
            {"instance_id": "w-2", "status": "ACTIVE"},
        ],
        containers=[
            {
                "instance_slug": "w-2",
                "slug": "wipter",
                "status": "running",
                "network_mode": "container:sidecar",
                "cap_add": ["NET_ADMIN", "NET_RAW", "DAC_OVERRIDE"],
            }
        ],
        inventory_confirmed=True,
    )
    assert report["status"] == "pass"


def test_audit_flags_live_proxy_container_without_database_instance():
    report = audit_provider_network_inventory(
        "wipter",
        instances=[],
        containers=[{"instance_slug": "wipter-proxy", "slug": "wipter", "network_mode": "bridge"}],
        inventory_confirmed=True,
    )
    assert report["status"] == "attention"
    assert report["untracked"] == ["wipter-proxy"]
    assert "direct egress risk" in report["findings"][0]


def test_wipter_audit_reports_missing_catalog_capabilities():
    report = audit_provider_network_inventory(
        "wipter",
        instances=[{"instance_id": "w-1", "status": "active"}],
        containers=[
            {
                "instance_slug": "w-1",
                "slug": "wipter",
                "status": "running",
                "network_mode": "container:w-1-egress",
                "cap_add": [],
            }
        ],
        inventory_confirmed=True,
    )
    assert report["status"] == "attention"
    assert "DAC_OVERRIDE" in report["findings"][0]


def test_wipter_legacy_runtime_name_matches_managed_instance_alias():
    report = audit_provider_network_inventory(
        "wipter",
        instances=[{"instance_id": "wipter-proxy", "status": "running"}],
        containers=[
            {
                "instance_slug": "wipter",
                "network_mode": "container:sidecar-id",
                "sidecar_id": "sidecar-id",
                "cap_add": ["NET_ADMIN", "NET_RAW", "DAC_OVERRIDE"],
            }
        ],
        inventory_confirmed=True,
    )
    assert report["status"] == "pass"
    assert report["missing_sidecar"] == []
    assert report["untracked"] == []
