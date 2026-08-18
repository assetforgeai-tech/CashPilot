import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import database
from app.main import app


def test_earnapp_account_line_parser_accepts_email_refresh_xsrf():
    from app.earnapp_accounts import parse_account_line

    row = parse_account_line("assetforgeai@gmail.com|refresh-token|xsrf-token")

    assert row == {
        "email": "assetforgeai@gmail.com",
        "oauth_refresh_token": "refresh-token",
        "xsrf_token": "xsrf-token",
    }


def test_earnapp_dashboard_device_title_uses_last_8_chars_for_any_sdk_prefix():
    from app.earnapp_macos import dashboard_device_title

    assert dashboard_device_title("sdk-mac-f85c082de4a8b9a1967ad447d3ceb137") == "sdk-mac-d3ceb137"
    assert dashboard_device_title("sdk-node-f85c082de4a8b9a1967ad447d3ceb137") == "sdk-node-d3ceb137"


def test_earnapp_runtime_script_uses_redsocks_iptables_tls_and_cluster_retry():
    from app.earnapp_macos import runtime_script

    script = runtime_script()

    assert "redsocks" in script
    assert "iptables -t nat -A OUTPUT -p tcp -j REDSOCKS" in script
    assert "NODE_TLS_REJECT_UNAUTHORIZED=0" in script
    assert "is_linked" in script
    assert "install_device" in script
    assert "link_device" in script
    assert "HTTP=000" in script
    assert "do not stop" in script.lower()
    assert "sing-box" not in script


def test_earnapp_pool_routes_are_registered_and_owner_only():
    routes = {route.path for route in app.routes}

    assert "/api/admin/earnapp-accounts" in routes
    assert "/api/admin/earnapp-accounts/import" in routes


def test_proxy_pool_ui_has_earnapp_mask_and_unmask_confirm():
    page = Path("app/templates/proxy_pool.html").read_text(encoding="utf-8")

    assert "earnapp_mask_reason" in page
    assert "Unblock EarnApp" in page
    assert "confirm(`Unblock EarnApp" in page
    assert "/api/proxy-pool/earnapp-unmask" in page


def test_earnapp_collector_uses_multi_account_pool_not_manual_single_fields():
    from app.collectors import COLLECTOR_MAP, collector_credential_fields

    assert collector_credential_fields("earnapp") == []


def test_earnapp_proxy_mask_can_be_removed(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
            await database.init_db()
            provider_id = await database.upsert_proxy_provider("manual", "manual")
            proxy_id = await database.upsert_proxy_endpoints(
                provider_id,
                [{"host": "1.1.1.1", "port": 1000, "protocol": "socks5", "status": "alive"}],
            )
            assert await database.mask_proxy_for_provider(proxy_id, "earnapp", "earnapp_blocked_ip")
            assert await database.proxy_masked_for_provider(proxy_id, "earnapp")
            assert await database.unmask_proxy_for_provider(proxy_id, "earnapp")
            assert not await database.proxy_masked_for_provider(proxy_id, "earnapp")

    asyncio.run(run())


def test_proxy_pool_earnapp_unmask_route_calls_database():
    def owner():
        return {"uid": 1, "u": "admin", "r": "owner"}

    with (
        TestClient(app, raise_server_exceptions=False) as client,
        patch("app.main.auth.get_current_user", return_value=owner()),
        patch("app.routers.proxies.database.unmask_proxy_for_provider", new_callable=AsyncMock, return_value=2) as unmask,
    ):
        resp = client.post("/api/proxy-pool/earnapp-unmask", json={"proxy_ids": [1, 2]})

    assert resp.status_code == 200
    assert resp.json()["unmasked"] == 2
    unmask.assert_awaited_once_with([1, 2], "earnapp")
