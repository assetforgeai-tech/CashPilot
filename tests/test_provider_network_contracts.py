from __future__ import annotations

import json
from pathlib import Path

from app import earnapp_runtime, orchestrator, provider_runtime
from app.provider_network_audit import audit_provider_network_inventory


def test_status_includes_live_sidecar_identity_for_managed_container(monkeypatch):
    class Image:
        tags = ["example/image:latest"]
        short_id = "sha256:x"

    class Container:
        def __init__(self, name, labels, cid):
            self.name = name
            self.labels = labels
            self.id = cid
            self.short_id = cid[:12]
            self.status = "running"
            self.image = Image()
            self.attrs = {"HostConfig": {"NetworkMode": "container:sidecar-id"}, "Created": ""}

        def stats(self, stream=False):
            return {"cpu_stats": {}, "precpu_stats": {}, "memory_stats": {}, "networks": {}}

        def exec_run(self, *args, **kwargs):
            return type("Result", (), {"exit_code": 0, "output": b""})()

    main = Container(
        "svc",
        {"cashpilot.managed": "true", "cashpilot.provider": "packetstream", "cashpilot.service": "svc"},
        "main-id",
    )
    sidecar = Container(
        "svc-egress",
        {
            "cashpilot.managed": "true",
            "cashpilot.provider": "packetstream",
            "cashpilot.service": "svc-egress",
            "cashpilot.role": "egress-sidecar",
        },
        "sidecar-id",
    )

    class Client:
        class Containers:
            def list(self, **kwargs):
                return [main, sidecar]

        containers = Containers()

    monkeypatch.setattr(orchestrator, "_get_client", lambda: Client())
    monkeypatch.setattr(orchestrator, "_collect_stats_bulk", lambda cs: {c.id: (0, 0, 0, 0) for c in cs})
    monkeypatch.setattr(
        orchestrator,
        "_provider_evidence",
        lambda slug, c: {"observed_egress_ip": "203.0.113.8", "probe_ok": True},
    )
    monkeypatch.setattr(orchestrator, "get_services", lambda: [])
    rows = orchestrator.get_status()
    assert rows[0]["sidecar_id"] == "sidecar-id"
    assert rows[0]["observed_egress_ip"] == "203.0.113.8"


def test_status_uses_legacy_sidecar_for_earnapp_evidence(monkeypatch):
    class Image:
        tags = ["example/image:latest"]
        short_id = "sha256:x"

    class Container:
        def __init__(self, name, labels, cid, network_mode):
            self.name = name
            self.labels = labels
            self.id = cid
            self.short_id = cid[:12]
            self.status = "running"
            self.image = Image()
            self.attrs = {"HostConfig": {"NetworkMode": network_mode}, "Created": ""}

        def stats(self, stream=False):
            return {"cpu_stats": {}, "precpu_stats": {}, "memory_stats": {}, "networks": {}}

    main = Container(
        "earnapp-1",
        {"cashpilot.managed": "true", "cashpilot.provider": "earnapp", "cashpilot.service": "earnapp-1"},
        "main-id",
        "container:sidecar-id",
    )
    sidecar = Container(
        "earnapp-1-egress",
        {
            "cashpilot.managed": "true",
            "cashpilot.provider": "earnapp",
            "cashpilot.service": "earnapp-1-egress",
            "cashpilot.role": "egress-sidecar",
        },
        "sidecar-id",
        "bridge",
    )

    class Client:
        class Containers:
            def list(self, **kwargs):
                return [main, sidecar]

            def get(self, cid):
                assert cid == "sidecar-id"
                return sidecar

        containers = Containers()

    seen = {}

    def evidence(slug, container, *, probe_container=None):
        seen["probe"] = probe_container
        return {}

    monkeypatch.setattr(orchestrator, "_get_client", lambda: Client())
    monkeypatch.setattr(orchestrator, "_collect_stats_bulk", lambda cs: {c.id: (0, 0, 0, 0) for c in cs})
    monkeypatch.setattr(orchestrator, "_provider_evidence", evidence)
    monkeypatch.setattr(orchestrator, "get_services", lambda: [])

    orchestrator.get_status()

    assert seen["probe"] is sidecar


def test_proxy_provider_evidence_probes_container_namespace():
    class Container:
        def exec_run(self, *_args, **_kwargs):
            return type("Result", (), {"exit_code": 0, "output": b"203.0.113.9\n"})()

    assert orchestrator._provider_evidence("packetstream", Container()) == {
        "running": True,
        "observed_egress_ip": "203.0.113.9",
        "probe_ok": True,
    }


