from app import provider_canary_matrix


def _evidence(**overrides):
    values = {
        "egress_ok": True,
        "dns_ok": True,
        "ipv6_ok": True,
        "direct_fallback_blocked": True,
        "watchdog_ok": True,
        "reboot_persistence_ok": True,
        "rollback_plan": "restore previous runtime digest",
    }
    values.update(overrides)
    return values


def test_proxy_provider_canary_requires_udp_evidence_and_reports_pass():
    result = provider_canary_matrix.evaluate_provider_canary("packetstream", evidence=_evidence(udp_ok=True))

    assert result.status == "PASS"
    assert result.group == "provider"
    assert result.missing == ()


def test_missing_evidence_is_inconclusive_not_pass():
    evidence = _evidence()
    evidence["udp_ok"] = True
    evidence.pop("watchdog_ok")
    result = provider_canary_matrix.evaluate_provider_canary("earnapp", evidence=evidence)

    assert result.status == "INCONCLUSIVE"
    assert result.missing == ("watchdog_ok",)


def test_failed_signal_is_fail_and_keeps_rollback_reference():
    result = provider_canary_matrix.evaluate_provider_canary(
        "proxies-sx", evidence=_evidence(dns_ok=False), rollback_plan="pin previous image"
    )

    assert result.status == "FAIL"
    assert result.findings == ("dns_ok",)
    assert result.rollback == "pin previous image"


def test_direct_only_provider_does_not_require_proxy_udp_or_watchdog():
    result = provider_canary_matrix.evaluate_provider_canary("mysterium", evidence=_evidence())

    assert result.status == "PASS"
    assert "udp_ok" not in result.required
    assert "watchdog_ok" not in result.required


def test_group_matrix_escalates_inconclusive_before_pass():
    matrix = provider_canary_matrix.evaluate_provider_groups(
        {
            "packetstream": _evidence(udp_ok=True),
            "proxies-sx": _evidence(),
        }
    )

    assert matrix["provider"].status == "INCONCLUSIVE"
    assert {item.provider for item in matrix["provider"].members} == {"packetstream", "proxies-sx"}
