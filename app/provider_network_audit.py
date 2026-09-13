"""Read-only checks for provider runtime network drift."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app import provider_runtime


def validate_provider_network_evidence(
    *,
    mode: str,
    dns_via_proxy: bool | None,
    ipv6_blocked: bool | None,
    udp_blocked: bool | None,
    doh_blocked: bool | None = None,
    dot_blocked: bool | None = None,
    direct_fallback_blocked: bool | None = None,
) -> dict[str, Any]:
    """Validate leak controls without treating missing evidence as safe."""
    findings: list[str] = []
    selected = str(mode or "").strip().lower()
    if selected == "direct" and dns_via_proxy is True:
        findings.append("direct_dns_not_native")
    elif dns_via_proxy is None:
        findings.append("dns_isolation_unverified")
    elif dns_via_proxy is False:
        findings.append("dns_leak_detected")
    if ipv6_blocked is None:
        findings.append("ipv6_isolation_unverified")
    elif ipv6_blocked is False:
        findings.append("ipv6_not_blocked")
    if selected == "direct" and direct_fallback_blocked is None:
        findings.append("direct_fallback_unverified")
    elif selected == "direct" and direct_fallback_blocked is False:
        findings.append("direct_fallback_detected")
    if selected == "proxy":
        if udp_blocked is None:
            findings.append("udp_isolation_unverified")
        elif udp_blocked is False:
            findings.append("udp_not_blocked")
        if doh_blocked is None:
            findings.append("doh_isolation_unverified")
        elif doh_blocked is False:
            findings.append("doh_bypass_detected")
        if dot_blocked is None:
            findings.append("dot_isolation_unverified")
        elif dot_blocked is False:
            findings.append("dot_bypass_detected")
        if direct_fallback_blocked is None:
            findings.append("direct_fallback_unverified")
        elif direct_fallback_blocked is False:
            findings.append("direct_fallback_detected")
    return {"status": "attention" if findings else "pass", "findings": findings}


def validate_provider_egress(
    provider: str,
    *,
    mode: str,
    expected_egress_ip: str,
    observed_egress_ip: str,
    proxy_lease_id: str = "",
    fallback_mode: str = "",
) -> dict[str, Any]:
    """Validate one lane's egress evidence without permitting fallback."""
    selected = str(mode or "").strip().lower()
    findings: list[str] = []
    expected = str(expected_egress_ip or "").strip()
    observed = str(observed_egress_ip or "").strip()
    if selected == "direct":
        if not expected:
            findings.append("missing expected direct egress")
        if not observed:
            findings.append("missing observed direct egress")
        elif expected and observed != expected:
            findings.append("direct egress mismatch")
    elif selected == "proxy":
        if not expected:
            findings.append("missing expected proxy egress")
        if expected and observed and observed != expected:
            findings.append("proxy egress mismatch")
        if not proxy_lease_id:
            findings.append("missing proxy lease")
        if not observed:
            findings.append("missing observed proxy egress")
    else:
        findings.append(f"unsupported egress mode: {selected or 'empty'}")
    fallback = str(fallback_mode or "").strip().lower()
    if fallback:
        findings.append(f"unsafe egress fallback: {fallback}")
    return {"status": "attention" if findings else "pass", "findings": findings}