def test_proxy_provider_evidence_uses_sidecar_when_main_has_no_probe_tool():
    class Main:
        def exec_run(self, *_args, **_kwargs):
            raise AssertionError("the provider image is not required to ship curl or wget")

    class Sidecar:
        def exec_run(self, *_args, **_kwargs):
            return type("Result", (), {"exit_code": 0, "output": b"203.0.113.10\n"})()

    assert orchestrator._provider_evidence("packetstream", Main(), probe_container=Sidecar()) == {
        "running": True,
        "observed_egress_ip": "203.0.113.10",
        "probe_ok": True,
    }


def test_proxy_provider_evidence_proves_sidecar_leak_controls():
    config = {
        "dns": {
            "servers": [
                {"tag": "cf", "type": "https", "detour": "proxy-out"},
                {"tag": "bootstrap", "type": "udp", "server": "1.1.1.1"},
            ],
            "rules": [{"domain": ["proxy.example"], "server": "bootstrap"}],
            "strategy": "ipv4_only",
        },
        "inbounds": [{"type": "tun", "strict_route": True, "address": ["172.31.255.1/30"]}],
        "outbounds": [
            {"type": "http", "tag": "proxy-out", "server": "proxy.example"},
            {"type": "direct", "tag": "direct"},
        ],
        "route": {
            "rules": [
                {"port": 53, "action": "hijack-dns"},
                {"domain": ["proxy.example"], "outbound": "direct"},
            ],
            "final": "proxy-out",
        },
    }

    class Sidecar:
        calls = 0

        def exec_run(self, *_args, **_kwargs):
            self.calls += 1
            output = b"203.0.113.10\n" if self.calls == 1 else json.dumps(config).encode()
            return type("Result", (), {"exit_code": 0, "output": output})()

    assert orchestrator._provider_evidence("packetstream", Sidecar()) == {
        "running": True,
        "observed_egress_ip": "203.0.113.10",
        "probe_ok": True,
        "dns_via_proxy": True,
        "ipv6_blocked": True,
        "udp_blocked": True,
        "doh_blocked": True,
        "dot_blocked": True,
        "direct_fallback_blocked": True,
    }


def test_direct_provider_evidence_proves_dedicated_native_network_controls():
    class Container:
        labels = {"cashpilot.instance_mode": "direct"}
        attrs = {
            "HostConfig": {"NetworkMode": "cashpilot-direct-ipv4-001"},
            "NetworkSettings": {
                "Networks": {
                    "cashpilot-direct-ipv4-001": {
                        "GlobalIPv6Address": "",
                        "IPv6Gateway": "",
                    }
                }
            },
        }
        calls = 0

        def exec_run(self, *_args, **_kwargs):
            self.calls += 1
            output = b"203.0.113.12\n" if self.calls == 1 else b"nameserver 127.0.0.11\n\n"
            return type("Result", (), {"exit_code": 0, "output": output})()

    assert orchestrator._provider_evidence("earnfm", Container()) == {
        "running": True,
        "observed_egress_ip": "203.0.113.12",
        "probe_ok": True,
        "dns_via_proxy": False,
        "ipv6_blocked": True,
        "direct_fallback_blocked": True,
    }


def test_earnapp_provider_evidence_includes_observed_egress():
    class Container:
        calls = 0

        def exec_run(self, *_args, **_kwargs):
            self.calls += 1
            output = b'{"device_id":"sdk-node-abc","running":true}\n' if self.calls == 1 else b"203.0.113.13\n"
            return type("Result", (), {"exit_code": 0, "output": output})()

    assert orchestrator._provider_evidence("earnapp", Container()) == {
        "device_id": "sdk-node-abc",
        "running": True,
        "observed_egress_ip": "203.0.113.13",
        "probe_ok": True,
    }


def test_earnapp_evidence_keeps_sidecar_controls_when_identity_probe_is_missing():
    config = {
        "dns": {
            "servers": [
                {"tag": "cf", "type": "https", "detour": "proxy-out"},
                {"tag": "bootstrap", "type": "udp", "server": "1.1.1.1"},
            ],
            "rules": [{"domain": ["proxy.example"], "server": "bootstrap"}],
            "strategy": "ipv4_only",
        },
        "inbounds": [{"type": "tun", "strict_route": True}],
        "outbounds": [{"tag": "proxy-out"}],
        "route": {
            "rules": [{"port": 53, "action": "hijack-dns"}],
            "final": "proxy-out",
        },
    }

    class Main:
        def exec_run(self, *_args, **_kwargs):
            return type("Result", (), {"exit_code": 1, "output": b""})()

    class Sidecar:
        calls = 0

        def exec_run(self, *_args, **_kwargs):
            self.calls += 1
            output = b"203.0.113.14\n" if self.calls == 1 else json.dumps(config).encode()
            return type("Result", (), {"exit_code": 0, "output": output})()

    evidence = orchestrator._provider_evidence("earnapp", Main(), probe_container=Sidecar())
    assert evidence["probe_ok"] is True
    assert evidence["observed_egress_ip"] == "203.0.113.14"
    assert evidence["dns_via_proxy"] is True
    assert evidence["direct_fallback_blocked"] is True


