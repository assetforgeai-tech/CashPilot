from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app import database, main


def _slot() -> dict[str, object]:
    return {
        "slot_id": "ipv4-001",
        "public_ip": "8.8.8.8",
        "private_ip": "10.20.0.4",
        "route_ready": True,
    }


def _lease() -> dict[str, object]:
    return {
        "id": 7,
        "wallet_assignment_version": 3,
        "wallet_json": '{"Address":"NKNwalletAddress"}',
        "wallet_pswd": "password-value",
        "public_ip": "8.8.8.8",
    }


def test_nkn_lxd_settings_have_safe_defaults_and_normalize_values():
    assert main._nkn_lxd_settings({}) == {"cpu": 1, "memory_mib": 1024}
    assert main._nkn_lxd_settings({"nkn_lxd_cpu": "2", "nkn_lxd_memory_mib": "2048"}) == {
        "cpu": 2,
        "memory_mib": 2048,
    }


@pytest.mark.parametrize(
    "config",
    [
        {"nkn_lxd_cpu": "0"},
        {"nkn_lxd_cpu": "65"},
        {"nkn_lxd_cpu": "1.5"},
        {"nkn_lxd_memory_mib": "127"},
        {"nkn_lxd_memory_mib": "65537"},
        {"nkn_lxd_memory_mib": "one-gib"},
    ],
)
def test_nkn_lxd_settings_reject_out_of_range_values(config):
    with pytest.raises(ValueError):
        main._nkn_lxd_settings(config)


def test_nkn_slot_payload_carries_server_authoritative_lxd_limits():
    async def run():
        with (
            patch.object(database, "get_worker", AsyncMock(return_value={"id": 7, "client_id": "worker-a"})),
            patch.object(main, "_worker_public_ip_slots", AsyncMock(return_value=[_slot()])),
            patch.object(database, "lease_nkn_wallet", AsyncMock(return_value=_lease())),
            patch.object(database, "get_provider_instance", AsyncMock(return_value=None)),
            patch.object(database, "save_provider_instance", AsyncMock()),
            patch.object(main, "_proxy_worker_nkn_deploy", AsyncMock(return_value={"container_id": "lxd"})) as deploy,
        ):
            result = await main._deploy_nkn_slots(
                7,
                beneficiary_address="NKNBeneficiaryAddress",
                lxd_settings={"cpu": 2, "memory_mib": 2048},
            )
        assert result["deployed"] == ["ipv4-001"]
        spec = deploy.await_args.args[2]
        assert spec["runtime_backend"] == "lxd"
        assert spec["lxd_cpu"] == 2
        assert spec["lxd_memory_mib"] == 2048

    asyncio.run(run())


def test_settings_template_exposes_authoritative_nkn_lxd_limits():
    from pathlib import Path

    text = (Path(__file__).parents[1] / "app" / "templates" / "settings.html").read_text(encoding="utf-8")
    assert 'data-config="nkn_lxd_cpu"' in text
    assert 'data-config="nkn_lxd_memory_mib"' in text
