from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException
from starlette.requests import Request

from app import catalog, database, earnapp_canary, earnapp_runtime, main, provider_runtime, worker_api
from scripts import build_earnapp_canary_image


def test_mac_profile_blob_uses_the_official_boot_js_default_key():
    assert hashlib.sha256(b"Earn-app-2movn-0951").hexdigest() == earnapp_runtime.MAC_PROFILE_KEY_HEX
    assert bytes.fromhex(earnapp_runtime.MAC_PROFILE_KEY_HEX) == earnapp_runtime.MAC_PROFILE_KEY
    identity = {"platform": "darwin", "appid": "mac_com.earnapp", "id": "test", "serial": "serial"}
    encrypted = earnapp_runtime.encrypt_mac_profile(identity)
    blob = base64.b64decode(encrypted, validate=True)
    nonce = blob[21:33]
    ciphertext = blob[33:]
    key = hashlib.sha256(b"Earn-app-2movn-0951").digest()
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, blob[:21])
    assert json.loads(plaintext.decode("utf-8")) == identity


def test_image_builder_default_source_points_to_cashpilot_bundle():
    expected = Path(__file__).resolve().parents[2] / "earnapp_new_update" / "earnapp-runtime-files" / "mac"
    assert build_earnapp_canary_image.default_source_dir() == expected


def _request(path: str) -> Request:
    return Request({"type": "http", "method": "POST", "path": path, "headers": []})


def test_earnapp_is_proxy_only_and_catalog_is_active():
    runtime = provider_runtime.get("earnapp")
    assert runtime is not None
    assert runtime.modes == ("proxy",)
    service = catalog.get_service("earnapp")
    assert service is not None
    assert service["status"] == "active"
    assert service["egress"]["mode"] == "proxy"


def test_canary_spec_is_account_scoped_and_hardened():
    spec = earnapp_canary.build_canary_spec(
        logical_node_id="earnapp-canary-1",
        account_id=7,
        device_id="sdk-mac-test",
        proxy={"proxy_id": 12, "exit_ip": "203.0.113.10"},
    )
    assert spec["provider_slug"] == "earnapp"
    assert spec["labels"]["cashpilot.earnapp.logical_node_id"] == "earnapp-canary-1"
    assert spec["labels"]["cashpilot.earnapp.account_id"] == "7"
    assert spec["volumes"]["earnapp-canary-1-data"]["bind"] == "/etc/earnapp"
    assert spec["privileged"] is False
    assert spec["cap_add"] is None
    assert spec["devices"] is None
    assert spec["image"] == earnapp_runtime.MAC_RUNTIME_IMAGE
    assert "/var/run/docker.sock" not in str(spec)
    assert "/dev/kvm" not in str(spec)


def test_canary_spec_requires_verified_mac_runtime_image():
    spec = earnapp_canary.build_canary_spec(
        logical_node_id="earnapp-canary-1",
        account_id=7,
        device_id="sdk-mac-test",
        proxy={"proxy_id": 12, "exit_ip": "203.0.113.10"},
    )
    assert spec["labels"]["cashpilot.earnapp.platform"] == "darwin"
    assert spec["labels"]["cashpilot.earnapp.runtime_contract"] == "mac_com.earnapp"
    assert spec["env"]["EARNAPP_DEVICE_ID"] == "sdk-mac-test"
    assert spec["env"]["EARNAPP_PLATFORM"] == "darwin"
    assert spec["runtime_contract"] == {
        "platform": "darwin",
        "appid": "mac_com.earnapp",
        "device_id_prefix": "sdk-mac-",
    }
    assert spec["image"] == earnapp_runtime.MAC_RUNTIME_IMAGE
    assert spec["image_contract_sha256"] == earnapp_runtime.MAC_RUNTIME_ASSET_MANIFEST_SHA256


def test_canary_spec_does_not_put_account_tokens_in_container_env_or_labels():
    spec = earnapp_canary.build_canary_spec(
        logical_node_id="earnapp-canary-1",
        account_id=7,
        device_id="sdk-mac-test",
        proxy={"proxy_id": 12, "exit_ip": "203.0.113.10", "username": "u", "password": "p"},
    )
    serialized = json.dumps(spec, sort_keys=True)
    assert "oauth-refresh-token" not in serialized
    assert "xsrf-token" not in serialized
    assert '"password": "p"' not in serialized


