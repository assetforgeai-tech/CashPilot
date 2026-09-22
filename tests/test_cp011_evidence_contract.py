import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_cp011_schema_locks_scope_and_required_gates():
    schema = json.loads((ROOT / "docs/ops/cp011-canary-evidence.schema.json").read_text())

    assert schema["properties"]["schema_version"]["const"] == 1
    scope = schema["properties"]["scope"]["properties"]
    assert scope["resource_group"]["const"] == "rg-cashpilot-live-test-20260911"
    assert scope["vm_names"]["const"] == ["cashpilot-live-ea", "cashpilot-live-je"]
    assert set(schema["properties"]["gates"]["required"]) == {
        "dry_run",
        "egress",
        "dns_doh",
        "ipv6",
        "udp",
        "direct_fallback",
        "watchdog",
        "reboot",
        "reconciliation",
        "cleanup",
    }


def test_cp011_runbook_forbids_non_disposable_scopes():
    runbook = (ROOT / "docs/ops/cp011-canary-runbook.md").read_text()

    assert "test-sing" in runbook
    assert "test-us" in runbook
    assert "production" in runbook.lower()
    assert "rollout" in runbook.lower()


def test_cp011_result_is_secret_free_and_stops_on_failed_gates():
    result = json.loads((ROOT / "docs/evidence/CP-011-canary-result.json").read_text())

    assert result["gates"]["watchdog"] == "FAIL"
    assert result["gates"]["reboot"] == "FAIL"
    assert result["authorization"]["production_rollout"] is False
    serialized = json.dumps(result).lower()
    for forbidden in ("password", "cookie", "private_key", "api_key"):
        assert forbidden not in serialized
