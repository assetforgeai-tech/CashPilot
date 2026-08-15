from __future__ import annotations

import pytest
from fastapi import HTTPException

from app import catalog, main
from app.collectors import collector_credential_fields, service_credential_fields


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


def test_urnetwork_api_key_maps_from_settings_to_worker_args():
    svc = catalog.get_service("urnetwork")

    assert main._resolve_deploy_credentials(
        "urnetwork",
        svc,
        {"urnetwork_api_key": "api-key"},
    ) == {"api_key": "api-key"}

def test_proxyrack_deploy_runtime_requires_only_api_key():
    svc = catalog.get_service("proxyrack")
    fields = service_credential_fields("proxyrack", "deploy", svc, fallback=False)

    assert [field["arg"] for field in fields] == ["api_key"]
    assert fields[0]["required"] is True
    assert main._resolve_deploy_credentials(
        "proxyrack",
        svc,
        {"proxyrack_api_key": "api-key"},
    ) == {"api_key": "api-key"}

def test_earnapp_deploy_runtime_uses_browser_session_tokens_not_manual_uuid():
    svc = catalog.get_service("earnapp")
    fields = service_credential_fields("earnapp", "deploy", svc, fallback=False)

    assert [field["arg"] for field in fields] == [
        "oauth_refresh_token",
        "oauth_token",
        "xsrf_token",
        "brd_sess_id",
        "cg_uuid",
    ]
    assert main._resolve_deploy_credentials(
        "earnapp",
        svc,
        {
            "earnapp_oauth_refresh_token": "refresh",
            "earnapp_oauth_token": "oauth",
            "earnapp_xsrf_token": "xsrf",
            "earnapp_brd_sess_id": "sess",
            "earnapp_cg_uuid": "cg",
        },
    ) == {
        "oauth_refresh_token": "refresh",
        "oauth_token": "oauth",
        "xsrf_token": "xsrf",
        "brd_sess_id": "sess",
        "cg_uuid": "cg",
    }

def test_settings_deploy_credentials_cover_node_creation_inputs_from_runtime_scripts():
    expected = {
        "bitping": {"email", "password"},
        "earnapp": {"oauth_refresh_token", "oauth_token", "xsrf_token", "brd_sess_id", "cg_uuid"},
        "earnfm": {"token"},
        "packetstream": {"cid"},
        "iproyal": {"email", "password", "device_name", "device_id"},
        "proxies-sx": {"api_key", "agent_name"},
        "proxyrack": {"api_key"},
        "repocket": {"email", "api_key"},
        "traffmonetizer": {"token"},
        "urnetwork": {"api_key"},
        "spide": {"email", "password"},
    }

    for slug, args in expected.items():
        fields = {field["arg"] for field in service_credential_fields(slug, "deploy", catalog.get_service(slug), fallback=False)}
        assert args <= fields, slug

    tm_fields = {field["arg"] for field in service_credential_fields("traffmonetizer", "deploy", catalog.get_service("traffmonetizer"), fallback=False)}
    assert "device_name" not in tm_fields

def test_settings_collector_credentials_cover_provider_collector_notes():
    expected = {
        "bitping": {"email", "password"},
        "earnfm": {"email", "password"},
        "iproyal": {"email", "password"},
        "packetstream": {"auth_token"},
        "proxies-sx": {"api_key"},
        "proxyrack": {"api_key"},
        "repocket": {"email", "password"},
        "traffmonetizer": {"email", "password"},
        "urnetwork": {"email", "password"},
    }

    for slug, args in expected.items():
        fields = {field["arg"] for field in collector_credential_fields(slug, catalog.get_service(slug))}
        assert args <= fields, slug

def test_iproyal_runtime_and_collector_credentials_are_separate():
    svc = catalog.get_service("iproyal")

    deploy_fields = {field["key"]: field["arg"] for field in service_credential_fields("iproyal", "deploy", svc, fallback=False)}
    collector_fields = {field["key"]: field["arg"] for field in collector_credential_fields("iproyal", svc)}

    assert deploy_fields["iproyal_email"] == "email"
    assert deploy_fields["iproyal_password"] == "password"
    assert collector_fields == {
        "iproyal_collector_email": "email",
        "iproyal_collector_password": "password",
    }

def test_node_count_only_providers_have_no_earnings_collector_inputs():
    for slug in ("proxylite", "proxybase-xyz", "uprock", "wipter"):
        svc = catalog.get_service(slug)
        assert (svc.get("collector") or {}).get("type") == "manual"
        assert collector_credential_fields(slug, svc) == []

def test_deploy_config_fields_can_feed_docker_env():
    svc = catalog.get_service("repocket")
    env = {}

    main._apply_deploy_config_to_env(
        "repocket",
        svc,
        {"repocket_email": "user@example.com", "repocket_api_key": "api-key"},
        env,
    )

    assert env == {"RP_EMAIL": "user@example.com", "RP_API_KEY": "api-key"}