def test_worker_reports_earnapp_instance_state_without_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    worker_api._save_earnapp_state(
        "earnapp-canary-1",
        {
            "logical_node_id": "earnapp-canary-1",
            "generation": 1,
            "device_id": "sdk-mac-test",
            "proxy_id": 12,
            "password": "proxy-secret",
        },
    )
    state = worker_api._earnapp_provider_state(
        [{"instance_slug": "earnapp-canary-1", "status": "running", "provider_evidence": {"online": True}}]
    )
    assert state["instances"][0]["logical_node_id"] == "earnapp-canary-1"
    assert state["instances"][0]["runtime_status"] == "running"
    assert "password" not in json.dumps(state)


def test_worker_deploy_spec_has_no_host_privilege():
    service = catalog.get_service("earnapp")
    assert service is not None
    assert service["docker"].get("privileged", False) is False
    assert not service["docker"].get("devices")
    assert not service["docker"].get("cap_add")


def test_runtime_asset_kind_accepts_mac_identity_profile():
    assert earnapp_runtime.validate_identity_asset_kind("mac_identity_profile") == "mac_identity_profile"


def test_runtime_asset_kind_rejects_untrusted_identity_profile():
    try:
        earnapp_runtime.validate_identity_asset_kind("lab_identity_profile")
    except ValueError as exc:
        assert "mac_identity_profile" in str(exc)
    else:
        raise AssertionError("untrusted identity asset kind must be rejected")


def test_runtime_mac_identity_is_stable_and_uses_expected_wire_contract(tmp_path):
    first = earnapp_runtime.ensure_mac_identity(tmp_path, seed="earnapp-canary-1")
    second = earnapp_runtime.ensure_mac_identity(tmp_path, seed="different-seed")

    assert second == first
    assert first["platform"] == "darwin"
    assert first["appid"] == "mac_com.earnapp"
    assert first["device_id"].startswith("sdk-mac-")


