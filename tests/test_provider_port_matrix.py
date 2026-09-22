from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
MATRIX = ROOT / "docs" / "ops" / "provider-port-matrix.yaml"


def load_matrix():
    return yaml.safe_load(MATRIX.read_text(encoding="utf-8"))


def test_matrix_covers_all_sixteen_active_provider_slugs():
    data = load_matrix()
    assert data["provider_count"] == 16
    assert len(data["providers"]) == 16


def test_count_contract_does_not_silently_reduce_proxy_lanes():
    contract = load_matrix()["count_contract"]
    assert contract["insufficient_proxy_capacity"] == "block_lane"
    assert contract["silent_count_reduction"] == "forbidden"


def test_mysterium_and_nkn_ports_are_explicit():
    providers = load_matrix()["providers"]
    assert providers["mysterium"]["inbound_udp"] == ["56000-56100"]
    assert providers["nkn"]["inbound_tcp"] == ["30000-30005"]
    assert providers["nkn"]["inbound_udp"] == ["30000-30005"]
    assert providers["nkn"]["web_view"].endswith(":30000/web")


def test_manual_ui_access_is_tunnel_only_and_worker_endpoints_private():
    data = load_matrix()
    assert data["providers"]["wipter"]["operator_access"] == "tunnel_only"
    assert data["providers"]["uprock"]["operator_access"] == "tunnel_only"
    assert data["security"]["public_worker_api_ports"] == []
    assert data["security"]["public_cashpilot_ui_ports"] == []
    assert data["security"]["no_public_vnc"] is True
    assert data["security"]["no_public_novnc"] is True


def test_proxybase_xyz_is_count_only_phrase_input():
    provider = load_matrix()["providers"]["proxybase-xyz"]
    assert provider["input"] == "phrase"
    assert provider["collector"] == "count_only"
