import pytest
from fastapi import HTTPException

from app import worker_api


def test_slot_network_requires_matching_ready_bootstrap_record(monkeypatch):
    monkeypatch.setattr(
        worker_api,
        "_load_public_ip_slots",
        lambda: [
            {
                "slot_id": "ipv4-001",
                "docker_network": "cashpilot-direct-ipv4-001",
                "route_ready": True,
            }
        ],
    )
    worker_api._validate_deploy_spec(
        worker_api.DeploySpec(
            image="example/image:1",
            provider_slug="earnfm",
            network="cashpilot-direct-ipv4-001",
            public_ip_slot="ipv4-001",
        )
    )


def test_slot_network_rejects_mismatch(monkeypatch):
    monkeypatch.setattr(worker_api, "_load_public_ip_slots", lambda: [])
    with pytest.raises(HTTPException, match="slot network"):
        worker_api._validate_deploy_spec(
            worker_api.DeploySpec(
                image="example/image:1",
                provider_slug="earnfm",
                network="cashpilot-direct-ipv4-001",
                public_ip_slot="ipv4-001",
            )
        )