def test_server_profile_is_stable_per_logical_node_and_unique_between_nodes(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            first = await earnapp_canary.get_or_create_mac_identity_profile("earnapp-canary-1")
            retry = await earnapp_canary.get_or_create_mac_identity_profile("earnapp-canary-1")
            other = await earnapp_canary.get_or_create_mac_identity_profile("earnapp-canary-2")

        assert retry == first
        assert other["device_id"] != first["device_id"]
        assert other["value"] != first["value"]
        assert first["value"].startswith("RVNQRg")  # base64("ESPF")
        assert first["asset_id"] == "earnapp-canary-1"

    asyncio.run(run())


def test_auto_deploy_excludes_explicit_earnapp_canary_lane():
    services = [
        {
            "slug": "earnapp",
            "status": "active",
            "docker": {"image": earnapp_runtime.MAC_RUNTIME_IMAGE},
            "deploy": {"automation": "earnapp_mac_canary"},
        },
        {"slug": "earnfm", "status": "active", "docker": {"image": "image"}},
    ]

    assert main._auto_deploy_slugs(services) == ["earnfm"]


@pytest.mark.asyncio
async def test_generic_earnapp_deploy_is_rejected_before_worker_call(monkeypatch):
    deploy = AsyncMock()
    monkeypatch.setattr(main, "_resolve_worker_id", AsyncMock(return_value=7))
    monkeypatch.setattr(main, "_proxy_worker_deploy", deploy)

    with pytest.raises(HTTPException) as exc:
        await main.api_deploy(
            _request("/api/deploy/earnapp"),
            "earnapp",
            main.DeployRequest(env={}, mode="proxy"),
            worker_id=7,
            _auth={"r": "owner"},
        )

    assert exc.value.status_code == 409
    assert "canary" in str(exc.value.detail).lower()
    deploy.assert_not_awaited()


def test_worker_rejects_unverified_earnapp_runtime_contract():
    spec = worker_api.DeploySpec(
        image="ubuntu:latest",
        provider_slug="earnapp",
        host_runtime="earnapp_mac_canary",
        labels={"cashpilot.provider": "earnapp"},
    )

    with pytest.raises(HTTPException) as exc:
        worker_api._validate_deploy_spec(spec, slug="earnapp-canary-1")

    assert exc.value.status_code == 403


def test_verified_image_labels_are_fail_closed():
    with pytest.raises(ValueError):
        earnapp_runtime.validate_image_labels({})

    earnapp_runtime.validate_image_labels(earnapp_runtime.required_image_labels())


def test_mac_runtime_manifest_is_derived_from_authoritative_artifact_hashes():
    assert earnapp_runtime.runtime_asset_manifest_sha256() == (
        "4fbeed7fb3f2a2b4cc379399586fe0f589463bff0092b82897a8ff0fb34501ec"
    )
    assert earnapp_runtime.runtime_asset_manifest_sha256() == earnapp_runtime.MAC_RUNTIME_ASSET_MANIFEST_SHA256


def test_canary_image_build_recipe_validates_artifacts_and_emits_pinned_labels(tmp_path):
    source = tmp_path / "mac"
    source.mkdir()
    expected = {}
    for name in earnapp_runtime.MAC_RUNTIME_ARTIFACT_HASHES:
        payload = (name + "\n").encode()
        (source / name).write_bytes(payload)
        expected[name] = hashlib.sha256(payload).hexdigest()

    manifest = build_earnapp_canary_image.validate_artifacts(source, expected)
    assert manifest == earnapp_runtime.runtime_asset_manifest(expected)
    recipe = build_earnapp_canary_image.render_dockerfile(manifest)
    manifest_hash = earnapp_runtime.runtime_asset_manifest_sha256(expected)
    assert f"com.cashpilot.earnapp.assets-sha256={manifest_hash}" in recipe
    assert 'ENTRYPOINT ["/usr/local/bin/earn-supervisor"]' in recipe


@pytest.mark.asyncio
async def test_deploy_hands_proxy_secret_only_to_worker_and_persists_redacted_spec(monkeypatch):
    sent: list[dict] = []
    saved: list[dict] = []

    async def fake_worker_deploy(_worker_id: int, _slug: str, spec: dict):
        sent.append(spec)
        return {"container_id": "canary-container"}

    async def fake_save(_provider: str, _instance: str, **kwargs):
        saved.append(kwargs)

    monkeypatch.setattr(
        earnapp_canary,
        "get_or_create_mac_identity_profile",
        AsyncMock(
            return_value={
                "asset_id": "earnapp-canary-1",
                "device_id": "sdk-mac-test",
                "value": "encrypted-profile",
            }
        ),
    )
    monkeypatch.setattr(database, "get_provider_instance", AsyncMock(return_value=None))
    monkeypatch.setattr(
        earnapp_canary,
        "provision_canary",
        AsyncMock(
            return_value={
                "logical_node_id": "earnapp-canary-1",
                "account_id": 7,
                "worker_id": 3,
                "device_id": "sdk-mac-test",
                "proxy_id": 12,
                "generation": 1,
                "state": "ACTIVE",
                "created_binding": True,
            }
        ),
    )
    monkeypatch.setattr(
        database,
        "lease_proxy_for_provider_instance",
        AsyncMock(
            return_value={
                "proxy_id": 12,
                "host": "proxy.example",
                "port": 1080,
                "protocol": "socks5",
                "username": "proxy-user",
                "password": "proxy-password",
                "exit_ip": "203.0.113.10",
                "country_code": "VN",
                "ip_type": "residential",
            }
        ),
    )
    monkeypatch.setattr(database, "save_provider_instance", fake_save)

    result = await earnapp_canary.deploy_canary(
        "earnapp-canary-1",
        3,
        worker_deploy=fake_worker_deploy,
        worker_remove=AsyncMock(),
    )

    assert result["status"] == "deployed"
    assert sent[0]["proxy"]["password"] == "proxy-password"
    assert "proxy-password" not in json.dumps(saved[0]["spec"], sort_keys=True)
    assert "proxy-user" not in json.dumps(saved[0]["spec"], sort_keys=True)


@pytest.mark.asyncio
async def test_failed_canary_deploy_removes_and_rolls_back_only_that_canary(monkeypatch):
    remove = AsyncMock()
    rollback = AsyncMock(return_value=True)
    monkeypatch.setattr(
        earnapp_canary,
        "get_or_create_mac_identity_profile",
        AsyncMock(
            return_value={
                "asset_id": "earnapp-canary-1",
                "device_id": "sdk-mac-test",
                "value": "encrypted-profile",
            }
        ),
    )
    monkeypatch.setattr(database, "get_provider_instance", AsyncMock(return_value=None))
    monkeypatch.setattr(
        earnapp_canary,
        "provision_canary",
        AsyncMock(
            return_value={
                "logical_node_id": "earnapp-canary-1",
                "account_id": 7,
                "worker_id": 3,
                "device_id": "sdk-mac-test",
                "proxy_id": 12,
                "generation": 4,
                "state": "ACTIVE",
                "created_binding": True,
            }
        ),
    )
    monkeypatch.setattr(
        database,
        "lease_proxy_for_provider_instance",
        AsyncMock(
            return_value={
                "proxy_id": 12,
                "host": "proxy.example",
                "port": 1080,
                "protocol": "socks5",
                "password": "secret",
                "exit_ip": "203.0.113.10",
                "country_code": "VN",
                "ip_type": "residential",
            }
        ),
    )
    monkeypatch.setattr(database, "rollback_earnapp_canary_binding", rollback)

    with pytest.raises(RuntimeError, match="worker failed"):
        await earnapp_canary.deploy_canary(
            "earnapp-canary-1",
            3,
            worker_deploy=AsyncMock(side_effect=RuntimeError("worker failed")),
            worker_remove=remove,
        )

    remove.assert_awaited_once_with(3, "earnapp-canary-1")
    rollback.assert_awaited_once_with(
        "earnapp-canary-1",
        3,
        generation=4,
        proxy_id=12,
        reason="EARNAPP_CANARY_DEPLOY_FAILED",
    )


@pytest.mark.asyncio
async def test_failed_retry_does_not_remove_or_rollback_existing_canary(monkeypatch):
    remove = AsyncMock()
    rollback = AsyncMock(return_value=True)
    monkeypatch.setattr(
        earnapp_canary,
        "get_or_create_mac_identity_profile",
        AsyncMock(
            return_value={
                "asset_id": "earnapp-canary-1",
                "device_id": "sdk-mac-test",
                "value": "encrypted-profile",
            }
        ),
    )
    monkeypatch.setattr(database, "get_provider_instance", AsyncMock(return_value=None))
    monkeypatch.setattr(
        earnapp_canary,
        "provision_canary",
        AsyncMock(
            return_value={
                "logical_node_id": "earnapp-canary-1",
                "account_id": 7,
                "worker_id": 3,
                "device_id": "sdk-mac-test",
                "proxy_id": 12,
                "generation": 4,
                "state": "ACTIVE",
                "created_binding": False,
            }
        ),
    )
    monkeypatch.setattr(
        database,
        "lease_proxy_for_provider_instance",
        AsyncMock(
            return_value={
                "proxy_id": 12,
                "host": "proxy.example",
                "port": 1080,
                "protocol": "socks5",
                "password": "secret",
                "exit_ip": "203.0.113.10",
                "country_code": "VN",
                "ip_type": "residential",
            }
        ),
    )
    monkeypatch.setattr(database, "rollback_earnapp_canary_binding", rollback)

    with pytest.raises(RuntimeError, match="worker failed"):
        await earnapp_canary.deploy_canary(
            "earnapp-canary-1",
            3,
            worker_deploy=AsyncMock(side_effect=RuntimeError("worker failed")),
            worker_remove=remove,
        )

    remove.assert_not_awaited()
    rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_proxy_validation_failure_rolls_back_new_binding_before_worker_deploy(monkeypatch):
    deploy = AsyncMock()
    remove = AsyncMock()
    rollback = AsyncMock(return_value=True)
    monkeypatch.setattr(
        earnapp_canary,
        "get_or_create_mac_identity_profile",
        AsyncMock(
            return_value={
                "asset_id": "earnapp-canary-1",
                "device_id": "sdk-mac-test",
                "value": "encrypted-profile",
            }
        ),
    )
    monkeypatch.setattr(database, "get_provider_instance", AsyncMock(return_value=None))
    monkeypatch.setattr(
        earnapp_canary,
        "provision_canary",
        AsyncMock(
            return_value={
                "logical_node_id": "earnapp-canary-1",
                "account_id": 7,
                "worker_id": 3,
                "device_id": "sdk-mac-test",
                "proxy_id": 12,
                "generation": 4,
                "state": "ACTIVE",
                "created_binding": True,
            }
        ),
    )
    monkeypatch.setattr(
        database,
        "lease_proxy_for_provider_instance",
        AsyncMock(
            return_value={
                "proxy_id": 12,
                "host": "proxy.example",
                "port": 1080,
                "protocol": "socks5",
                "exit_ip": "203.0.113.10",
                "country_code": "US",
                "ip_type": "residential",
            }
        ),
    )
    monkeypatch.setattr(database, "rollback_earnapp_canary_binding", rollback)

    with pytest.raises(ValueError, match="VN residential"):
        await earnapp_canary.deploy_canary(
            "earnapp-canary-1",
            3,
            worker_deploy=deploy,
            worker_remove=remove,
        )

    deploy.assert_not_awaited()
    remove.assert_not_awaited()
    rollback.assert_awaited_once_with(
        "earnapp-canary-1",
        3,
        generation=4,
        proxy_id=12,
        reason="EARNAPP_CANARY_PREPARE_FAILED",
    )


@pytest.mark.asyncio
async def test_provider_instance_persist_failure_removes_and_rolls_back_new_canary(monkeypatch):
    remove = AsyncMock()
    rollback = AsyncMock(return_value=True)
    monkeypatch.setattr(
        earnapp_canary,
        "get_or_create_mac_identity_profile",
        AsyncMock(
            return_value={
                "asset_id": "earnapp-canary-1",
                "device_id": "sdk-mac-test",
                "value": "encrypted-profile",
            }
        ),
    )
    monkeypatch.setattr(database, "get_provider_instance", AsyncMock(return_value=None))
    monkeypatch.setattr(
        earnapp_canary,
        "provision_canary",
        AsyncMock(
            return_value={
                "logical_node_id": "earnapp-canary-1",
                "account_id": 7,
                "worker_id": 3,
                "device_id": "sdk-mac-test",
                "proxy_id": 12,
                "generation": 4,
                "state": "ACTIVE",
                "created_binding": True,
            }
        ),
    )
    monkeypatch.setattr(
        database,
        "lease_proxy_for_provider_instance",
        AsyncMock(
            return_value={
                "proxy_id": 12,
                "host": "proxy.example",
                "port": 1080,
                "protocol": "socks5",
                "exit_ip": "203.0.113.10",
                "country_code": "VN",
                "ip_type": "residential",
            }
        ),
    )
    monkeypatch.setattr(database, "save_provider_instance", AsyncMock(side_effect=RuntimeError("db failed")))
    monkeypatch.setattr(database, "rollback_earnapp_canary_binding", rollback)

    with pytest.raises(RuntimeError, match="db failed"):
        await earnapp_canary.deploy_canary(
            "earnapp-canary-1",
            3,
            worker_deploy=AsyncMock(return_value={"container_id": "canary-container"}),
            worker_remove=remove,
        )

    remove.assert_awaited_once_with(3, "earnapp-canary-1")
    rollback.assert_awaited_once_with(
        "earnapp-canary-1",
        3,
        generation=4,
        proxy_id=12,
        reason="EARNAPP_CANARY_PERSIST_FAILED",
    )


@pytest.mark.asyncio
async def test_retry_running_canary_is_idempotent_and_never_redeploys(monkeypatch):
    deploy = AsyncMock()
    remove = AsyncMock()
    monkeypatch.setattr(
        earnapp_canary,
        "get_or_create_mac_identity_profile",
        AsyncMock(
            return_value={
                "asset_id": "earnapp-canary-1",
                "device_id": "sdk-mac-test",
                "value": "encrypted-profile",
            }
        ),
    )
    monkeypatch.setattr(
        earnapp_canary,
        "provision_canary",
        AsyncMock(
            return_value={
                "logical_node_id": "earnapp-canary-1",
                "account_id": 7,
                "worker_id": 3,
                "device_id": "sdk-mac-test",
                "proxy_id": 12,
                "generation": 4,
                "state": "ACTIVE",
                "created_binding": False,
            }
        ),
    )
    monkeypatch.setattr(
        database,
        "get_provider_instance",
        AsyncMock(
            return_value={
                "instance_id": "earnapp-canary-1",
                "slug": "earnapp",
                "worker_id": 3,
                "proxy_id": 12,
                "container_id": "existing-container",
                "status": "running",
            }
        ),
    )

    result = await earnapp_canary.deploy_canary(
        "earnapp-canary-1",
        3,
        worker_deploy=deploy,
        worker_remove=remove,
    )

    assert result["status"] == "already_deployed"
    assert result["container_id"] == "existing-container"
    deploy.assert_not_awaited()
    remove.assert_not_awaited()


def test_provision_canary_reuses_existing_node_and_never_worker_assignment():
    async def run():
        with (
            patch.object(
                database,
                "get_earnapp_logical_node",
                AsyncMock(side_effect=[None, {"current_proxy_id": 12}]),
            ),
            patch.object(
                earnapp_canary.earnapp_recovery,
                "provision_node",
                AsyncMock(
                    return_value={
                        "logical_node_id": "earnapp-canary-1",
                        "account_id": 7,
                        "worker_id": 3,
                        "device_id": "sdk-mac-test",
                        "proxy_id": 12,
                        "generation": 1,
                        "state": "ACTIVE",
                    }
                ),
            ),
            patch.object(database, "get_worker_proxy_assignment", AsyncMock(return_value=None)),
        ):
            first = await earnapp_canary.provision_canary("earnapp-canary-1", 3, "sdk-mac-test")
            second = await earnapp_canary.provision_canary("earnapp-canary-1", 3, "sdk-mac-test")
            assert second["proxy_id"] == first["proxy_id"]
            assert await database.get_worker_proxy_assignment(3) is None

    asyncio.run(run())


@pytest.mark.asyncio
async def test_verify_canary_uses_the_bound_account_proxy_and_returns_only_sanitized_evidence(monkeypatch):
    collector = AsyncMock(
        return_value={
            "status": "online",
            "device_id": "sdk-mac-test",
            "authenticated": True,
            "link_attempted": True,
            "device_present": True,
            "online": True,
            "banned": False,
        }
    )
    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(
            return_value={
                "logical_node_id": "earnapp-canary-1",
                "account_id": 7,
                "assigned_worker_id": 3,
                "device_id": "sdk-mac-test",
                "current_proxy_id": 12,
                "generation": 1,
                "state": "ACTIVE",
            }
        ),
    )
    monkeypatch.setattr(
        database,
        "get_earnapp_account_credentials",
        AsyncMock(
            return_value={
                "id": 7,
                "state": "ACTIVE",
                "credentials": {
                    "cookies": {
                        "oauth-refresh-token": "refresh-secret",
                        "xsrf-token": "xsrf-secret",
                    }
                },
            }
        ),
    )
    monkeypatch.setattr(
        database,
        "get_earnapp_account_node_routes",
        AsyncMock(
            return_value=[
                {
                    "logical_node_id": "earnapp-canary-1",
                    "proxy_id": 12,
                    "protocol": "socks5",
                    "host": "proxy.example",
                    "port": 1080,
                    "username": "proxy-user",
                    "password": "proxy-secret",
                }
            ]
        ),
    )
    with patch("app.earnapp_canary.EarnAppAccountCollector") as collector_type:
        collector_type.return_value.link_and_verify_device = collector
        result = await earnapp_canary.verify_canary("earnapp-canary-1", attempts=1)

    assert result["status"] == "online"
    assert result["online"] is True
    serialized = json.dumps(result, sort_keys=True)
    assert "refresh-secret" not in serialized
    assert "xsrf-secret" not in serialized
    assert "proxy-secret" not in serialized
    collector_type.assert_called_once()
    collector.assert_awaited_once_with("sdk-mac-test", platform="macos")