def audit_provider_network_inventory(
    provider: str,
    *,
    instances: Iterable[Mapping[str, Any]],
    containers: Iterable[Mapping[str, Any]],
    inventory_confirmed: bool,
) -> dict[str, Any]:
    """Report proxy-only runtimes that bypass the managed egress sidecar.

    This is intentionally inspection-only. Missing or unconfirmed Docker
    inventory is ``unverified`` rather than evidence of a safe deployment.
    """
    slug = str(provider or "").strip().lower()
    instances = list(instances)
    containers = list(containers)
    runtime = provider_runtime.get(slug)
    if runtime is None or not inventory_confirmed:
        return {"provider": slug, "status": "unverified", "missing_sidecar": [], "untracked": [], "findings": []}
    by_id = {
        str(item.get("instance_id") or item.get("instance_slug") or item.get("name") or "").strip(): item
        for item in containers
        if isinstance(item, Mapping)
    }
    findings: list[str] = []
    network_findings: list[str] = []
    for instance in instances:
        if str(instance.get("mode") or "").strip().lower() != "direct":
            continue
        instance_id = str(instance.get("instance_id") or "").strip()
        container = by_id.get(instance_id)
        expected = str(instance.get("public_ip") or "").strip()
        actual = str((container or {}).get("actual_egress_ip") or "").strip()
        if expected:
            evidence = validate_provider_egress(
                slug,
                mode="direct",
                expected_egress_ip=expected,
                observed_egress_ip=actual,
            )
            findings.extend(f"{instance_id}: {item}" for item in evidence["findings"])
    proxy_instances = [
        item
        for item in instances
        if str(item.get("mode") or "").strip().lower() == "proxy"
        or (not item.get("mode") and runtime.modes == ("proxy",))
    ]
    if not proxy_instances:
        if runtime.modes == ("proxy",) and containers:
            proxy_instances = [
                {"instance_id": str(item.get("instance_slug") or item.get("name") or ""), "status": "running"}
                for item in containers
            ]
        elif runtime.modes != ("proxy",):
            return {
                "provider": slug,
                "status": "attention" if findings else "pass",
                "missing_sidecar": [],
                "untracked": [],
                "findings": findings,
            }
    if not proxy_instances:
        return {"provider": slug, "status": "not_applicable", "missing_sidecar": [], "untracked": [], "findings": []}

    if slug == "wipter" and "wipter" in by_id and "wipter-proxy" not in by_id:
        by_id["wipter-proxy"] = by_id["wipter"]
    missing: list[str] = []
    tracked = {str(item.get("instance_id") or "").strip() for item in instances}
    if slug == "wipter" and "wipter-proxy" in tracked:
        tracked.add("wipter")
    untracked = sorted(
        str(item.get("instance_slug") or item.get("name") or "").strip()
        for item in containers
        if str(item.get("instance_slug") or item.get("name") or "").strip() not in tracked
    )
    for instance in proxy_instances:
        instance_id = str(instance.get("instance_id") or instance.get("logical_node_id") or "").strip()
        if not instance_id or str(instance.get("status") or "").lower() in {"retired", "stopped"}:
            continue
        container = by_id.get(instance_id)
        if not container:
            missing.append(instance_id)
            findings.append(f"{instance_id}: runtime inventory missing; direct egress risk")
            continue
        spec = instance.get("spec") if isinstance(instance.get("spec"), Mapping) else {}
        proxy = spec.get("proxy") if isinstance(spec.get("proxy"), Mapping) else {}
        expected_egress = str(
            instance.get("expected_egress_ip") or proxy.get("exit_ip") or instance.get("exit_ip") or ""
        ).strip()
        observed_egress = str(container.get("observed_egress_ip") or container.get("actual_egress_ip") or "").strip()
        lease_id = str(
            instance.get("proxy_lease_id") or instance.get("lease_id") or proxy.get("proxy_id") or proxy.get("id") or ""
        ).strip()
        # Managed slot lanes must always prove both the lease and observed
        # egress. Manual runtimes retain their legacy capability-only audit.
        active = str(instance.get("status") or "").strip().lower() in {"active", "running", "deployed"}
        if (
            (active and runtime.topology in {"slot_proxy", "slot_both"})
            or expected_egress
            or observed_egress
            or lease_id
        ):
            evidence = validate_provider_egress(
                slug,
                mode="proxy",
                expected_egress_ip=expected_egress,
                observed_egress_ip=observed_egress,
                proxy_lease_id=lease_id,
            )
            findings.extend(f"{instance_id}: {item}" for item in evidence["findings"])
        if active and runtime.topology in {"slot_proxy", "slot_both"}:
            network = validate_provider_network_evidence(
                mode="proxy",
                dns_via_proxy=instance.get("dns_via_proxy")
                if "dns_via_proxy" in instance
                else container.get("dns_via_proxy"),
                ipv6_blocked=instance.get("ipv6_blocked")
                if "ipv6_blocked" in instance
                else container.get("ipv6_blocked"),
                udp_blocked=instance.get("udp_blocked") if "udp_blocked" in instance else container.get("udp_blocked"),
                doh_blocked=instance.get("doh_blocked") if "doh_blocked" in instance else container.get("doh_blocked"),
                dot_blocked=instance.get("dot_blocked") if "dot_blocked" in instance else container.get("dot_blocked"),
                direct_fallback_blocked=instance.get("direct_fallback_blocked")
                if "direct_fallback_blocked" in instance
                else container.get("direct_fallback_blocked"),
            )
            network_findings.extend(f"{instance_id}: {item}" for item in network["findings"])
        mode = str(container.get("network_mode") or container.get("NetworkMode") or "").lower()
        # EarnApp installs redsocks, DNS forwarding, and fail-closed iptables
        # inside its main container. It intentionally has no sidecar.
        in_container = (
            slug == "earnapp"
            or str(container.get("network_contract") or instance.get("network_contract") or "").strip().lower()
            == "in_container"
        )
        sidecar = bool(container.get("sidecar_id") or container.get("sidecar_container_id"))
        if not in_container and not sidecar and not mode.startswith("container:"):
            missing.append(instance_id)
            findings.append(f"{instance_id}: managed sidecar missing; direct egress risk")
            continue
        if slug == "wipter":
            required = {"NET_ADMIN", "NET_RAW", "DAC_OVERRIDE"}
            actual = {str(cap).upper() for cap in (container.get("cap_add") or [])}
            absent = sorted(required - actual)
            if absent:
                missing.append(instance_id)
                findings.append(f"{instance_id}: required capabilities missing: {', '.join(absent)}")
    for instance_id in untracked:
        live = by_id.get(instance_id)
        if live is None and len(containers) == 1:
            live = containers[0]
        mode = str((live or {}).get("network_mode") or (live or {}).get("NetworkMode") or "").lower()
        suffix = "; direct egress risk" if mode and not mode.startswith("container:") else ""
        findings.append(f"{instance_id}: live runtime is not tracked in CashPilot{suffix}")
    return {
        "provider": slug,
        "status": "attention" if missing or untracked or findings or network_findings else "pass",
        "missing_sidecar": missing,
        "untracked": untracked,
        "findings": findings + network_findings,
        "network_evidence": {
            "status": "attention" if network_findings else "pass",
            "findings": network_findings,
        },
    }
