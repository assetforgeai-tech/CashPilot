from __future__ import annotations

import io
import json
import tarfile
from unittest.mock import MagicMock, patch

import pytest

from app import orchestrator, provider_automation


def test_grass_store_patch_requires_the_confirmed_seven_fields():
    creds = {
        "store_wynd_status": '"CONNECTED"',
        "store_wynd_user_id": "user",
        "store_token_expiry": "1817965755",
        "store_auto_update": "true",
        "store_wynd_authenticated": "true",
        "store_refresh_token": "refresh",
        "store_access_token": "access",
    }

    assert provider_automation.grass_store_patch(creds) == {
        "wynd:status": '"CONNECTED"',
        "wynd:user_id": "user",
        "tokenExpiry": "1817965755",
        "autoUpdate": "true",
        "wynd:authenticated": "true",
        "refreshToken": "refresh",
        "accessToken": "access",
    }


def test_grass_store_patch_refuses_partial_credentials():
    with pytest.raises(ValueError, match="store_access_token"):
        provider_automation.grass_store_patch(
            {
                "store_wynd_status": '"CONNECTED"',
                "store_wynd_user_id": "user",
                "store_token_expiry": "1817965755",
                "store_auto_update": "true",
                "store_wynd_authenticated": "true",
                "store_refresh_token": "refresh",
            }
        )


def test_grass_patch_waits_for_store_writes_patch_file_and_restarts():
    container = MagicMock()
    container.exec_run.side_effect = [
        MagicMock(exit_code=1),
        MagicMock(exit_code=0),
        MagicMock(exit_code=0),
    ]
    creds = {
        "store_wynd_status": '"CONNECTED"',
        "store_wynd_user_id": "user",
        "store_token_expiry": "1817965755",
        "store_auto_update": "true",
        "store_wynd_authenticated": "true",
        "store_refresh_token": "refresh",
        "store_access_token": "access",
    }

    provider_automation.apply_grass_store_patch(container, creds, timeout_seconds=2, poll_seconds=0)

    assert container.exec_run.call_count == 3
    assert container.restart.call_count == 1
    target, archive = container.put_archive.call_args.args
    assert target == "/tmp"
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r") as tf:
        payload = json.loads(tf.extractfile("cashpilot-grass-store-patch.json").read())
    assert payload["store"]["accessToken"] == "access"
    assert payload["store"]["wynd:status"] == '"CONNECTED"'


def test_deploy_raw_applies_grass_store_patch_after_container_create():
    client = MagicMock()
    client.containers.get.side_effect = orchestrator.NotFound("nope")
    container = MagicMock(short_id="abc123", id="container-id")
    client.containers.run.return_value = container
    creds = {
        "store_wynd_status": '"CONNECTED"',
        "store_wynd_user_id": "user",
        "store_token_expiry": "1817965755",
        "store_auto_update": "true",
        "store_wynd_authenticated": "true",
        "store_refresh_token": "refresh",
        "store_access_token": "access",
    }

    with (
        patch.object(orchestrator, "_get_client", return_value=client),
        patch.object(orchestrator.provider_automation, "apply_grass_store_patch") as apply_patch,
    ):
        orchestrator.deploy_raw(slug="grass", image="img:1", deploy_credentials=creds)

    apply_patch.assert_called_once_with(container, creds)

def test_deploy_raw_maps_wipter_credentials_to_env_and_restarts_after_login_state():
    client = MagicMock()
    client.containers.get.side_effect = orchestrator.NotFound("nope")
    container = MagicMock(short_id="abc123", id="container-id")
    client.containers.run.return_value = container

    with (
        patch.object(orchestrator, "_get_client", return_value=client),
        patch.object(orchestrator.provider_automation, "schedule_wipter_post_login_restart") as restart_once,
    ):
        orchestrator.deploy_raw(
            slug="wipter",
            image="img:1",
            env={"EXTRA": "1"},
            deploy_credentials={"email": "user@example.com", "password": "secret"},
        )

    env = client.containers.run.call_args.kwargs["environment"]
    assert env["EXTRA"] == "1"
    assert env["WIPTER_EMAIL"] == "user@example.com"
    assert env["WIPTER_PASSWORD"] == "secret"
    restart_once.assert_called_once_with(container)

