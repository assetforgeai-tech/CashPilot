from unittest.mock import MagicMock, patch

from app import orchestrator


def test_deploy_raw_enables_init_reaper():
    client = MagicMock()
    container = MagicMock(short_id="abc")
    client.containers.run.return_value = container
    with patch.object(orchestrator, "_get_client", return_value=client):
        orchestrator.deploy_raw(slug="demo", image="img:1")
    assert client.containers.run.call_args.kwargs["init"] is True