def test_probe_service_egress_uses_container_namespace_sidecar(monkeypatch):
    class Main:
        status = "running"
        attrs = {"HostConfig": {"NetworkMode": "container:sidecar-id"}}

        def exec_run(self, *_args, **_kwargs):
            raise AssertionError("main provider image has no probe tool")

    class Sidecar:
        status = "running"

        def exec_run(self, *_args, **_kwargs):
            return type("Result", (), {"exit_code": 0, "output": b"203.0.113.11\n"})()

    class Containers:
        def get(self, container_id):
            assert container_id == "sidecar-id"
            return Sidecar()

    class Client:
        containers = Containers()

    monkeypatch.setattr(orchestrator, "_get_client", lambda: Client())
    monkeypatch.setattr(orchestrator, "_find_container", lambda _slug: Main())
    assert orchestrator.probe_service_egress("packetstream") == {
        "running": True,
        "observed_egress_ip": "203.0.113.11",
        "probe_ok": True,
    }


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


def test_hybrid_proxy_lane_without_managed_sidecar_is_attention():
    report = audit_provider_network_inventory(
        "earnfm",
        instances=[{"instance_id": "earnfm-proxy-w1-ipv4-001", "mode": "proxy", "status": "running"}],
        containers=[
            {
                "instance_slug": "earnfm-proxy-w1-ipv4-001",
                "slug": "earnfm",
                "status": "running",
                "network_mode": "bridge",
            }
        ],
        inventory_confirmed=True,
    )
    assert report["status"] == "attention"
    assert report["missing_sidecar"] == ["earnfm-proxy-w1-ipv4-001"]


def test_hybrid_direct_lane_does_not_require_proxy_sidecar():
    report = audit_provider_network_inventory(
        "earnfm",
        instances=[{"instance_id": "earnfm-direct-w1-ipv4-001", "mode": "direct", "status": "running"}],
        containers=[
            {
                "instance_slug": "earnfm-direct-w1-ipv4-001",
                "slug": "earnfm",
                "status": "running",
                "network_mode": "cashpilot-direct-ipv4-001",
                "dns_via_proxy": False,
                "ipv6_blocked": True,
                "direct_fallback_blocked": True,
            }
        ],
        inventory_confirmed=True,
    )
    assert report["status"] == "pass"


def test_active_direct_lane_requires_dns_ipv6_and_route_fallback_evidence():
    report = audit_provider_network_inventory(
        "earnfm",
        instances=[
            {
                "instance_id": "earnfm-direct-w1-ipv4-001",
                "mode": "direct",
                "status": "running",
                "public_ip": "198.51.100.1",
            }
        ],
        containers=[
            {
                "instance_slug": "earnfm-direct-w1-ipv4-001",
                "status": "running",
                "network_mode": "cashpilot-direct-ipv4-001",
                "actual_egress_ip": "198.51.100.1",
            }
        ],
        inventory_confirmed=True,
    )
    assert report["status"] == "attention"
    assert report["network_evidence"]["findings"] == [
        "earnfm-direct-w1-ipv4-001: dns_isolation_unverified",
        "earnfm-direct-w1-ipv4-001: ipv6_isolation_unverified",
        "earnfm-direct-w1-ipv4-001: direct_fallback_unverified",
    ]


def test_direct_lane_flags_verified_egress_mismatch():
    report = audit_provider_network_inventory(
        "earnfm",
        instances=[
            {
                "instance_id": "earnfm-direct-w1-ipv4-001",
                "mode": "direct",
                "status": "running",
                "public_ip": "198.51.100.1",
            }
        ],
        containers=[
            {
                "instance_slug": "earnfm-direct-w1-ipv4-001",
                "slug": "earnfm",
                "network_mode": "cashpilot-direct-ipv4-001",
                "actual_egress_ip": "198.51.100.2",
            }
        ],
        inventory_confirmed=True,
    )
    assert report["status"] == "attention"
    assert "egress mismatch" in report["findings"][0]