def test_deploy_raw_builds_proxybase_xyz_command_from_deploy_phrase():
    client = MagicMock()
    client.containers.get.side_effect = orchestrator.NotFound("nope")
    container = MagicMock(short_id="abc123", id="container-id")
    client.containers.run.return_value = container

    with (
        patch.object(orchestrator, "_get_client", return_value=client),
        patch.object(orchestrator.provider_installers, "ensure_proxybase_xyz_image", return_value="cashpilot/proxybase-xyz-cli:latest-ubuntu24.04"),
    ):
        orchestrator.deploy_raw(
            slug="proxybase-xyz",
            image="ubuntu:24.04",
            deploy_credentials={"phrase": "seed phrase words"},
        )

    assert client.containers.run.call_args.kwargs["image"] == "cashpilot/proxybase-xyz-cli:latest-ubuntu24.04"
    command = client.containers.run.call_args.kwargs["command"]
    assert "apt-get" not in command
    assert "https://proxybase.xyz/install.sh" not in command
    env = client.containers.run.call_args.kwargs["environment"]
    assert env["PROXYBASE_XYZ_PHRASE"] == "seed phrase words"
    assert 'PHASE="${PROXYBASE_XYZ_PHRASE:?missing wallet phrase}"' in command
    assert '"$CLI" wallet import "$PHASE"' in command
    assert '"$CLI" login' in command

def test_deploy_raw_maps_proxybase_deploy_token_to_peer_cli_args():
    client = MagicMock()
    client.containers.get.side_effect = orchestrator.NotFound("nope")
    container = MagicMock(short_id="abc123", id="container-id")
    client.containers.run.return_value = container

    with patch.object(orchestrator, "_get_client", return_value=client):
        orchestrator.deploy_raw(
            slug="proxybase",
            image="ghcr.io/proxybaseorg/peer-cli:latest",
            env={"NAME": "cashpilot-node"},
            deploy_credentials={"deploy_access_token": "deploy-token"},
        )

    env = client.containers.run.call_args.kwargs["environment"]
    assert env["ID"] == "deploy-token"
    assert env["NAME"] == "cashpilot-node"

def test_deploy_raw_maps_proxylite_user_id_to_proxyservice_env():
    client = MagicMock()
    client.containers.get.side_effect = orchestrator.NotFound("nope")
    container = MagicMock(short_id="abc123", id="container-id")
    client.containers.run.return_value = container

    with patch.object(orchestrator, "_get_client", return_value=client):
        orchestrator.deploy_raw(
            slug="proxylite",
            image="proxylite/proxyservice",
            deploy_credentials={"user_id": "000000"},
        )

    env = client.containers.run.call_args.kwargs["environment"]
    assert env["USER_ID"] == "000000"


def test_deploy_raw_maps_urnetwork_auth_token_to_provider_env():
    client = MagicMock()
    client.containers.get.side_effect = orchestrator.NotFound("nope")
    container = MagicMock(short_id="abc123", id="container-id")
    client.containers.run.return_value = container

    with patch.object(orchestrator, "_get_client", return_value=client):
        orchestrator.deploy_raw(
            slug="urnetwork",
            image="bringyour/community-provider",
            deploy_credentials={"auth_token": "jwt-token"},
        )

    env = client.containers.run.call_args.kwargs["environment"]
    assert env["UR_AUTH_TOKEN"] == "jwt-token"

def test_deploy_raw_maps_adnade_username_to_chrome_url():
    client = MagicMock()
    client.containers.get.side_effect = orchestrator.NotFound("nope")
    container = MagicMock(short_id="abc123", id="container-id")
    client.containers.run.return_value = container

    with patch.object(orchestrator, "_get_client", return_value=client):
        orchestrator.deploy_raw(
            slug="adnade",
            image="lscr.io/linuxserver/chromium:latest",
            deploy_credentials={"username": "assetforge"},
        )

    env = client.containers.run.call_args.kwargs["environment"]
    assert env["ADNADE_USERNAME"] == "assetforge"
    assert env["ADNADE_USE_CHROME"] == "true"
    assert env["CUSTOM_PORT"] == "3000"
    assert env["CHROME_CLI"] == "https://adnade.net/view.php?user=assetforge&multi=4"


def test_deploy_raw_forwards_container_user_when_declared():
    client = MagicMock()
    client.containers.get.side_effect = orchestrator.NotFound("nope")
    container = MagicMock(short_id="abc123", id="container-id")
    client.containers.run.return_value = container

    with patch.object(orchestrator, "_get_client", return_value=client):
        orchestrator.deploy_raw(slug="wipter", image="img:1", user="root")

    assert client.containers.run.call_args.kwargs["user"] == "root"
