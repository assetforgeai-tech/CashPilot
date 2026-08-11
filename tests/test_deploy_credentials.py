from __future__ import annotations

import pytest
from fastapi import HTTPException

from app import catalog, main


def test_grass_deploy_credentials_map_from_stored_config_to_worker_args():
    svc = catalog.get_service("grass")
    config = {
        "grass_store_wynd_status": '"CONNECTED"',
        "grass_store_wynd_user_id": "user",
        "grass_store_token_expiry": "1817965755",
        "grass_store_auto_update": "true",
        "grass_store_wynd_authenticated": "true",
        "grass_store_refresh_token": "refresh",
        "grass_store_access_token": "access",
    }

    assert main._resolve_deploy_credentials("grass", svc, config) == {
        "store_wynd_status": '"CONNECTED"',
        "store_wynd_user_id": "user",
        "store_token_expiry": "1817965755",
        "store_auto_update": "true",
        "store_wynd_authenticated": "true",
        "store_refresh_token": "refresh",
        "store_access_token": "access",
    }


def test_grass_deploy_credentials_are_required_before_worker_deploy():
    svc = catalog.get_service("grass")

    with pytest.raises(HTTPException) as exc:
        main._resolve_deploy_credentials("grass", svc, {})

    assert exc.value.status_code == 400
    assert "wynd:user_id" in exc.value.detail
    assert "accessToken" in exc.value.detail

