from __future__ import annotations

from unittest.mock import MagicMock, patch

from app import orchestrator


def test_deploy_raw_patches_grass_auth_seed_after_first_start():
    client = MagicMock()
    client.containers.get.side_effect = orchestrator.NotFound("nope")
    container = MagicMock(short_id="abc123", id="container-id")
    client.containers.run.return_value = container
    credentials = {
        "store_access_token": '"access"',
        "store_refresh_token": '"refresh"',
        "store_token_expiry": "1818650340",
        "store_wynd_status": '"CONNECTED"',
        "store_wynd_authenticated": "true",
        "store_wynd_user_id": '"user"',
        "store_auto_update": "true",
    }

    with (
        patch.object(orchestrator, "_get_client", return_value=client),
        patch.object(orchestrator.provider_automation, "apply_grass_store_patch") as patch_store,
    ):
        orchestrator.deploy_raw(
            slug="grass",
            image="cashpilot/grass-desktop:auto",
            deploy_credentials=credentials,
        )

    env = client.containers.run.call_args.kwargs["environment"]
    assert "USER_EMAIL" not in env
    assert "USER_PASSWORD" not in env
    assert client.containers.run.call_args.kwargs["image"] == "cashpilot/grass-desktop:auto"
    patch_store.assert_called_once_with(container, credentials)


def test_grass_store_patch_includes_token_expiry():
    patch = orchestrator.provider_automation.grass_store_patch(
        {
            "store_access_token": '"access"',
            "store_refresh_token": '"refresh"',
            "store_token_expiry": "1818650340",
            "store_wynd_status": '"CONNECTED"',
            "store_wynd_authenticated": "true",
            "store_wynd_user_id": '"user"',
            "store_auto_update": "true",
        }
    )

    assert patch["tokenExpiry"] == "1818650340"


def test_grass_patch_waits_only_for_store_file_before_overwriting_auth_seed():
    container = MagicMock(short_id="abc123", id="container-id")
    container.exec_run.side_effect = [
        MagicMock(exit_code=1),
        MagicMock(exit_code=0),
        MagicMock(exit_code=0),
    ]
    container.put_archive.return_value = True

    with (
        patch.object(orchestrator.provider_automation.time, "sleep"),
        patch.object(orchestrator.provider_automation.time, "monotonic", side_effect=[0, 1, 2]),
    ):
        orchestrator.provider_automation.apply_grass_store_patch(
            container,
            {
                "store_access_token": '"access"',
                "store_refresh_token": '"refresh"',
                "store_token_expiry": "1818650340",
                "store_wynd_status": '"CONNECTED"',
                "store_wynd_authenticated": "true",
                "store_wynd_user_id": '"user"',
                "store_auto_update": "true",
            },
            timeout_seconds=5,
            poll_seconds=0,
        )

    assert container.put_archive.called
    container.kill.assert_not_called()
    container.start.assert_not_called()
    check = container.exec_run.call_args_list[0].args[0]
    assert "test -s" in check[-1]
    assert "wynd:device_id" not in check[-1]


def test_deploy_raw_preseeds_grass_named_volume_before_start(tmp_path):
    client = MagicMock()
    client.containers.get.side_effect = orchestrator.NotFound("nope")
    container = MagicMock(short_id="abc123", id="container-id")
    events = []

    class _Volumes:
        def get(self, name):
            assert name == "grass-profile-proxy-2"
            return MagicMock()

        def create(self, name):
            assert name == "grass-profile-proxy-2"
            return MagicMock()

    def run(**_kwargs):
        events.append(_kwargs["name"])
        return container

    client.volumes = _Volumes()
    client.containers.run.side_effect = run

    with (
        patch.object(orchestrator, "_get_client", return_value=client),
        patch.object(orchestrator.provider_automation, "apply_grass_store_patch") as post_start_patch,
    ):
        orchestrator.deploy_raw(
            slug="grass-proxy-2",
            provider_slug="grass",
            image="cashpilot/grass-desktop:auto",
            volumes={"grass-profile-proxy-2": {"bind": "/var/lib/grass-xdg", "mode": "rw"}},
            deploy_credentials={
                "store_access_token": '"access"',
                "store_refresh_token": '"refresh"',
                "store_token_expiry": "1818650340",
                "store_wynd_status": '"CONNECTED"',
                "store_wynd_authenticated": "true",
                "store_wynd_user_id": '"user"',
                "store_auto_update": "true",
            },
        )

    assert events == ["cashpilot-grass-profile-proxy-2-seed", "cashpilot-grass-proxy-2"]
    seed_call = client.containers.run.call_args_list[0].kwargs
    assert seed_call["remove"] is True
    assert seed_call["volumes"] == {"grass-profile-proxy-2": {"bind": "/seed", "mode": "rw"}}
    assert '"tokenExpiry":"1818650340"' in seed_call["environment"]["GRASS_STORE_JSON"]
    post_start_patch.assert_not_called()


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