def test_proxy_lane_flags_verified_egress_mismatch_even_with_sidecar():
    report = audit_provider_network_inventory(
        "earnfm",
        instances=[
            {
                "instance_id": "earnfm-proxy-w1-ipv4-001",
                "mode": "proxy",
                "status": "running",
                "spec": {"proxy": {"exit_ip": "203.0.113.1"}},
            }
        ],
        containers=[
            {
                "instance_slug": "earnfm-proxy-w1-ipv4-001",
                "slug": "earnfm",
                "network_mode": "container:sidecar-id",
                "sidecar_id": "sidecar-id",
                "observed_egress_ip": "203.0.113.2",
            }
        ],
        inventory_confirmed=True,
    )
    assert report["status"] == "attention"
    assert "proxy egress mismatch" in report["findings"][0]


def test_active_proxy_lane_reports_missing_leak_control_evidence():
    report = audit_provider_network_inventory(
        "earnfm",
        instances=[
            {
                "instance_id": "earnfm-proxy-w1-proxy-001",
                "mode": "proxy",
                "status": "running",
                "proxy_lease_id": "9",
                "expected_egress_ip": "203.0.113.1",
            }
        ],
        containers=[
            {
                "instance_slug": "earnfm-proxy-w1-proxy-001",
                "network_mode": "container:sidecar-id",
                "sidecar_id": "sidecar-id",
                "observed_egress_ip": "203.0.113.1",
            }
        ],
        inventory_confirmed=True,
    )
    assert report["network_evidence"] == {
        "status": "attention",
        "findings": [
            "earnfm-proxy-w1-proxy-001: dns_isolation_unverified",
            "earnfm-proxy-w1-proxy-001: ipv6_isolation_unverified",
            "earnfm-proxy-w1-proxy-001: udp_isolation_unverified",
            "earnfm-proxy-w1-proxy-001: doh_isolation_unverified",
            "earnfm-proxy-w1-proxy-001: dot_isolation_unverified",
            "earnfm-proxy-w1-proxy-001: direct_fallback_unverified",
        ],
    }
    assert report["status"] == "attention"


def test_proxy_lane_requires_doh_dot_and_direct_fallback_evidence():
    report = audit_provider_network_inventory(
        "earnfm",
        instances=[
            {
                "instance_id": "earnfm-proxy-w1-proxy-001",
                "mode": "proxy",
                "status": "running",
                "proxy_lease_id": "9",
                "expected_egress_ip": "203.0.113.1",
            }
        ],
        containers=[
            {
                "instance_slug": "earnfm-proxy-w1-proxy-001",
                "network_mode": "container:sidecar-id",
                "sidecar_id": "sidecar-id",
                "observed_egress_ip": "203.0.113.1",
                "dns_via_proxy": True,
                "ipv6_blocked": True,
                "udp_blocked": True,
                "doh_blocked": False,
                "dot_blocked": None,
                "direct_fallback_blocked": None,
            }
        ],
        inventory_confirmed=True,
    )
    assert report["network_evidence"]["findings"] == [
        "earnfm-proxy-w1-proxy-001: doh_bypass_detected",
        "earnfm-proxy-w1-proxy-001: dot_isolation_unverified",
        "earnfm-proxy-w1-proxy-001: direct_fallback_unverified",
    ]


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


def test_earnapp_iptables_parser_proves_fail_closed_controls():
    from app.orchestrator import _parse_earnapp_iptables

    output = """-N CP_EARNAPP_OUT
-A CP_EARNAPP_OUT -j DROP
-N CP_EARNAPP_DNS
-A CP_EARNAPP_DNS -p udp --dport 53 -j REDIRECT --to-ports 1053
-A CP_EARNAPP_DNS -p tcp --dport 53 -j REDIRECT --to-ports 1053
-N CP_EARNAPP6_OUT
-A CP_EARNAPP6_OUT -j DROP
"""
    assert _parse_earnapp_iptables(output) == {
        "dns_via_proxy": True,
        "ipv6_blocked": True,
        "udp_blocked": True,
        "doh_blocked": True,
        "dot_blocked": True,
        "direct_fallback_blocked": True,
    }


def test_live_container_network_evidence_overrides_stale_instance_fields():
    report = audit_provider_network_inventory(
        "earnapp",
        instances=[
            {
                "instance_id": "node-1",
                "mode": "proxy",
                "status": "active",
                "dns_via_proxy": False,
                "ipv6_blocked": False,
                "udp_blocked": False,
                "doh_blocked": False,
                "dot_blocked": False,
                "direct_fallback_blocked": False,
            }
        ],
        containers=[
            {
                "instance_slug": "node-1",
                "status": "running",
                "network_mode": "container:sidecar",
                "dns_via_proxy": True,
                "ipv6_blocked": True,
                "udp_blocked": True,
                "doh_blocked": True,
                "dot_blocked": True,
                "direct_fallback_blocked": True,
            }
        ],
        inventory_confirmed=True,
    )
    assert report["network_evidence"] == {"status": "pass", "findings": []}


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
