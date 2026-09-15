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
