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

def test_wipter_deploy_credentials_map_from_stored_config_to_worker_args():
    svc = catalog.get_service("wipter")

    assert main._resolve_deploy_credentials(
        "wipter",
        svc,
        {"wipter_email": "user@example.com", "wipter_password": "secret"},
    ) == {"email": "user@example.com", "password": "secret"}

def test_proxybase_xyz_deploy_phrase_maps_from_settings_to_worker_args():
    svc = catalog.get_service("proxybase-xyz")

    assert main._resolve_deploy_credentials(
        "proxybase-xyz",
        svc,
        {"proxybase-xyz_phrase": "seed phrase words"},
    ) == {"phrase": "seed phrase words"}

def test_proxybase_deploy_and_dashboard_tokens_stay_separate():
    svc = catalog.get_service("proxybase")

    deploy = main._resolve_deploy_credentials(
        "proxybase",
        svc,
        {
            "proxybase_deploy_access_token": "deploy-token",
        },
    )
    assert deploy == {"deploy_access_token": "deploy-token"}

def test_proxylite_user_id_maps_from_settings_to_worker_args():
    svc = catalog.get_service("proxylite")

    assert main._resolve_deploy_credentials(
        "proxylite",
        svc,
        {"proxylite_user_id": "000000"},
    ) == {"user_id": "000000"}


def test_urnetwork_auth_token_maps_from_settings_to_worker_args():
    svc = catalog.get_service("urnetwork")

    assert main._resolve_deploy_credentials(
        "urnetwork",
        svc,
        {"urnetwork_auth_token": "jwt-token"},
    ) == {"auth_token": "jwt-token"}

def test_adnade_username_maps_from_settings_to_worker_args():
    svc = catalog.get_service("adnade")

    assert main._resolve_deploy_credentials(
        "adnade",
        svc,
        {"adnade_username": "assetforge", "adnade_chrome_profile_zip": "Zg=="},
    ) == {"username": "assetforge", "chrome_profile_zip": "Zg=="}