@pytest.mark.asyncio
async def test_canary_deploy_route_is_owner_only_and_calls_deploy_then_verify(monkeypatch):
    routes = {route.path for route in main.app.routes}
    assert "/api/admin/earnapp/canary/deploy" in routes
    assert "/api/admin/earnapp/canary/{logical_node_id}/verify" in routes

    deploy = AsyncMock(
        return_value={
            "status": "deployed",
            "logical_node_id": "earnapp-canary-1",
            "account_id": 7,
            "worker_id": 3,
            "device_id": "sdk-mac-test",
            "proxy_id": 12,
            "generation": 1,
            "container_id": "container-id",
        }
    )
    verify = AsyncMock(return_value={"status": "online", "device_id": "sdk-mac-test", "online": True})
    monkeypatch.setattr(main, "_resolve_worker_id", AsyncMock(return_value=3))
    monkeypatch.setattr(earnapp_canary, "deploy_canary", deploy)
    monkeypatch.setattr(earnapp_canary, "verify_canary", verify)
    monkeypatch.setattr(database, "record_health_event", AsyncMock())

    result = await main.api_deploy_earnapp_canary(
        _request("/api/admin/earnapp/canary/deploy"),
        main.EarnAppCanaryDeployRequest(logical_node_id="earnapp-canary-1", worker_id=3),
        _auth={"r": "owner"},
    )

    assert result["status"] == "online"
    assert result["deployment"]["container_id"] == "container-id"
    deploy.assert_awaited_once()
    verify.assert_awaited_once_with("earnapp-canary-1")


