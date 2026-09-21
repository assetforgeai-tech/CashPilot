from app.proxy_health import build_probe_groups, fanout_probe_result


def test_shared_proxy_uses_one_probe_and_fans_out_without_masking_nodes():
    leases = [
        {"instance_id": "earnapp-1", "proxy_id": 10, "exit_ip": "203.0.113.10", "lane": "proxy"},
        {"instance_id": "pawns-1", "proxy_id": 11, "exit_ip": "203.0.113.10", "lane": "proxy"},
        {"instance_id": "proxy-2", "proxy_id": 12, "exit_ip": "203.0.113.12", "lane": "proxy"},
        {"instance_id": "direct-1", "proxy_id": 0, "exit_ip": "", "lane": "direct"},
    ]
    groups = build_probe_groups(leases)
    assert len(groups) == 2
    shared = next(group for group in groups if "earnapp-1" in group["instance_ids"])
    assert shared["instance_ids"] == ["earnapp-1", "pawns-1"]
    result = fanout_probe_result(shared, {"status": "dead", "reason": "timeout"})
    assert [row["instance_id"] for row in result] == ["earnapp-1", "pawns-1"]
    assert all(row["status"] == "dead" for row in result)


def test_different_proxy_endpoints_do_not_share_health():
    leases = [
        {"instance_id": "a", "proxy_id": 10, "exit_ip": "", "host": "proxy-a", "port": 1080, "protocol": "socks5"},
        {"instance_id": "b", "proxy_id": 11, "exit_ip": "", "host": "proxy-b", "port": 1080, "protocol": "socks5"},
    ]
    groups = build_probe_groups(leases)
    assert len(groups) == 2
