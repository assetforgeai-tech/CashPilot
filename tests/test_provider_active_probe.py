import asyncio
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


def test_active_probe_is_bounded_and_read_only():
    from app import main

    with (
        patch.object(main, "_require_owner"),
        patch.object(
            main.database,
            "list_workers",
            AsyncMock(
                return_value=[
                    {
                        "id": 118903,
                        "status": "online",
                        "containers": '[{"slug":"spide","instance_slug":"spide-node-1"}]',
                    }
                ]
            ),
        ),
        patch.object(
            main,
            "_proxy_to_worker",
            AsyncMock(return_value={"results": [{"instance_id": "spide-node-1", "probe_ok": True}]}),
        ) as proxy,
    ):
        response = TestClient(main.app).get("/api/admin/provider-network/active-probe?worker_ids=118903")

    assert response.status_code == 200
    assert response.json()["reports"][0]["worker_id"] == 118903
    proxy.assert_awaited_once()
    assert proxy.await_args.kwargs["json"] == {"instances": ["spide-node-1"]}


def test_active_probe_filters_provider_and_instances():
    from app import main

    with (
        patch.object(main, "_require_owner"),
        patch.object(
            main.database,
            "list_workers",
            AsyncMock(
                return_value=[
                    {
                        "id": 118903,
                        "status": "online",
                        "containers": (
                            '[{"slug":"proxies-sx","instance_slug":"sx-1"},{"slug":"spide","instance_slug":"spide-1"}]'
                        ),
                    }
                ]
            ),
        ),
        patch.object(
            main,
            "_proxy_to_worker",
            AsyncMock(return_value={"results": [{"instance_id": "sx-1", "probe_ok": True}]}),
        ) as proxy,
    ):
        response = TestClient(main.app).get(
            "/api/admin/provider-network/active-probe?worker_ids=118903&provider=proxies-sx&instance_ids=sx-1"
        )

    assert response.status_code == 200
    assert proxy.await_args.kwargs["json"] == {"instances": ["sx-1"]}


def test_active_probe_reports_worker_timeout_without_hanging():
    from app import main

    async def hangs(*_args, **_kwargs):
        await asyncio.sleep(1.1)

    with (
        patch.object(main, "_require_owner"),
        patch.object(
            main.database,
            "list_workers",
            AsyncMock(
                return_value=[
                    {
                        "id": 118903,
                        "status": "online",
                        "containers": '[{"slug":"proxies-sx","instance_slug":"sx-1"}]',
                    }
                ]
            ),
        ),
        patch.object(main, "_proxy_to_worker", hangs),
    ):
        response = TestClient(main.app).get(
            "/api/admin/provider-network/active-probe?worker_ids=118903&provider=proxies-sx&timeout_seconds=1"
        )

    assert response.status_code == 200
    result = response.json()["reports"][0]["results"][0]
    assert result["error"] == "probe_timeout"


def test_active_probe_requires_repeated_failures_before_confirming_unhealthy():
    from app import main

    probe = AsyncMock(
        side_effect=[
            {"results": [{"instance_id": "sx-1", "probe_ok": False, "running": True, "observed_egress_ip": ""}]},
            {"results": [{"instance_id": "sx-1", "probe_ok": True, "running": True, "observed_egress_ip": "1.2.3.4"}]},
            {"results": [{"instance_id": "sx-1", "probe_ok": False, "running": True, "observed_egress_ip": ""}]},
        ]
    )
    with (
        patch.object(main, "_require_owner"),
        patch.object(
            main.database,
            "list_workers",
            AsyncMock(
                return_value=[
                    {
                        "id": 118903,
                        "status": "online",
                        "containers": '[{"slug":"proxies-sx","instance_slug":"sx-1"}]',
                    }
                ]
            ),
        ),
        patch.object(main, "_proxy_to_worker", probe),
    ):
        response = TestClient(main.app).get(
            "/api/admin/provider-network/active-probe?worker_ids=118903&provider=proxies-sx&attempts=3"
        )

    assert response.status_code == 200
    result = response.json()["reports"][0]["results"][0]
    assert result["attempts"] == 3
    assert result["successes"] == 1
    assert result["confirmed_failed"] is False
    assert result["observed_egress_ip"] == "1.2.3.4"
    assert probe.await_count == 3