@pytest.mark.asyncio
async def test_runtime_asset_request_uses_the_logical_node_asset_id(monkeypatch):
    monkeypatch.setattr(main, "_require_confirmed_worker", AsyncMock())
    monkeypatch.setattr(
        database,
        "get_worker_by_client_id",
        AsyncMock(return_value={"id": 3, "client_id": "worker-a"}),
    )
    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(
            return_value={
                "logical_node_id": "earnapp-canary-1",
                "assigned_worker_id": 3,
                "state": "ACTIVE",
            }
        ),
    )
    fetch = AsyncMock(return_value={"device_id": "sdk-mac-test", "value": "encrypted-profile"})
    monkeypatch.setattr(database, "get_earnapp_mac_profile", fetch)

    result = await main.api_worker_runtime_asset(
        _request("/api/workers/runtime-asset"),
        main.RuntimeAssetRequest(
            client_id="worker-a",
            provider="earnapp",
            asset_kind="mac_identity_profile",
            asset_id="earnapp-canary-1",
        ),
    )

    assert result == {
        "provider": "earnapp",
        "asset_kind": "mac_identity_profile",
        "value": "encrypted-profile",
    }
    fetch.assert_awaited_once_with("earnapp-canary-1")


@pytest.mark.asyncio
async def test_runtime_asset_request_rejects_worker_that_does_not_own_logical_node(monkeypatch):
    monkeypatch.setattr(main, "_require_confirmed_worker", AsyncMock())
    monkeypatch.setattr(
        database,
        "get_worker_by_client_id",
        AsyncMock(return_value={"id": 3, "client_id": "worker-a"}),
    )
    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(
            return_value={
                "logical_node_id": "earnapp-canary-1",
                "assigned_worker_id": 4,
                "state": "ACTIVE",
            }
        ),
    )

    with pytest.raises(HTTPException) as exc:
        await main.api_worker_runtime_asset(
            _request("/api/workers/runtime-asset"),
            main.RuntimeAssetRequest(
                client_id="worker-a",
                provider="earnapp",
                asset_kind="mac_identity_profile",
                asset_id="earnapp-canary-1",
            ),
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_worker_remove_cleans_only_the_matching_earnapp_heartbeat_state(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    worker_api._save_earnapp_state("earnapp-canary-1", {"generation": 1})
    worker_api._save_earnapp_state("earnapp-canary-2", {"generation": 1})

    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(worker_api.orchestrator, "remove_service", return_value={"volumes_removed": []}),
    ):
        result = await worker_api.api_remove_container(
            _request("/api/containers/earnapp-canary-1"),
            "earnapp-canary-1",
        )

    assert result["status"] == "removed"
    assert not worker_api._earnapp_state_path("earnapp-canary-1").exists()
    assert worker_api._earnapp_state_path("earnapp-canary-2").exists()
