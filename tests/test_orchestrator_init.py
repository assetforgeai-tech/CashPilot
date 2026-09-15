from unittest.mock import MagicMock, patch

from app import orchestrator


def test_deploy_raw_enables_init_reaper():
    client = MagicMock()
    container = MagicMock(short_id="abc")
    client.containers.run.return_value = container
    with patch.object(orchestrator, "_get_client", return_value=client):
        orchestrator.deploy_raw(slug="demo", image="img:1")
    assert client.containers.run.call_args.kwargs["init"] is True


def test_deploy_raw_does_not_pull_locally_built_installer_image():
    client = MagicMock()
    client.containers.run.return_value = MagicMock(short_id="abc")
    with (
        patch.object(orchestrator, "_get_client", return_value=client),
        patch.object(orchestrator.provider_installers, "resolve_installer_manifest", return_value={"version": "v1", "url": "https://example.test/a"}),
        patch.object(orchestrator.provider_installers, "ensure_installer_image", return_value="cashpilot/uprock-mining:v1-ubuntu24.04"),
    ):
        orchestrator.deploy_raw(
            slug="uprock-node",
            provider_slug="uprock",
            image="cashpilot/uprock-mining:auto",
            installer_manifest_url="https://edge.uprock.com/v1/app-download/UpRock-Mining-v0.0.38.deb",
        )
    client.images.pull.assert_not_called()
