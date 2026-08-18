from __future__ import annotations

from unittest.mock import MagicMock, patch

from app import orchestrator


def test_deploy_raw_maps_grass_account_credentials_to_env():
    client = MagicMock()
    client.containers.get.side_effect = orchestrator.NotFound("nope")
    container = MagicMock(short_id="abc123", id="container-id")
    client.containers.run.return_value = container

    with patch.object(orchestrator, "_get_client", return_value=client):
        orchestrator.deploy_raw(
            slug="grass",
            image="cashpilot/grass-desktop:auto",
            env={"USER_EMAIL": "user@example.com", "USER_PASSWORD": "secret"},
            deploy_credentials={"email": "user@example.com", "password": "secret"},
        )

    env = client.containers.run.call_args.kwargs["environment"]
    assert env["USER_EMAIL"] == "user@example.com"
    assert env["USER_PASSWORD"] == "secret"
    container.restart.assert_not_called()


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
        patch.object(
            orchestrator.provider_installers,
            "ensure_proxybase_xyz_image",
            return_value="cashpilot/proxybase-xyz-cli:latest-ubuntu24.04",
        ),
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
    assert "export HOME=/home/proxybase" in command
    assert 'PHASE="${PROXYBASE_XYZ_PHRASE:?missing wallet phrase}"' in command
    assert '"$CLI" wallet import "$PHASE"' in command
    assert '"$CLI" login' in command
    assert "seller_config.json" in command
    assert 'exec "$CLI" seller start --foreground' in command


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
    assert env["NAME"] == "cashpilot-node"
    assert client.containers.run.call_args.kwargs["command"] == ["deploy-token", "cashpilot-node"]


def test_deploy_raw_authenticates_urnetwork_with_api_key_before_provider_start():
    client = MagicMock()
    client.containers.get.side_effect = orchestrator.NotFound("nope")
    container = MagicMock(short_id="abc123", id="container-id")
    client.containers.run.return_value = container

    with (
        patch.object(orchestrator, "_get_client", return_value=client),
        patch.object(orchestrator, "_urnetwork_auth_code", return_value="auth-code") as auth_code,
    ):
        orchestrator.deploy_raw(
            slug="urnetwork",
            image="bringyour/community-provider",
            volumes={"urnetwork-data": {"bind": "/root/.urnetwork", "mode": "rw"}},
            deploy_credentials={"api_key": "api-key"},
        )

    auth_code.assert_called_once_with("api-key")
    auth_call, provider_call = client.containers.run.call_args_list[-2:]
    assert auth_call.kwargs["entrypoint"] == "/usr/local/sbin/bringyour-provider"
    assert auth_call.kwargs["command"] == ["auth", "auth-code"]
    assert auth_call.kwargs["remove"] is True
    assert auth_call.kwargs["volumes"] == {"urnetwork-data": {"bind": "/root/.urnetwork", "mode": "rw"}}
    assert provider_call.kwargs["command"] == "provide"
    assert provider_call.kwargs["environment"]["UR_API_KEY"] == "api-key"


def test_deploy_raw_forwards_container_user_when_declared():
    client = MagicMock()
    client.containers.get.side_effect = orchestrator.NotFound("nope")
    container = MagicMock(short_id="abc123", id="container-id")
    client.containers.run.return_value = container

    with patch.object(orchestrator, "_get_client", return_value=client):
        orchestrator.deploy_raw(slug="wipter", image="img:1", user="root")

    assert client.containers.run.call_args.kwargs["user"] == "root"
