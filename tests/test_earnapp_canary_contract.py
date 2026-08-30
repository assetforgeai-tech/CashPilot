from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException
from starlette.requests import Request

from app import (
    catalog,
    database,
    earnapp_canary,
    earnapp_deploy,
    earnapp_identity,
    earnapp_runtime,
    main,
    provider_runtime,
    singbox_config,
    worker_api,
)
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
    assert service["docker"]["image"] == earnapp_runtime.MAC_RUNTIME_IMAGE
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
    assert spec["image_delivery"] == "operator_preload"


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


def test_server_profile_routes_mac_lan_ip_through_sidecar_tun(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            profile = await earnapp_canary.get_or_create_mac_identity_profile("earnapp-canary-1")

        identity = earnapp_runtime.decrypt_mac_profile(profile["value"])
        config = singbox_config.render_tun_proxy_config(
            {"host": "proxy.example", "port": 1080, "protocol": "socks5"},
            worker_name="earnapp-canary-1",
        )
        tun_ip = config["inbounds"][0]["address"][0].split("/", 1)[0]
        assert identity["lan_ip"] == tun_ip

    asyncio.run(run())


def test_existing_profile_with_wrong_tun_lan_ip_fails_closed_without_rewrite(tmp_path):
    async def run():
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "earnapp.db"):
            await database.init_db()
            original = earnapp_canary._identity_value("earnapp-canary-1")
            original["lan_ip"] = "192.168.64.2"
            device_id = (
                earnapp_runtime.MAC_DEVICE_PREFIX
                + hashlib.sha256((str(original["id"]) + str(original["serial"])).encode("utf-8")).hexdigest()[:32]
            )
            await database.save_earnapp_mac_profile(
                "earnapp-canary-1",
                device_id=device_id,
                value=earnapp_runtime.encrypt_mac_profile(original),
            )
            before = await database.get_earnapp_identity_profile("earnapp-canary-1")
            with pytest.raises(ValueError, match="lan_ip"):
                await earnapp_canary.get_or_create_mac_identity_profile("earnapp-canary-1")
            after = await database.get_earnapp_identity_profile("earnapp-canary-1")

        assert after["device_id"] == device_id
        assert after["value"] == before["value"]

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
    assert "ubuntu lxd" in str(exc.value.detail).lower()
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
        "4a1e80cbb95da585c8e902fb2f0f118b634d51ee62b92454862e9457797b6f43"
    )
    assert earnapp_runtime.runtime_asset_manifest_sha256() == earnapp_runtime.MAC_RUNTIME_ASSET_MANIFEST_SHA256


def test_canary_image_build_recipe_validates_artifacts_and_emits_pinned_labels(tmp_path):
    source = tmp_path / "mac"
    source.mkdir()
    expected = {}
    for name in earnapp_runtime.MAC_RUNTIME_ARTIFACT_HASHES:
        content = '[[ ! -s "$STATE_DIR/registered" || ! -x /usr/bin/earnapp ]]' if name == "entrypoint.sh" else name
        payload = (content + "\n").encode()
        (source / name).write_bytes(payload)
        expected[name] = hashlib.sha256(payload).hexdigest()

    manifest = build_earnapp_canary_image.validate_artifacts(source, expected)
    assert manifest == earnapp_runtime.runtime_asset_manifest(expected)
    recipe = build_earnapp_canary_image.render_dockerfile(manifest)
    manifest_hash = earnapp_runtime.runtime_asset_manifest_sha256(expected)
    assert f"com.cashpilot.earnapp.assets-sha256={manifest_hash}" in recipe
    assert 'ENTRYPOINT ["/usr/local/bin/earn-supervisor"]' in recipe


@pytest.mark.parametrize(
    ("platform", "wrong_marker"),
    [
        ("macos", '[[ ! -f "$STATE_DIR/uuid" || ! -x /usr/bin/earnapp ]]'),
        ("ios", '[[ ! -s "$STATE_DIR/registered" || ! -x /usr/bin/earnapp ]]'),
    ],
)
def test_image_builder_rejects_entrypoint_with_the_other_platform_install_marker(tmp_path, platform, wrong_marker):
    source = tmp_path / platform
    source.mkdir()
    artifact_names = (
        earnapp_runtime.MAC_RUNTIME_ARTIFACT_HASHES
        if platform == "macos"
        else earnapp_runtime.IOS_RUNTIME_ARTIFACT_HASHES
    )
    expected = {}
    for name in artifact_names:
        payload = (wrong_marker if name == "entrypoint.sh" else name).encode()
        (source / name).write_bytes(payload)
        expected[name] = hashlib.sha256(payload).hexdigest()

    with pytest.raises(ValueError, match="install marker"):
        build_earnapp_canary_image.validate_artifacts(source, expected, platform=platform)


def test_ios_runtime_manifest_is_content_addressed_from_the_forensic_bundle():
    assert earnapp_runtime.IOS_RUNTIME_ARTIFACT_HASHES == {
        "boot.js": "5de4b51eecdaf4b8b01bd5a2cafd019c701f877b9add727f405d6409f0c1793d",
        "earn-supervisor": "170c39c7821b7fd6110b96242b703fd6a0541dee29cf6c4525c3a70b67d42a25",
        "earnapp-bootstrap": "be9c4f6865134c87dbae373304e4b20bc55e91f60d2744ac03ebb864ca7fc2ee",
        "entrypoint.sh": "50b32e6f7280da75a7568cd25b6e4e43797f254517b1ee316f5b359f24e4144e",
    }
    digest = earnapp_runtime.runtime_asset_manifest_sha256(platform="ios")
    assert earnapp_runtime.runtime_image("ios") == f"cashpilot/earnapp-ios:asset-{digest[:12]}"
    labels = earnapp_runtime.required_image_labels("ios")
    assert labels["com.cashpilot.earnapp.platform"] == "ios"
    assert labels["com.cashpilot.earnapp.appid"] == "com.brd.earnapp"
    assert labels["com.cashpilot.earnapp.device-prefix"] == "sdk-ios-"


def test_ios_runtime_separates_profile_appid_from_install_control_plane_appid():
    assert earnapp_runtime.IOS_APPID == "com.brd.earnapp"
    assert earnapp_runtime.IOS_INSTALL_APPID == "ios_com.brd.earnapp"
    assert earnapp_runtime.IOS_INSTALL_APPID != earnapp_runtime.IOS_APPID


def test_audited_runtime_artifacts_only_override_machine_architecture_queries():
    configured = str(os.environ.get("CASHPILOT_EARNAPP_AUDIT_ROOT") or "").strip()
    root = (
        Path(configured)
        if configured
        else Path(__file__).resolve().parents[2] / "earnapp_new_update" / "earnapp-runtime-small"
    )
    if not root.is_dir():
        pytest.skip("external EarnApp forensic bundle is not available on this runner")

    for platform in ("mac", "ios"):
        uname = (root / platform / "uname").read_text(encoding="utf-8")
        entrypoint = (root / platform / "entrypoint.sh").read_text(encoding="utf-8")
        assert "-m|-p|-i" in uname
        assert '*) exec /bin/uname "$@"' in uname
        assert "rm -f /.dockerenv" in entrypoint
        assert "systemd-detect-virt" not in entrypoint
        assert "/proc/1/cgroup" not in entrypoint


def test_ios_image_builder_uses_the_ios_bundle_and_verified_runtime_contract(tmp_path):
    source = tmp_path / "ios"
    source.mkdir()
    expected = {}
    for name in ("boot.js", "earn-supervisor", "earnapp-bootstrap", "entrypoint.sh"):
        content = '[[ ! -f "$STATE_DIR/uuid" || ! -x /usr/bin/earnapp ]]' if name == "entrypoint.sh" else "ios-" + name
        payload = (content + "\n").encode()
        (source / name).write_bytes(payload)
        expected[name] = hashlib.sha256(payload).hexdigest()

    manifest = build_earnapp_canary_image.validate_artifacts(source, expected, platform="ios")
    recipe = build_earnapp_canary_image.render_dockerfile(manifest, platform="ios")
    digest = earnapp_runtime.runtime_asset_manifest_sha256(expected, platform="ios")

    assert "COPY earnapp-bootstrap /opt/earnapp-ios" in recipe
    assert "com.cashpilot.earnapp.runtime=earnapp_ios" in recipe
    assert "com.cashpilot.earnapp.platform=ios" in recipe
    assert "com.cashpilot.earnapp.appid=com.brd.earnapp" in recipe
    assert f"com.cashpilot.earnapp.assets-sha256={digest}" in recipe
    assert build_earnapp_canary_image.image_reference(digest, platform="ios").startswith("cashpilot/earnapp-ios:asset-")


def test_ios_image_builder_installs_idempotent_control_plane_registration_wrapper(tmp_path):
    source = tmp_path / "ios"
    source.mkdir()
    expected = {}
    for name in ("boot.js", "earn-supervisor", "earnapp-bootstrap", "entrypoint.sh"):
        content = '[[ ! -f "$STATE_DIR/uuid" || ! -x /usr/bin/earnapp ]]' if name == "entrypoint.sh" else "ios-" + name
        payload = (content + "\n").encode()
        (source / name).write_bytes(payload)
        expected[name] = hashlib.sha256(payload).hexdigest()

    manifest = build_earnapp_canary_image.validate_artifacts(source, expected, platform="ios")
    recipe = build_earnapp_canary_image.render_dockerfile(manifest, platform="ios")

    assert "COPY ios-register-device /usr/local/bin/ios-register-device" in recipe
    assert (
        "RUN chmod 0755 /opt/earnapp-ios /usr/local/bin/earn-supervisor "
        "/usr/local/bin/entrypoint.sh /usr/local/bin/entrypoint-original.sh "
        "/usr/local/bin/ios-register-device"
    ) in recipe
    assert (
        "bash -n /usr/local/bin/earn-supervisor /usr/local/bin/entrypoint.sh "
        "/usr/local/bin/entrypoint-original.sh /usr/local/bin/ios-register-device"
    ) in recipe
    wrapper = build_earnapp_canary_image.render_ios_registration_wrapper()
    assert "APPID=ios_com.brd.earnapp" in wrapper
    assert "appid=com.brd.earnapp" not in wrapper
    assert 'MARKER="$STATE_DIR/registered-ios-control-plane"' in wrapper
    assert 'test "$(cat "$MARKER")" = "$FINGERPRINT"' in wrapper
    assert "install_device" in wrapper
    assert "is_linked" in wrapper
    assert 'mv -f "$TEMP_MARKER" "$MARKER"' in wrapper


def test_ios_registration_uses_query_parameters_json_body_and_validated_responses():
    wrapper = build_earnapp_canary_image.render_ios_registration_wrapper()

    assert 'require("node:' not in wrapper
    assert "REGISTER_URL=$(node -e" in wrapper
    assert 'searchParams.set("appid", "ios_com.brd.earnapp")' in wrapper
    assert "REGISTER_BODY=$(node -e" in wrapper
    assert "JSON.stringify({serial: process.argv[1]})" in wrapper
    assert '--data-binary "$REGISTER_BODY"' in wrapper
    assert "--get 'https://client.earnapp.com/install_device'" not in wrapper
    assert "body.ok !== 1" in wrapper
    assert 'typeof body.linked !== "boolean"' in wrapper


def test_ios_registration_fails_closed_unless_sidecar_egress_matches_the_lease():
    wrapper = build_earnapp_canary_image.render_ios_registration_wrapper()

    assert 'EXPECTED_EGRESS_IP="${EARNAPP_EXPECTED_EGRESS_IP:-}"' in wrapper
    assert "format=json" in wrapper
    assert '[[ "$OBSERVED_EGRESS_IP" == "$EXPECTED_EGRESS_IP" ]]' in wrapper
    assert wrapper.index("format=json") < wrapper.index("install_device")


def test_ios_generated_entrypoint_runs_registration_after_profile_boot_before_runtime():
    startup = earnapp_runtime.ios_entrypoint_script().decode("utf-8")

    assert "/usr/local/bin/ios-register-device" in startup
    assert 'exec /usr/local/bin/entrypoint-original.sh "$@"' in startup


def test_ios_manifest_hash_covers_every_generated_runtime_script():
    generated = earnapp_runtime.generated_runtime_artifacts("ios")
    manifest = earnapp_runtime.runtime_asset_manifest(platform="ios")
    hashes = build_earnapp_canary_image.manifest_hashes(manifest)

    assert set(generated) == {"ios-entrypoint", "ios-register-device"}
    for path, payload in generated.items():
        assert hashes[path] == hashlib.sha256(payload).hexdigest()


def test_non_ios_runtime_paths_do_not_install_or_invoke_ios_registration():
    manifest = earnapp_runtime.runtime_asset_manifest(platform="macos")
    recipe = build_earnapp_canary_image.render_dockerfile(manifest, platform="macos")

    assert earnapp_runtime.generated_runtime_artifacts("macos") == {}
    assert "ios-register-device" not in recipe
    assert "ios-entrypoint" not in recipe
    assert "entrypoint-original.sh" not in recipe
    assert "COPY entrypoint.sh /usr/local/bin/entrypoint.sh" in recipe


def test_ios_runtime_spec_is_account_scoped_hardened_and_uses_the_persisted_profile():
    identity = earnapp_identity.generate_identity("earnapp-ios-1", "ios")
    spec = earnapp_canary.build_runtime_spec(
        logical_node_id="earnapp-ios-1",
        account_id=7,
        platform="ios",
        device_id=identity["device_id"],
        proxy={
            "proxy_id": 12,
            "host": "proxy.example",
            "port": 1080,
            "protocol": "socks5",
            "exit_ip": "203.0.113.10",
            "country_code": "VN",
            "ip_type": "residential",
        },
        generation=4,
    )

    assert spec["image"] == earnapp_runtime.runtime_image("ios")
    assert spec["host_runtime"] == "earnapp_ios"
    assert spec["image_delivery"] == "operator_preload"
    assert spec["runtime_assets"] == [
        {
            "provider": "earnapp",
            "asset_kind": "ios_identity_profile",
            "asset_id": "earnapp-ios-1",
            "target": "/etc/earnapp-spoof/profile.json.enc",
            "encoding": "base64",
        }
    ]
    assert spec["labels"]["cashpilot.earnapp.platform"] == "ios"
    assert spec["labels"]["cashpilot.earnapp.generation"] == "4"
    assert spec["env"]["EARNAPP_EXPECTED_EGRESS_IP"] == "203.0.113.10"
    assert spec["privileged"] is False
    assert spec["cap_add"] is None
    assert spec["devices"] is None
    earnapp_runtime.validate_runtime_spec(spec)


def test_ios_runtime_spec_requires_authoritative_proxy_egress_for_registration():
    identity = earnapp_identity.generate_identity("earnapp-ios-egress", "ios")
    spec = earnapp_canary.build_runtime_spec(
        logical_node_id="earnapp-ios-egress",
        account_id=7,
        platform="ios",
        device_id=identity["device_id"],
        proxy={"proxy_id": 12, "exit_ip": "203.0.113.10"},
    )
    spec["env"].pop("EARNAPP_EXPECTED_EGRESS_IP")

    with pytest.raises(ValueError, match="egress"):
        earnapp_runtime.validate_runtime_spec(spec)


@pytest.mark.parametrize(
    ("proxy_patch", "message"),
    [
        ({"host": ""}, "proxy"),
        ({"port": 0}, "proxy"),
        ({"protocol": "https"}, "protocol"),
        ({"country_code": "US"}, "VN residential"),
        ({"ip_type": "datacenter"}, "VN residential"),
        ({"exit_ip": ""}, "egress"),
    ],
)
def test_worker_boundary_rejects_ios_proxy_outside_authoritative_vn_residential_contract(
    proxy_patch,
    message,
):
    identity = earnapp_identity.generate_identity("earnapp-ios-worker-boundary", "ios")
    proxy = {
        "proxy_id": 12,
        "host": "proxy.example",
        "port": 1080,
        "protocol": "socks5",
        "exit_ip": "203.0.113.10",
        "country_code": "VN",
        "ip_type": "residential",
    }
    spec = earnapp_canary.build_runtime_spec(
        logical_node_id="earnapp-ios-worker-boundary",
        account_id=7,
        platform="ios",
        device_id=identity["device_id"],
        proxy=proxy,
    )
    spec["proxy"].update(proxy_patch)

    with pytest.raises(ValueError, match=message):
        earnapp_runtime.validate_runtime_spec(spec)


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

    remove.assert_awaited_once_with(3, "earnapp-canary-1", 4, "sdk-mac-test")
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

    remove.assert_awaited_once_with(3, "earnapp-canary-1", 4, "sdk-mac-test")
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
            ) as provision,
            patch.object(database, "get_worker_proxy_assignment", AsyncMock(return_value=None)),
        ):
            first = await earnapp_canary.provision_canary("earnapp-canary-1", 3, "sdk-mac-test")
            second = await earnapp_canary.provision_canary("earnapp-canary-1", 3, "sdk-mac-test")
            assert second["proxy_id"] == first["proxy_id"]
            provision.assert_awaited_with(
                "earnapp-canary-1",
                3,
                device_id="sdk-mac-test",
                proxy_country_code="VN",
                platform="macos",
            )
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

    assert result["status"] == "online_pending_usage"
    assert result["workload_state"] == "online_pending_usage"
    assert result["online"] is True
    serialized = json.dumps(result, sort_keys=True)
    assert "refresh-secret" not in serialized
    assert "xsrf-secret" not in serialized
    assert "proxy-secret" not in serialized
    collector_type.assert_called_once()
    collector.assert_awaited_once_with("sdk-mac-test", platform="macos")


@pytest.mark.asyncio
async def test_verify_canary_stops_remote_link_error_for_macos(monkeypatch):
    collector = AsyncMock(
        return_value={
            "status": "error",
            "error_kind": "remote",
            "error": "device registration rejected",
        }
    )
    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(
            return_value={
                "logical_node_id": "earnapp-canary-1",
                "account_id": 7,
                "device_id": "sdk-mac-test",
                "current_proxy_id": 12,
                "state": "ACTIVE",
            }
        ),
    )
    monkeypatch.setattr(
        database,
        "get_earnapp_account_credentials",
        AsyncMock(return_value={"id": 7, "state": "ACTIVE", "credentials": {}}),
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
                }
            ]
        ),
    )
    with patch("app.earnapp_canary.EarnAppAccountCollector") as collector_type:
        collector_type.return_value.link_and_verify_device = collector
        result = await earnapp_canary.verify_canary("earnapp-canary-1", attempts=3, interval_seconds=0)

    assert result["status"] == "error"
    assert result["error_kind"] == "remote"
    collector.assert_awaited_once_with("sdk-mac-test", platform="macos")


@pytest.mark.asyncio
async def test_verify_canary_retries_remote_link_error_until_attempt_budget_for_ubuntu(monkeypatch):
    collector = AsyncMock(
        return_value={
            "status": "error",
            "error_kind": "remote",
            "error": "device registration rejected",
        }
    )
    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(
            return_value={
                "logical_node_id": "earnapp-ubuntu-canary-1",
                "account_id": 7,
                "device_id": "sdk-node-" + "a" * 32,
                "platform": "ubuntu",
                "current_proxy_id": 12,
                "state": "ACTIVE",
            }
        ),
    )
    monkeypatch.setattr(
        database,
        "get_earnapp_account_credentials",
        AsyncMock(return_value={"id": 7, "state": "ACTIVE", "credentials": {}}),
    )
    monkeypatch.setattr(
        database,
        "get_earnapp_account_node_routes",
        AsyncMock(
            return_value=[
                {
                    "logical_node_id": "earnapp-ubuntu-canary-1",
                    "proxy_id": 12,
                    "protocol": "socks5",
                    "host": "proxy.example",
                    "port": 1080,
                }
            ]
        ),
    )
    with patch("app.earnapp_canary.EarnAppAccountCollector") as collector_type:
        collector_type.return_value.link_and_verify_device = collector
        result = await earnapp_canary.verify_canary("earnapp-ubuntu-canary-1", attempts=3, interval_seconds=0)

    assert result["status"] == "error"
    assert result["error_kind"] == "remote"
    assert collector.await_count == 3
    assert all(
        call == (("sdk-node-" + "a" * 32,), {"platform": "ubuntu"})
        for call in collector.await_args_list
    )


@pytest.mark.asyncio
async def test_verify_canary_retries_remote_link_error_until_exact_device_is_online(monkeypatch):
    collector = AsyncMock(
        side_effect=[
            {
                "status": "error",
                "error_kind": "remote",
                "error": "device registration is still pending",
            },
            {
                "status": "online",
                "device_id": "sdk-node-" + "a" * 32,
                "authenticated": True,
                "link_attempted": True,
                "device_present": True,
                "online": True,
                "banned": False,
                "billing": "bandwidth",
                "bandwidth": 100,
                "total_bandwidth": 100,
                "earned_total": 0,
            },
            {
                "status": "online",
                "device_id": "sdk-node-" + "a" * 32,
                "authenticated": True,
                "link_attempted": True,
                "device_present": True,
                "online": True,
                "banned": False,
                "billing": "bandwidth",
                "bandwidth": 140,
                "total_bandwidth": 140,
                "earned_total": 0,
            },
        ]
    )
    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(
            return_value={
                "logical_node_id": "earnapp-ubuntu-canary-1",
                "account_id": 7,
                "device_id": "sdk-node-" + "a" * 32,
                "platform": "ubuntu",
                "current_proxy_id": 12,
                "state": "ACTIVE",
            }
        ),
    )
    monkeypatch.setattr(
        database,
        "get_earnapp_account_credentials",
        AsyncMock(return_value={"id": 7, "state": "ACTIVE", "credentials": {}}),
    )
    monkeypatch.setattr(
        database,
        "get_earnapp_account_node_routes",
        AsyncMock(
            return_value=[
                {
                    "logical_node_id": "earnapp-ubuntu-canary-1",
                    "proxy_id": 12,
                    "protocol": "socks5",
                    "host": "proxy.example",
                    "port": 1080,
                }
            ]
        ),
    )
    with patch("app.earnapp_canary.EarnAppAccountCollector") as collector_type:
        collector_type.return_value.link_and_verify_device = collector
        result = await earnapp_canary.verify_canary(
            "earnapp-ubuntu-canary-1", attempts=3, interval_seconds=0
        )

    assert result["status"] == "workload_verified"
    assert result["workload_state"] == "workload_verified"
    assert result["device_id"] == "sdk-node-" + "a" * 32
    assert result["workload_delta"]["bandwidth"] == 40.0
    assert collector.await_count == 3


@pytest.mark.asyncio
async def test_verify_canary_rejects_online_evidence_for_stale_device_uuid(monkeypatch):
    stale_device_id = "sdk-node-" + "b" * 32
    expected_device_id = "sdk-node-" + "a" * 32
    collector = AsyncMock(
        return_value={
            "status": "online",
            "device_id": stale_device_id,
            "authenticated": True,
            "link_attempted": True,
            "device_present": True,
            "online": True,
            "banned": False,
            "billing": "bandwidth",
            "bandwidth": 999,
            "total_bandwidth": 999,
            "earned_total": 0,
        }
    )
    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(
            return_value={
                "logical_node_id": "earnapp-ubuntu-canary-stale",
                "account_id": 7,
                "device_id": expected_device_id,
                "platform": "ubuntu",
                "current_proxy_id": 12,
                "state": "ACTIVE",
            }
        ),
    )
    monkeypatch.setattr(
        database,
        "get_earnapp_account_credentials",
        AsyncMock(return_value={"id": 7, "state": "ACTIVE", "credentials": {}}),
    )
    monkeypatch.setattr(
        database,
        "get_earnapp_account_node_routes",
        AsyncMock(
            return_value=[
                {
                    "logical_node_id": "earnapp-ubuntu-canary-stale",
                    "proxy_id": 12,
                    "protocol": "socks5",
                    "host": "proxy.example",
                    "port": 1080,
                }
            ]
        ),
    )
    with patch("app.earnapp_canary.EarnAppAccountCollector") as collector_type:
        collector_type.return_value.link_and_verify_device = collector
        result = await earnapp_canary.verify_canary(
            "earnapp-ubuntu-canary-stale", attempts=2, interval_seconds=0
        )

    assert result["status"] == "error"
    assert result["error_kind"] == "identity"
    assert result["device_id"] == expected_device_id
    assert result["observed_device_id"] == stale_device_id
    assert result["online"] is False
    assert collector.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored_platform", "device_id", "wire_platform"),
    [("ios", "sdk-ios-test", "ios"), ("ubuntu", "sdk-node-" + "a" * 32, "ubuntu")],
)
async def test_verify_canary_uses_the_persisted_node_platform(monkeypatch, stored_platform, device_id, wire_platform):
    collector = AsyncMock(return_value={"status": "online", "device_present": True, "online": True, "banned": False})
    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(
            return_value={
                "logical_node_id": "earnapp-node-1",
                "account_id": 7,
                "device_id": device_id,
                "platform": stored_platform,
                "current_proxy_id": 12,
                "state": "ACTIVE",
            }
        ),
    )
    monkeypatch.setattr(
        database,
        "get_earnapp_account_credentials",
        AsyncMock(return_value={"id": 7, "state": "ACTIVE", "credentials": {}}),
    )
    monkeypatch.setattr(
        database,
        "get_earnapp_account_node_routes",
        AsyncMock(
            return_value=[
                {"logical_node_id": "earnapp-node-1", "proxy_id": 12, "host": "proxy", "port": 1, "protocol": "http"}
            ]
        ),
    )
    with patch("app.earnapp_canary.EarnAppAccountCollector") as collector_type:
        collector_type.return_value.link_and_verify_device = collector
        result = await earnapp_canary.verify_canary("earnapp-node-1", attempts=1)

    assert result["online"] is True
    collector.assert_awaited_once_with(device_id, platform=wire_platform)


def test_verify_canary_requires_a_positive_usage_or_earnings_delta_between_samples(monkeypatch):
    async def run():
        collector = AsyncMock(
            side_effect=[
                {
                    "status": "online",
                    "device_id": "sdk-mac-test",
                    "authenticated": True,
                    "device_present": True,
                    "online": True,
                    "banned": False,
                    "billing": "bandwidth",
                    "bandwidth": 1000,
                    "total_bandwidth": 5000,
                    "earned_total": 0.0,
                },
                {
                    "status": "online",
                    "device_id": "sdk-mac-test",
                    "authenticated": True,
                    "device_present": True,
                    "online": True,
                    "banned": False,
                    "billing": "bandwidth",
                    "bandwidth": 1600,
                    "total_bandwidth": 5600,
                    "earned_total": 0.0,
                },
            ]
        )
        monkeypatch.setattr(
            database,
            "get_earnapp_logical_node",
            AsyncMock(
                return_value={
                    "logical_node_id": "earnapp-canary-1",
                    "account_id": 7,
                    "device_id": "sdk-mac-test",
                    "platform": "macos",
                    "current_proxy_id": 12,
                    "state": "ACTIVE",
                }
            ),
        )
        monkeypatch.setattr(
            database,
            "get_earnapp_account_credentials",
            AsyncMock(return_value={"id": 7, "state": "ACTIVE", "credentials": {}}),
        )
        monkeypatch.setattr(
            database,
            "get_earnapp_account_node_routes",
            AsyncMock(
                return_value=[
                    {
                        "logical_node_id": "earnapp-canary-1",
                        "proxy_id": 12,
                        "host": "proxy",
                        "port": 1,
                        "protocol": "http",
                    }
                ]
            ),
        )
        with patch("app.earnapp_canary.EarnAppAccountCollector") as collector_type:
            collector_type.return_value.link_and_verify_device = collector
            result = await earnapp_canary.verify_canary("earnapp-canary-1", attempts=2, interval_seconds=0)

        assert result["status"] == "workload_verified"
        assert result["workload_state"] == "workload_verified"
        assert result["workload_delta"] == {
            "bandwidth": 600.0,
            "total_bandwidth": 600.0,
            "earned_total": 0.0,
        }
        assert collector.await_count == 2

    asyncio.run(run())


def test_verify_canary_accepts_any_positive_qualified_uptime_delta_within_poll_window(monkeypatch):
    samples = [
        {
            "status": "online",
            "authenticated": True,
            "device_present": True,
            "online": True,
            "banned": False,
            "device_id": "sdk-mac-" + "a" * 32,
            "billing": "qualified_uptime",
            "total_uptime": 1000,
            "bandwidth": 0,
            "total_bandwidth": 0,
            "earned_total": 0,
        },
        {
            "status": "online",
            "authenticated": True,
            "device_present": True,
            "online": True,
            "banned": False,
            "device_id": "sdk-mac-" + "a" * 32,
            "billing": "qualified_uptime",
            "total_uptime": 1600,
            "bandwidth": 0,
            "total_bandwidth": 0,
            "earned_total": 0,
        },
    ]

    class Collector:
        async def link_and_verify_device(self, *_args, **_kwargs):
            return samples.pop(0)

    with (
        patch.object(
            database,
            "get_earnapp_logical_node",
            AsyncMock(
                return_value={
                    "state": "ACTIVE",
                    "account_id": 1,
                    "current_proxy_id": 12,
                    "device_id": "sdk-mac-" + "a" * 32,
                    "platform": "macos",
                }
            ),
        ),
        patch.object(
            database,
            "get_earnapp_account_credentials",
            AsyncMock(
                return_value={
                    "state": "ACTIVE",
                    "credentials": {},
                }
            ),
        ),
        patch.object(
            database,
            "get_earnapp_account_node_routes",
            AsyncMock(
                return_value=[
                    {
                        "logical_node_id": "earnapp-node-1",
                        "proxy_id": 12,
                    }
                ]
            ),
        ),
        patch.object(earnapp_canary, "EarnAppAccountCollector", return_value=Collector()),
    ):
        result = asyncio.run(earnapp_canary.verify_canary("earnapp-node-1", attempts=2, interval_seconds=0))

    assert result["status"] == "workload_verified"
    assert result["workload_state"] == "workload_verified"
    assert result["workload_delta"]["total_uptime"] == 600.0


def test_verify_canary_keeps_flat_qualified_uptime_pending(monkeypatch):
    samples = [
        {
            "status": "online",
            "authenticated": True,
            "device_present": True,
            "online": True,
            "banned": False,
            "device_id": "sdk-mac-" + "c" * 32,
            "billing": "qualified_uptime",
            "total_uptime": 1000,
            "earned_total": 0,
        },
        {
            "status": "online",
            "authenticated": True,
            "device_present": True,
            "online": True,
            "banned": False,
            "device_id": "sdk-mac-" + "c" * 32,
            "billing": "qualified_uptime",
            "total_uptime": 1000,
            "earned_total": 0,
        },
    ]

    class Collector:
        async def link_and_verify_device(self, *_args, **_kwargs):
            return samples.pop(0)

    with (
        patch.object(
            database,
            "get_earnapp_logical_node",
            AsyncMock(
                return_value={
                    "state": "ACTIVE",
                    "account_id": 1,
                    "current_proxy_id": 12,
                    "device_id": "sdk-mac-" + "c" * 32,
                    "platform": "macos",
                }
            ),
        ),
        patch.object(
            database,
            "get_earnapp_account_credentials",
            AsyncMock(
                return_value={
                    "state": "ACTIVE",
                    "credentials": {},
                }
            ),
        ),
        patch.object(
            database,
            "get_earnapp_account_node_routes",
            AsyncMock(
                return_value=[
                    {
                        "logical_node_id": "earnapp-node-sustained",
                        "proxy_id": 12,
                    }
                ]
            ),
        ),
        patch.object(earnapp_canary, "EarnAppAccountCollector", return_value=Collector()),
    ):
        result = asyncio.run(earnapp_canary.verify_canary("earnapp-node-sustained", attempts=2, interval_seconds=0))

    assert result["status"] == "online_pending_usage"
    assert result["workload_state"] == "online_pending_usage"
    assert result["workload_reason"] == "awaiting_metric_delta"


def test_verify_canary_ignores_historical_usage_growth_when_current_workload_is_flat(monkeypatch):
    samples = [
        {
            "status": "online",
            "authenticated": True,
            "device_present": True,
            "online": True,
            "banned": False,
            "device_id": "sdk-mac-" + "e" * 32,
            "billing": "qualified_uptime",
            "uptime": 1000,
            "total_uptime": 1000,
            "usage_current": 1000,
            "usage_total": 5000,
            "earned_total": 0,
        },
        {
            "status": "online",
            "authenticated": True,
            "device_present": True,
            "online": True,
            "banned": False,
            "device_id": "sdk-mac-" + "e" * 32,
            "billing": "qualified_uptime",
            "uptime": 1000,
            "total_uptime": 1000,
            "usage_current": 1000,
            "usage_total": 9000,
            "earned_total": 0,
        },
    ]

    class Collector:
        async def link_and_verify_device(self, *_args, **_kwargs):
            return samples.pop(0)

    with (
        patch.object(
            database,
            "get_earnapp_logical_node",
            AsyncMock(
                return_value={
                    "state": "ACTIVE",
                    "account_id": 1,
                    "current_proxy_id": 12,
                    "device_id": "sdk-mac-" + "e" * 32,
                    "platform": "macos",
                }
            ),
        ),
        patch.object(
            database,
            "get_earnapp_account_credentials",
            AsyncMock(return_value={"state": "ACTIVE", "credentials": {}}),
        ),
        patch.object(
            database,
            "get_earnapp_account_node_routes",
            AsyncMock(return_value=[{"logical_node_id": "earnapp-node-history", "proxy_id": 12}]),
        ),
        patch.object(earnapp_canary, "EarnAppAccountCollector", return_value=Collector()),
    ):
        result = asyncio.run(earnapp_canary.verify_canary("earnapp-node-history", attempts=2, interval_seconds=0))

    assert result["workload_state"] == "online_pending_usage"
    assert result["workload_reason"] == "awaiting_metric_delta"


def test_verify_canary_accepts_positive_current_usage_when_legacy_bandwidth_counters_are_flat(monkeypatch):
    samples = [
        {
            "status": "online",
            "authenticated": True,
            "device_present": True,
            "online": True,
            "banned": False,
            "device_id": "sdk-ios-" + "f" * 32,
            "billing": "bandwidth",
            "bandwidth": 0,
            "total_bandwidth": 0,
            "usage_current": 100,
            "usage_total": 5000,
            "earned_total": 0,
        },
        {
            "status": "online",
            "authenticated": True,
            "device_present": True,
            "online": True,
            "banned": False,
            "device_id": "sdk-ios-" + "f" * 32,
            "billing": "bandwidth",
            "bandwidth": 0,
            "total_bandwidth": 0,
            "usage_current": 160,
            "usage_total": 5060,
            "earned_total": 0,
        },
    ]

    class Collector:
        async def link_and_verify_device(self, *_args, **_kwargs):
            return samples.pop(0)

    with (
        patch.object(
            database,
            "get_earnapp_logical_node",
            AsyncMock(
                return_value={
                    "state": "ACTIVE",
                    "account_id": 1,
                    "current_proxy_id": 12,
                    "device_id": "sdk-ios-" + "f" * 32,
                    "platform": "ios",
                }
            ),
        ),
        patch.object(
            database,
            "get_earnapp_account_credentials",
            AsyncMock(return_value={"state": "ACTIVE", "credentials": {}}),
        ),
        patch.object(
            database,
            "get_earnapp_account_node_routes",
            AsyncMock(return_value=[{"logical_node_id": "earnapp-node-current", "proxy_id": 12}]),
        ),
        patch.object(earnapp_canary, "EarnAppAccountCollector", return_value=Collector()),
    ):
        result = asyncio.run(earnapp_canary.verify_canary("earnapp-node-current", attempts=2, interval_seconds=0))

    assert result["workload_state"] == "workload_verified"
    assert result["workload_delta"]["usage_current"] == 60.0


def test_verify_canary_accepts_positive_current_usage_for_qualified_uptime(monkeypatch):
    samples = [
        {
            "status": "online",
            "authenticated": True,
            "device_present": True,
            "online": True,
            "banned": False,
            "device_id": "sdk-mac-" + "a" * 32,
            "billing": "qualified_uptime",
            "uptime": 1000,
            "total_uptime": 1000,
            "usage_current": 100,
            "usage_total": 5000,
            "earned_total": 0,
        },
        {
            "status": "online",
            "authenticated": True,
            "device_present": True,
            "online": True,
            "banned": False,
            "device_id": "sdk-mac-" + "a" * 32,
            "billing": "qualified_uptime",
            "uptime": 1000,
            "total_uptime": 1000,
            "usage_current": 160,
            "usage_total": 5060,
            "earned_total": 0,
        },
    ]

    class Collector:
        async def link_and_verify_device(self, *_args, **_kwargs):
            return samples.pop(0)

    with (
        patch.object(
            database,
            "get_earnapp_logical_node",
            AsyncMock(
                return_value={
                    "state": "ACTIVE",
                    "account_id": 1,
                    "current_proxy_id": 12,
                    "device_id": "sdk-mac-" + "a" * 32,
                    "platform": "macos",
                }
            ),
        ),
        patch.object(
            database,
            "get_earnapp_account_credentials",
            AsyncMock(return_value={"state": "ACTIVE", "credentials": {}}),
        ),
        patch.object(
            database,
            "get_earnapp_account_node_routes",
            AsyncMock(return_value=[{"logical_node_id": "earnapp-node-uptime-current", "proxy_id": 12}]),
        ),
        patch.object(earnapp_canary, "EarnAppAccountCollector", return_value=Collector()),
    ):
        result = asyncio.run(
            earnapp_canary.verify_canary("earnapp-node-uptime-current", attempts=2, interval_seconds=0)
        )

    assert result["workload_state"] == "workload_verified"
    assert result["workload_delta"]["usage_current"] == 60.0


def test_verify_canary_uses_persisted_pending_baseline_across_verify_calls(monkeypatch):
    sample = {
        "status": "online",
        "authenticated": True,
        "device_present": True,
        "online": True,
        "banned": False,
        "device_id": "sdk-mac-" + "d" * 32,
        "billing": "qualified_uptime",
        "total_uptime": 1600,
        "earned_total": 0,
    }

    class Collector:
        async def link_and_verify_device(self, *_args, **_kwargs):
            return sample

    with (
        patch.object(
            database,
            "get_earnapp_logical_node",
            AsyncMock(
                return_value={
                    "state": "ACTIVE",
                    "account_id": 1,
                    "current_proxy_id": 12,
                    "device_id": "sdk-mac-" + "d" * 32,
                    "platform": "macos",
                }
            ),
        ),
        patch.object(
            database,
            "get_earnapp_account_credentials",
            AsyncMock(
                return_value={
                    "state": "ACTIVE",
                    "credentials": {},
                }
            ),
        ),
        patch.object(
            database,
            "get_earnapp_account_node_routes",
            AsyncMock(
                return_value=[
                    {
                        "logical_node_id": "earnapp-node-persisted-baseline",
                        "proxy_id": 12,
                    }
                ]
            ),
        ),
        patch.object(
            database,
            "get_provider_instance_spec",
            AsyncMock(
                return_value={
                    "earnapp_device_verification": {
                        "device_id": "sdk-mac-" + "d" * 32,
                        "billing": "qualified_uptime",
                        "total_uptime": 1000,
                        "earned_total": 0,
                        "workload_state": "online_pending_usage",
                    },
                }
            ),
        ),
        patch.object(earnapp_canary, "EarnAppAccountCollector", return_value=Collector()),
    ):
        result = asyncio.run(
            earnapp_canary.verify_canary(
                "earnapp-node-persisted-baseline",
                attempts=1,
                interval_seconds=0,
            )
        )

    assert result["status"] == "workload_verified"
    assert result["workload_delta"]["total_uptime"] == 600.0


def test_verify_canary_keeps_unknown_billing_pending_without_guessing(monkeypatch):
    samples = [
        {
            "status": "online",
            "authenticated": True,
            "device_present": True,
            "online": True,
            "banned": False,
            "device_id": "sdk-mac-" + "b" * 32,
            "billing": "",
            "total_uptime": 1000,
            "bandwidth": 10,
        },
        {
            "status": "online",
            "authenticated": True,
            "device_present": True,
            "online": True,
            "banned": False,
            "device_id": "sdk-mac-" + "b" * 32,
            "billing": "",
            "total_uptime": 1600,
            "bandwidth": 20,
        },
    ]

    class Collector:
        async def link_and_verify_device(self, *_args, **_kwargs):
            return samples.pop(0)

    with (
        patch.object(
            database,
            "get_earnapp_logical_node",
            AsyncMock(
                return_value={
                    "state": "ACTIVE",
                    "account_id": 1,
                    "current_proxy_id": 12,
                    "device_id": "sdk-mac-" + "b" * 32,
                    "platform": "macos",
                }
            ),
        ),
        patch.object(
            database,
            "get_earnapp_account_credentials",
            AsyncMock(
                return_value={
                    "state": "ACTIVE",
                    "credentials": {},
                }
            ),
        ),
        patch.object(
            database,
            "get_earnapp_account_node_routes",
            AsyncMock(
                return_value=[
                    {
                        "logical_node_id": "earnapp-node-unknown",
                        "proxy_id": 12,
                    }
                ]
            ),
        ),
        patch.object(earnapp_canary, "EarnAppAccountCollector", return_value=Collector()),
    ):
        result = asyncio.run(earnapp_canary.verify_canary("earnapp-node-unknown", attempts=2, interval_seconds=0))

    assert result["status"] == "online_pending_usage"
    assert result["workload_state"] == "online_pending_usage"
    assert result["workload_reason"] == "billing_unknown"


@pytest.mark.asyncio
async def test_canary_deploy_route_defaults_to_authorized_ubuntu_lane(monkeypatch):
    routes = {route.path for route in main.app.routes}
    assert "/api/admin/earnapp/canary/deploy" in routes
    assert "/api/admin/earnapp/canary/{logical_node_id}/verify" in routes

    deploy = AsyncMock(
        return_value={
            "status": "deployed",
            "logical_node_id": "earnapp-canary-1",
            "account_id": 7,
            "worker_id": 3,
            "device_id": "sdk-node-test",
            "proxy_id": 12,
            "generation": 1,
            "container_id": "container-id",
        }
    )
    verify = AsyncMock(
        return_value={
            "status": "workload_verified",
            "workload_state": "workload_verified",
            "device_id": "sdk-node-test",
            "online": True,
        }
    )
    monkeypatch.setattr(main, "_resolve_worker_id", AsyncMock(return_value=3))
    monkeypatch.setattr(database, "get_config", AsyncMock(return_value={}))
    monkeypatch.setattr(earnapp_canary, "deploy_platform_canary", deploy)
    monkeypatch.setattr(earnapp_canary, "verify_canary", verify)
    monkeypatch.setattr(main, "_persist_earnapp_canary_verification", AsyncMock(side_effect=lambda _node, value: value))
    monkeypatch.setattr(database, "record_health_event", AsyncMock())

    result = await main.api_deploy_earnapp_canary(
        _request("/api/admin/earnapp/canary/deploy"),
        main.EarnAppCanaryDeployRequest(logical_node_id="earnapp-canary-1", worker_id=3),
        _auth={"r": "owner"},
    )

    assert result["deployment"]["logical_node_id"] == "earnapp-canary-1"
    assert deploy.await_args.kwargs["platform"] == "ubuntu"
    verify.assert_awaited_once_with("earnapp-canary-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["ios"])
async def test_owner_canary_route_blocks_platform_specific_runtime(monkeypatch, platform):
    deploy = AsyncMock(
        return_value={
            "status": "deployed",
            "logical_node_id": f"earnapp-{platform}-canary",
            "worker_id": 3,
            "device_id": ("sdk-ios-" if platform == "ios" else "sdk-node-") + "1" * 32,
            "generation": 1,
        }
    )
    verify = AsyncMock(
        return_value={
            "status": "workload_verified",
            "workload_state": "workload_verified",
            "online": True,
        }
    )
    monkeypatch.setattr(main, "_resolve_worker_id", AsyncMock(return_value=3))
    monkeypatch.setattr(earnapp_canary, "deploy_platform_canary", deploy)
    monkeypatch.setattr(earnapp_canary, "verify_canary", verify)
    monkeypatch.setattr(main, "_persist_earnapp_canary_verification", AsyncMock(side_effect=lambda _node, value: value))
    monkeypatch.setattr(database, "get_config", AsyncMock(return_value={}))
    monkeypatch.setattr(database, "record_health_event", AsyncMock())

    with pytest.raises(HTTPException) as exc:
        await main.api_deploy_earnapp_canary(
            _request("/api/admin/earnapp/canary/deploy"),
            main.EarnAppCanaryDeployRequest(
                logical_node_id=f"earnapp-{platform}-canary",
                worker_id=3,
                platform=platform,
            ),
            _auth={"r": "owner"},
        )

    assert exc.value.status_code == 409
    deploy.assert_not_awaited()
    verify.assert_not_awaited()


def test_owner_canary_request_defaults_to_ubuntu_and_rejects_unknown_platform():
    assert main.EarnAppCanaryDeployRequest(logical_node_id="earnapp-ubuntu-canary").platform == "ubuntu"
    with pytest.raises(ValueError):
        main.EarnAppCanaryDeployRequest(logical_node_id="earnapp-invalid-canary", platform="android")


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["macos", "ios"])
async def test_canary_deploy_route_rejects_apple_runtimes_before_worker_or_lease_calls(monkeypatch, platform):
    resolve = AsyncMock()
    deploy = AsyncMock()
    prepare = AsyncMock()
    monkeypatch.setattr(main, "_resolve_worker_id", resolve)
    monkeypatch.setattr(earnapp_canary, "deploy_canary", deploy)
    monkeypatch.setattr(earnapp_canary, "deploy_platform_canary", deploy)
    monkeypatch.setattr(earnapp_deploy, "prepare_node", prepare)

    with pytest.raises(HTTPException) as exc:
        await main.api_deploy_earnapp_canary(
            _request("/api/admin/earnapp/canary/deploy"),
            main.EarnAppCanaryDeployRequest(
                logical_node_id=f"earnapp-{platform}-policy-block",
                worker_id=3,
                platform=platform,
            ),
            _auth={"r": "owner"},
        )

    assert exc.value.status_code == 409
    assert "macos/ios emulation remains disabled" in str(exc.value.detail).lower()
    resolve.assert_not_awaited()
    deploy.assert_not_awaited()
    prepare.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["ios", "ubuntu"])
async def test_platform_canary_uses_matching_transport_and_persists_redacted_state(monkeypatch, platform):
    device_prefix = "sdk-ios-" if platform == "ios" else "sdk-node-"
    prepared = earnapp_deploy.PreparedEarnAppNode(
        worker_id=3,
        slot_id="ipv4-001",
        logical_node_id=f"earnapp-{platform}-canary",
        platform=platform,
        account_id=7,
        device_id=device_prefix + "1" * 32,
        generation=4,
        proxy={
            "proxy_id": 12,
            "host": "proxy.example",
            "port": 1080,
            "protocol": "socks5",
            "username": "proxy-user",
            "password": "proxy-secret",
            "exit_ip": "203.0.113.10",
            "country_code": "VN" if platform == "ios" else "US",
            "ip_type": "residential",
        },
        identity={
            "platform": "ubuntu",
            "machine_id": "2" * 32,
            "device_id": device_prefix + "1" * 32,
            "hostname": "earnapp-test",
        }
        if platform == "ubuntu"
        else {},
        identity_asset_id=f"earnapp-{platform}-canary",
    )
    deploy = AsyncMock(
        return_value={"instance_id": "lxd-node"} if platform == "ubuntu" else {"container_id": "ios-node"}
    )
    save = AsyncMock()
    monkeypatch.setattr(database, "get_provider_instance", AsyncMock(return_value=None))
    monkeypatch.setattr(database, "get_earnapp_logical_node", AsyncMock(return_value=None))
    monkeypatch.setattr(database, "assign_earnapp_account", AsyncMock())
    monkeypatch.setattr(earnapp_deploy, "prepare_node", AsyncMock(return_value=prepared))
    monkeypatch.setattr(database, "save_provider_instance", save)

    result = await earnapp_canary.deploy_platform_canary(
        prepared.logical_node_id,
        3,
        platform=platform,
        worker_deploy=deploy,
        worker_remove=AsyncMock(),
        lxd_settings={"cpu": 2, "memory_mib": 2048},
    )

    transport = deploy.await_args.args[2]
    if platform == "ios":
        assert transport["image"] == earnapp_runtime.IOS_RUNTIME_IMAGE
        assert transport["runtime_contract"]["platform"] == "ios"
    else:
        assert transport["lxd_cpu"] == 2
        assert transport["lxd_memory_mib"] == 2048
        assert transport["identity"]["device_id"] == prepared.device_id
    persisted = save.await_args.kwargs["spec"]
    assert "proxy-secret" not in json.dumps(persisted, sort_keys=True)
    assert save.await_args.kwargs["proxy_id"] == 12
    assert save.await_args.kwargs["status"] == "running"
    assert result["device_id"] == prepared.device_id


@pytest.mark.asyncio
async def test_failed_ubuntu_canary_cleanup_is_cas_scoped_to_its_own_node(monkeypatch):
    node_id = "earnapp-ubuntu-canary"
    device_id = "sdk-node-" + "3" * 32
    prepared = earnapp_deploy.PreparedEarnAppNode(
        worker_id=3,
        slot_id="ipv4-001",
        logical_node_id=node_id,
        platform="ubuntu",
        account_id=7,
        device_id=device_id,
        generation=5,
        proxy={
            "proxy_id": 14,
            "host": "proxy.example",
            "port": 1080,
            "protocol": "socks5",
            "exit_ip": "203.0.113.14",
            "country_code": "US",
            "ip_type": "residential",
        },
        identity={
            "platform": "ubuntu",
            "machine_id": "4" * 32,
            "device_id": device_id,
            "hostname": "earnapp-test",
        },
    )
    remove = AsyncMock()
    rollback = AsyncMock(return_value=True)
    monkeypatch.setattr(database, "get_provider_instance", AsyncMock(return_value=None))
    monkeypatch.setattr(database, "get_earnapp_logical_node", AsyncMock(return_value=None))
    monkeypatch.setattr(database, "assign_earnapp_account", AsyncMock())
    monkeypatch.setattr(earnapp_deploy, "prepare_node", AsyncMock(return_value=prepared))
    monkeypatch.setattr(database, "rollback_earnapp_canary_binding", rollback)

    with pytest.raises(RuntimeError, match="isolated failure"):
        await earnapp_canary.deploy_platform_canary(
            node_id,
            3,
            platform="ubuntu",
            worker_deploy=AsyncMock(side_effect=RuntimeError("isolated failure")),
            worker_remove=remove,
        )

    remove.assert_awaited_once_with(3, node_id, 5, device_id)
    rollback.assert_awaited_once_with(
        node_id,
        3,
        generation=5,
        proxy_id=14,
        reason="EARNAPP_CANARY_DEPLOY_FAILED",
    )


@pytest.mark.asyncio
async def test_retry_running_ios_canary_reuses_identity_account_and_proxy(monkeypatch):
    node_id = "earnapp-ios-retry"
    assign = AsyncMock()
    prepare = AsyncMock()
    deploy = AsyncMock()
    remove = AsyncMock()
    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(
            return_value={
                "logical_node_id": node_id,
                "platform": "ios",
                "account_id": 7,
                "current_proxy_id": 12,
                "device_id": "sdk-ios-" + "4" * 32,
            }
        ),
    )
    monkeypatch.setattr(
        database,
        "get_provider_instance",
        AsyncMock(
            return_value={
                "worker_id": 3,
                "status": "verification_pending",
                "container_id": "ios-existing",
            }
        ),
    )
    monkeypatch.setattr(database, "assign_earnapp_account", assign)
    monkeypatch.setattr(earnapp_deploy, "prepare_node", prepare)

    result = await earnapp_canary.deploy_platform_canary(
        node_id,
        3,
        platform="ios",
        worker_deploy=deploy,
        worker_remove=remove,
    )

    assert result == {
        "status": "already_deployed",
        "logical_node_id": node_id,
        "worker_id": 3,
        "container_id": "ios-existing",
    }
    assign.assert_not_awaited()
    prepare.assert_not_awaited()
    deploy.assert_not_awaited()
    remove.assert_not_awaited()


@pytest.mark.asyncio
async def test_ios_provider_instance_persist_failure_cleans_only_matching_generation(monkeypatch):
    node_id = "earnapp-ios-persist-fail"
    device_id = "sdk-ios-" + "5" * 32
    prepared = earnapp_deploy.PreparedEarnAppNode(
        worker_id=3,
        slot_id="ipv4-001",
        logical_node_id=node_id,
        platform="ios",
        account_id=7,
        device_id=device_id,
        generation=6,
        proxy={
            "proxy_id": 16,
            "host": "proxy.example",
            "port": 1080,
            "protocol": "socks5",
            "exit_ip": "203.0.113.16",
            "country_code": "VN",
            "ip_type": "residential",
        },
        identity_asset_id=node_id,
    )
    remove = AsyncMock()
    rollback = AsyncMock(return_value=True)
    monkeypatch.setattr(database, "get_provider_instance", AsyncMock(return_value=None))
    monkeypatch.setattr(database, "get_earnapp_logical_node", AsyncMock(return_value=None))
    monkeypatch.setattr(database, "assign_earnapp_account", AsyncMock())
    monkeypatch.setattr(earnapp_deploy, "prepare_node", AsyncMock(return_value=prepared))
    monkeypatch.setattr(database, "save_provider_instance", AsyncMock(side_effect=RuntimeError("db failed")))
    monkeypatch.setattr(database, "rollback_earnapp_canary_binding", rollback)

    with pytest.raises(RuntimeError, match="db failed"):
        await earnapp_canary.deploy_platform_canary(
            node_id,
            3,
            platform="ios",
            worker_deploy=AsyncMock(return_value={"container_id": "ios-container"}),
            worker_remove=remove,
        )

    remove.assert_awaited_once_with(3, node_id, 6, device_id)
    rollback.assert_awaited_once_with(
        node_id,
        3,
        generation=6,
        proxy_id=16,
        reason="EARNAPP_CANARY_PERSIST_FAILED",
    )


@pytest.mark.asyncio
async def test_canary_deploy_route_defaults_to_lxd_cleanup_not_composite_docker_cleanup(monkeypatch):
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
    proxy = AsyncMock(
        return_value={
            "status": "removed",
            "main_present": False,
            "sidecar_present": False,
        }
    )
    monkeypatch.setattr(main, "_resolve_worker_id", AsyncMock(return_value=3))
    monkeypatch.setattr(main, "_proxy_to_worker", proxy)
    monkeypatch.setattr(database, "get_config", AsyncMock(return_value={}))
    monkeypatch.setattr(earnapp_canary, "deploy_platform_canary", deploy)
    monkeypatch.setattr(main, "_persist_earnapp_canary_verification", AsyncMock(side_effect=lambda _node, value: value))
    monkeypatch.setattr(
        earnapp_canary,
        "verify_canary",
        AsyncMock(
            return_value={
                "status": "workload_verified",
                "workload_state": "workload_verified",
                "device_id": "sdk-mac-test",
                "online": True,
            }
        ),
    )
    monkeypatch.setattr(database, "record_health_event", AsyncMock())

    await main.api_deploy_earnapp_canary(
        _request("/api/admin/earnapp/canary/deploy"),
        main.EarnAppCanaryDeployRequest(logical_node_id="earnapp-canary-1", worker_id=3),
        _auth={"r": "owner"},
    )

    deploy.assert_awaited_once()
    proxy.assert_not_awaited()


@pytest.mark.asyncio
async def test_macos_canary_policy_block_never_sends_cleanup_or_worker_calls(monkeypatch):
    node_id = "earnapp-macos-cas"
    device_id = "sdk-mac-" + "a" * 32
    proxy = AsyncMock(return_value={"status": "removed", "main_present": False, "sidecar_present": False})

    async def deploy(*_args, **kwargs):
        await kwargs["worker_remove"](3, node_id, 7, device_id)
        return {"status": "deployed", "logical_node_id": node_id, "worker_id": 3}

    monkeypatch.setattr(main, "_resolve_worker_id", AsyncMock(return_value=3))
    monkeypatch.setattr(main, "_proxy_to_worker", proxy)
    monkeypatch.setattr(earnapp_canary, "deploy_canary", deploy)
    monkeypatch.setattr(
        earnapp_canary,
        "verify_canary",
        AsyncMock(return_value={"workload_state": "workload_verified", "online": True}),
    )
    monkeypatch.setattr(main, "_persist_earnapp_canary_verification", AsyncMock(side_effect=lambda _node, value: value))
    monkeypatch.setattr(database, "record_health_event", AsyncMock())

    with pytest.raises(HTTPException) as exc:
        await main.api_deploy_earnapp_canary(
            _request("/api/admin/earnapp/canary/deploy"),
            main.EarnAppCanaryDeployRequest(logical_node_id=node_id, worker_id=3, platform="macos"),
            _auth={"r": "owner"},
        )

    assert exc.value.status_code == 409
    proxy.assert_not_awaited()


@pytest.mark.asyncio
async def test_platform_mismatch_rolls_back_new_binding_before_raising(monkeypatch):
    node_id = "earnapp-ubuntu-mismatch"
    device_id = "sdk-node-" + "b" * 32
    rollback = AsyncMock(return_value=True)
    prepared = earnapp_deploy.PreparedEarnAppNode(
        worker_id=3,
        slot_id="ipv4-001",
        logical_node_id=node_id,
        platform="ios",
        account_id=7,
        device_id=device_id,
        generation=4,
        proxy={"proxy_id": 21, "exit_ip": "203.0.113.21", "country_code": "US", "ip_type": "residential"},
    )
    monkeypatch.setattr(database, "get_earnapp_logical_node", AsyncMock(return_value=None))
    monkeypatch.setattr(database, "get_provider_instance", AsyncMock(return_value=None))
    monkeypatch.setattr(database, "assign_earnapp_account", AsyncMock())
    monkeypatch.setattr(earnapp_deploy, "prepare_node", AsyncMock(return_value=prepared))
    monkeypatch.setattr(database, "rollback_earnapp_canary_binding", rollback)

    with pytest.raises(ValueError, match="platform selection"):
        await earnapp_canary.deploy_platform_canary(
            node_id,
            3,
            platform="ubuntu",
            worker_deploy=AsyncMock(),
            worker_remove=AsyncMock(),
        )

    rollback.assert_awaited_once_with(
        node_id,
        3,
        generation=4,
        proxy_id=21,
        reason="EARNAPP_CANARY_PLATFORM_MISMATCH",
    )


@pytest.mark.asyncio
async def test_canary_deploy_route_refuses_mutating_the_protected_live_canary(monkeypatch):
    resolve = AsyncMock(return_value=3)
    deploy = AsyncMock()
    monkeypatch.setattr(main, "_resolve_worker_id", resolve)
    monkeypatch.setattr(earnapp_canary, "deploy_canary", deploy)

    with pytest.raises(HTTPException) as exc:
        await main.api_deploy_earnapp_canary(
            _request("/api/admin/earnapp/canary/deploy"),
            main.EarnAppCanaryDeployRequest(logical_node_id="earnapp-canary-test-sing-1", worker_id=3),
            _auth={"r": "owner"},
        )

    assert exc.value.status_code == 409
    resolve.assert_not_awaited()
    deploy.assert_not_awaited()


@pytest.mark.asyncio
async def test_canary_deploy_route_rejects_online_without_workload(monkeypatch):
    monkeypatch.setattr(main, "_resolve_worker_id", AsyncMock(return_value=3))
    monkeypatch.setattr(database, "get_config", AsyncMock(return_value={}))
    monkeypatch.setattr(
        earnapp_canary,
        "deploy_platform_canary",
        AsyncMock(
            return_value={
                "status": "deployed",
                "logical_node_id": "earnapp-canary-online-only",
                "worker_id": 3,
            }
        ),
    )
    monkeypatch.setattr(main, "_persist_earnapp_canary_verification", AsyncMock(side_effect=lambda _node, value: value))
    monkeypatch.setattr(
        earnapp_canary,
        "verify_canary",
        AsyncMock(
            return_value={
                "status": "online_pending_usage",
                "workload_state": "online_pending_usage",
                "online": True,
            }
        ),
    )
    monkeypatch.setattr(database, "record_health_event", AsyncMock())

    with pytest.raises(HTTPException) as exc:
        await main.api_deploy_earnapp_canary(
            _request("/api/admin/earnapp/canary/deploy"),
            main.EarnAppCanaryDeployRequest(
                logical_node_id="earnapp-canary-online-only",
                worker_id=3,
                platform="ubuntu",
            ),
            _auth={"r": "owner"},
        )

    assert exc.value.status_code == 409
    assert "authenticated workload is not verified" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_canary_verify_route_rejects_online_without_workload(monkeypatch):
    pending = {
        "status": "online_pending_usage",
        "workload_state": "online_pending_usage",
        "workload_reason": "awaiting_metric_delta",
        "authenticated": True,
        "device_present": True,
        "device_id": "sdk-ios-" + "7" * 32,
        "billing": "qualified_uptime",
        "total_uptime": 1200.0,
        "earned_total": 0.0,
        "online": True,
    }
    monkeypatch.setattr(
        earnapp_canary,
        "verify_canary",
        AsyncMock(return_value=pending),
    )
    monkeypatch.setattr(
        database,
        "get_provider_instance",
        AsyncMock(
            return_value={
                "instance_id": "earnapp-canary-online-only",
                "slug": "earnapp",
                "worker_id": 3,
                "mode": "proxy",
                "container_id": "ios-container",
                "sidecar_id": "ios-sidecar",
                "proxy_id": 12,
                "status": "running",
            }
        ),
    )
    monkeypatch.setattr(
        database,
        "get_provider_instance_spec",
        AsyncMock(return_value={"device_id": pending["device_id"], "generation": 4}),
    )
    save = AsyncMock()
    monkeypatch.setattr(database, "save_provider_instance", save)

    with pytest.raises(HTTPException) as exc:
        await main.api_verify_earnapp_canary(
            _request("/api/admin/earnapp/canary/earnapp-canary-online-only/verify"),
            "earnapp-canary-online-only",
            _auth={"r": "owner"},
        )

    assert exc.value.status_code == 409
    assert "workload" in str(exc.value.detail).lower()
    saved = save.await_args.kwargs
    assert saved["status"] == "verification_pending"
    assert saved["sidecar_id"] == "ios-sidecar"
    assert saved["spec"]["earnapp_device_verification"] == pending


@pytest.mark.asyncio
async def test_canary_deploy_route_policy_block_does_not_persist_a_new_workload_baseline(monkeypatch):
    node_id = "earnapp-ios-pending"
    device_id = "sdk-ios-" + "8" * 32
    pending = {
        "status": "online_pending_usage",
        "workload_state": "online_pending_usage",
        "workload_reason": "awaiting_metric_delta",
        "authenticated": True,
        "device_present": True,
        "device_id": device_id,
        "billing": "qualified_uptime",
        "total_uptime": 900.0,
        "online": True,
    }
    monkeypatch.setattr(main, "_resolve_worker_id", AsyncMock(return_value=3))
    monkeypatch.setattr(
        earnapp_canary,
        "deploy_platform_canary",
        AsyncMock(
            return_value={
                "status": "deployed",
                "logical_node_id": node_id,
                "worker_id": 3,
                "device_id": device_id,
                "generation": 2,
                "proxy_id": 12,
                "container_id": "ios-container",
            }
        ),
    )
    monkeypatch.setattr(earnapp_canary, "verify_canary", AsyncMock(return_value=pending))
    monkeypatch.setattr(
        database,
        "get_provider_instance",
        AsyncMock(
            return_value={
                "instance_id": node_id,
                "slug": "earnapp",
                "worker_id": 3,
                "mode": "proxy",
                "container_id": "ios-container",
                "sidecar_id": "",
                "proxy_id": 12,
                "status": "running",
            }
        ),
    )
    monkeypatch.setattr(
        database,
        "get_provider_instance_spec",
        AsyncMock(return_value={"device_id": device_id, "generation": 2}),
    )
    save = AsyncMock()
    monkeypatch.setattr(database, "save_provider_instance", save)
    monkeypatch.setattr(database, "record_health_event", AsyncMock())

    with pytest.raises(HTTPException) as exc:
        await main.api_deploy_earnapp_canary(
            _request("/api/admin/earnapp/canary/deploy"),
            main.EarnAppCanaryDeployRequest(logical_node_id=node_id, worker_id=3, platform="ios"),
            _auth={"r": "owner"},
        )

    assert exc.value.status_code == 409
    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_ios_canary_policy_block_never_sends_cleanup_or_worker_calls(monkeypatch):
    node_id = "earnapp-ios-cas"
    device_id = "sdk-ios-" + "9" * 32
    proxy = AsyncMock(return_value={"status": "removed", "main_present": False, "sidecar_present": False})

    async def deploy(*_args, **kwargs):
        await kwargs["worker_remove"](3, node_id, 6, device_id)
        return {"status": "deployed", "logical_node_id": node_id, "worker_id": 3}

    monkeypatch.setattr(main, "_resolve_worker_id", AsyncMock(return_value=3))
    monkeypatch.setattr(main, "_proxy_to_worker", proxy)
    monkeypatch.setattr(earnapp_canary, "deploy_platform_canary", deploy)
    monkeypatch.setattr(
        earnapp_canary,
        "verify_canary",
        AsyncMock(return_value={"workload_state": "workload_verified", "online": True}),
    )
    monkeypatch.setattr(database, "get_provider_instance", AsyncMock(return_value=None))
    monkeypatch.setattr(main, "_persist_earnapp_canary_verification", AsyncMock(side_effect=lambda _node, value: value))
    monkeypatch.setattr(database, "record_health_event", AsyncMock())

    with pytest.raises(HTTPException) as exc:
        await main.api_deploy_earnapp_canary(
            _request("/api/admin/earnapp/canary/deploy"),
            main.EarnAppCanaryDeployRequest(logical_node_id=node_id, worker_id=3, platform="ios"),
            _auth={"r": "owner"},
        )

    assert exc.value.status_code == 409
    proxy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("slug", "device_id"),
    [
        ("earnapp-canary-test-sing-1", "sdk-mac-" + "1" * 32),
        ("earnapp-recovery-test-sing-2", "sdk-mac-" + "2" * 32),
        ("earnapp-ios-canary-test-sing-3", "sdk-ios-" + "3" * 32),
    ],
)
async def test_worker_cleanup_refuses_every_existing_earnapp_runtime(slug, device_id, monkeypatch):
    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(worker_api.orchestrator, "remove_earnapp_service") as remove,
        pytest.raises(HTTPException) as exc,
    ):
        await worker_api.api_remove_earnapp_docker_node(
            _request(f"/api/earnapp/docker-nodes/{slug}"),
            slug,
            worker_api.EarnAppDockerNodeCasSpec(generation=1, device_id=device_id),
        )

    assert exc.value.status_code == 409
    remove.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "slug",
    [
        "earnapp-canary-test-sing-1",
        "earnapp-recovery-test-sing-2",
        "earnapp-ios-canary-test-sing-3",
    ],
)
@pytest.mark.parametrize(
    "action",
    [
        worker_api.api_start_container,
        worker_api.api_stop_container,
        worker_api.api_restart_container,
    ],
)
async def test_worker_lifecycle_refuses_every_existing_earnapp_runtime(slug, action, monkeypatch):
    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(worker_api.orchestrator, "start_service") as start,
        patch.object(worker_api.orchestrator, "stop_service") as stop,
        patch.object(worker_api.orchestrator, "restart_service") as restart,
        pytest.raises(HTTPException) as exc,
    ):
        await action(_request(f"/api/containers/{slug}"), slug)

    assert exc.value.status_code == 409
    start.assert_not_called()
    stop.assert_not_called()
    restart.assert_not_called()


@pytest.mark.asyncio
async def test_generic_worker_remove_refuses_existing_earnapp_runtime(monkeypatch):
    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(worker_api.orchestrator, "remove_earnapp_service") as earnapp_remove,
        patch.object(worker_api.orchestrator, "remove_service") as generic_remove,
        pytest.raises(HTTPException) as exc,
    ):
        await worker_api.api_remove_container(
            _request("/api/containers/earnapp-recovery-test-sing-2"),
            "earnapp-recovery-test-sing-2",
        )

    assert exc.value.status_code == 409
    earnapp_remove.assert_not_called()
    generic_remove.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "slug",
    [
        "earnapp",
        "earnapp-canary-test-sing-1",
        "earnapp-recovery-test-sing-2",
        "earnapp-ios-canary-test-sing-3",
    ],
)
@pytest.mark.parametrize("action", ["stop", "restart", "remove"])
async def test_server_lifecycle_refuses_every_existing_earnapp_runtime(slug, action, monkeypatch):
    proxy = AsyncMock()
    resolve = AsyncMock(return_value=3)
    monkeypatch.setattr(main, "_require_writer", lambda _request: {"r": "writer"})
    monkeypatch.setattr(main, "_resolve_worker_id", resolve)
    monkeypatch.setattr(main, "_proxy_worker_command", proxy)

    with pytest.raises(HTTPException) as exc:
        if action == "stop":
            await main._svc_stop(_request(f"/api/stop/{slug}"), slug, 3)
        elif action == "restart":
            await main._svc_restart(_request(f"/api/restart/{slug}"), slug, 3)
        else:
            await main._svc_remove(_request(f"/api/remove/{slug}"), slug, 3, False)

    assert exc.value.status_code == 409
    resolve.assert_not_awaited()
    proxy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "slug",
    [
        "earnapp",
        "earnapp-canary-test-sing-1",
        "earnapp-recovery-test-sing-2",
        "earnapp-ios-canary-test-sing-3",
    ],
)
async def test_server_start_refuses_every_existing_earnapp_runtime(slug, monkeypatch):
    proxy = AsyncMock()
    resolve = AsyncMock(return_value=3)
    monkeypatch.setattr(main, "_require_writer", lambda _request: {"r": "writer"})
    monkeypatch.setattr(main, "_resolve_worker_id", resolve)
    monkeypatch.setattr(main, "_proxy_worker_command", proxy)

    with pytest.raises(HTTPException) as exc:
        await main.api_service_start(
            _request(f"/api/services/{slug}/start"),
            slug,
            3,
        )

    assert exc.value.status_code == 409
    resolve.assert_not_awaited()
    proxy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "slug",
    [
        "earnapp",
        "earnapp-canary-test-sing-1",
        "earnapp-recovery-test-sing-2",
        "earnapp-ios-canary-test-sing-3",
    ],
)
@pytest.mark.parametrize("command", ["deploy", "stop", "restart", "start", "remove"])
async def test_raw_worker_command_refuses_every_existing_earnapp_runtime(slug, command, monkeypatch):
    proxy = AsyncMock()
    monkeypatch.setattr(main, "_require_owner", lambda _request: {"r": "owner"})
    monkeypatch.setattr(main, "_require_writer", lambda _request: {"r": "writer"})
    monkeypatch.setattr(main, "_proxy_to_worker", proxy)

    with pytest.raises(HTTPException) as exc:
        await main.api_worker_command(
            _request("/api/workers/3/command"),
            3,
            main.WorkerCommand(command=command, slug=slug, spec={}),
        )

    assert exc.value.status_code == 409
    proxy.assert_not_awaited()


@pytest.mark.asyncio
async def test_raw_worker_deploy_refuses_earnapp_before_worker_or_lease_calls(monkeypatch):
    proxy = AsyncMock()
    wallet = AsyncMock()
    monkeypatch.setattr(main, "_require_owner", lambda _request: {"r": "owner"})
    monkeypatch.setattr(main, "_proxy_to_worker", proxy)
    monkeypatch.setattr(main, "_attach_myst_wallet_for_deploy", wallet)

    with pytest.raises(HTTPException) as exc:
        await main.api_worker_command(
            _request("/api/workers/3/command"),
            3,
            main.WorkerCommand(command="deploy", slug="earnapp", spec={}),
        )

    assert exc.value.status_code == 409
    assert "macos/ios emulation remains disabled" in str(exc.value.detail).lower()
    proxy.assert_not_awaited()
    wallet.assert_not_awaited()


@pytest.mark.asyncio
async def test_raw_worker_deploy_refuses_earnapp_provider_slug_hidden_under_an_alias(monkeypatch):
    proxy = AsyncMock(return_value={"container_id": "must-not-deploy"})
    wallet = AsyncMock()
    monkeypatch.setattr(main, "_require_owner", lambda _request: {"r": "owner"})
    monkeypatch.setattr(main, "_proxy_to_worker", proxy)
    monkeypatch.setattr(main, "_attach_myst_wallet_for_deploy", wallet)
    monkeypatch.setattr(database, "save_deployment", AsyncMock())
    monkeypatch.setattr(database, "record_health_event", AsyncMock())
    monkeypatch.setattr(main.metrics, "record_container_lifecycle", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "_spawn", lambda coro: coro.close())

    with pytest.raises(HTTPException) as exc:
        await main.api_worker_command(
            _request("/api/workers/3/command"),
            3,
            main.WorkerCommand(
                command="deploy",
                slug="runtime-alias",
                spec={"provider_slug": "earnapp", "image": "example.invalid/earnapp:test"},
            ),
        )

    assert exc.value.status_code == 409
    proxy.assert_not_awaited()
    wallet.assert_not_awaited()


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
                "platform": "macos",
                "state": "ACTIVE",
            }
        ),
    )
    fetch = AsyncMock(
        return_value={
            "platform": "macos",
            "asset_kind": "mac_identity_profile",
            "device_id": "sdk-mac-test",
            "value": "encrypted-profile",
        }
    )
    monkeypatch.setattr(database, "get_earnapp_identity_profile", fetch)

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
@pytest.mark.parametrize(
    ("platform", "asset_kind"),
    [("ios", "ios_identity_profile"), ("ubuntu", "ubuntu_identity_profile")],
)
async def test_runtime_asset_request_supports_only_the_nodes_platform_asset(monkeypatch, platform, asset_kind):
    monkeypatch.setattr(main, "_require_confirmed_worker", AsyncMock())
    monkeypatch.setattr(database, "get_worker_by_client_id", AsyncMock(return_value={"id": 3}))
    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(return_value={"logical_node_id": "earnapp-node-1", "assigned_worker_id": 3, "platform": platform}),
    )
    fetch = AsyncMock(return_value={"platform": platform, "asset_kind": asset_kind, "value": "opaque-profile"})
    monkeypatch.setattr(database, "get_earnapp_identity_profile", fetch)

    result = await main.api_worker_runtime_asset(
        _request("/api/workers/runtime-asset"),
        main.RuntimeAssetRequest(
            client_id="worker-a",
            provider="earnapp",
            asset_kind=asset_kind,
            asset_id="earnapp-node-1",
        ),
    )

    assert result["value"] == "opaque-profile"
    fetch.assert_awaited_once_with("earnapp-node-1")


@pytest.mark.asyncio
async def test_runtime_asset_request_rejects_cross_platform_asset_kind(monkeypatch):
    monkeypatch.setattr(main, "_require_confirmed_worker", AsyncMock())
    monkeypatch.setattr(database, "get_worker_by_client_id", AsyncMock(return_value={"id": 3}))
    monkeypatch.setattr(
        database,
        "get_earnapp_logical_node",
        AsyncMock(return_value={"logical_node_id": "earnapp-node-1", "assigned_worker_id": 3, "platform": "ios"}),
    )

    with pytest.raises(HTTPException) as exc:
        await main.api_worker_runtime_asset(
            _request("/api/workers/runtime-asset"),
            main.RuntimeAssetRequest(
                client_id="worker-a",
                provider="earnapp",
                asset_kind="mac_identity_profile",
                asset_id="earnapp-node-1",
            ),
        )

    assert exc.value.status_code == 403


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
async def test_worker_remove_preserves_all_earnapp_heartbeat_state_when_runtime_is_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = "sdk-ios-" + "1" * 32
    worker_api._save_earnapp_state("earnapp-canary-1", {"generation": 1, "device_id": device_id})
    worker_api._save_earnapp_state("earnapp-canary-2", {"generation": 1, "device_id": "sdk-ios-" + "2" * 32})

    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(
            worker_api.orchestrator,
            "remove_earnapp_service",
            return_value={"main_present": False, "sidecar_present": False},
        ) as remove,
        pytest.raises(HTTPException) as exc,
    ):
        await worker_api.api_remove_container(
            _request("/api/containers/earnapp-canary-1"),
            "earnapp-canary-1",
        )

    assert exc.value.status_code == 409
    remove.assert_not_called()
    assert worker_api._earnapp_state_path("earnapp-canary-1").exists()
    assert worker_api._earnapp_state_path("earnapp-canary-2").exists()


@pytest.mark.asyncio
async def test_generic_worker_remove_cannot_bypass_disabled_earnapp_runtime_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = "sdk-mac-" + "1" * 32
    worker_api._save_earnapp_state("earnapp-node-1", {"generation": 1, "device_id": device_id})

    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(
            worker_api.orchestrator,
            "remove_earnapp_service",
            return_value={"main_present": False, "sidecar_present": False},
        ) as remove,
        patch.object(
            worker_api.orchestrator,
            "remove_service",
            side_effect=AssertionError("generic Docker cleanup must not handle EarnApp"),
        ) as generic_remove,
        pytest.raises(HTTPException) as exc,
    ):
        await worker_api.api_remove_container(
            _request("/api/containers/earnapp-node-1"),
            "earnapp-node-1",
        )

    assert exc.value.status_code == 409
    remove.assert_not_called()
    generic_remove.assert_not_called()
    assert worker_api._earnapp_state_path("earnapp-node-1").exists()


@pytest.mark.asyncio
async def test_worker_cleanup_refuses_the_protected_live_canary(monkeypatch):
    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(worker_api.orchestrator, "remove_earnapp_service") as remove,
        pytest.raises(HTTPException) as exc,
    ):
        await worker_api.api_remove_earnapp_docker_node(
            _request("/api/earnapp/docker-nodes/earnapp-canary-test-sing-1"),
            "earnapp-canary-test-sing-1",
            worker_api.EarnAppDockerNodeCasSpec(generation=1, device_id="sdk-mac-" + "1" * 32),
        )

    assert exc.value.status_code == 409
    remove.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action",
    [
        worker_api.api_start_container,
        worker_api.api_stop_container,
        worker_api.api_restart_container,
    ],
)
async def test_worker_lifecycle_refuses_the_protected_live_canary(action, monkeypatch):
    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(worker_api.orchestrator, "start_service") as start,
        patch.object(worker_api.orchestrator, "stop_service") as stop,
        patch.object(worker_api.orchestrator, "restart_service") as restart,
        pytest.raises(HTTPException) as exc,
    ):
        await action(
            _request("/api/containers/earnapp-canary-test-sing-1"),
            "earnapp-canary-test-sing-1",
        )

    assert exc.value.status_code == 409
    start.assert_not_called()
    stop.assert_not_called()
    restart.assert_not_called()


@pytest.mark.asyncio
async def test_worker_deploy_refuses_the_protected_live_canary(monkeypatch):
    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(worker_api.orchestrator, "deploy_raw") as deploy,
        pytest.raises(HTTPException) as exc,
    ):
        await worker_api.api_deploy_container(
            _request("/api/containers/earnapp-canary-test-sing-1/deploy"),
            "earnapp-canary-test-sing-1",
            worker_api.DeploySpec(image="cashpilot/earnapp-mac:test", provider_slug="earnapp"),
        )

    assert exc.value.status_code == 409
    deploy.assert_not_called()


@pytest.mark.asyncio
async def test_worker_earnapp_docker_remove_is_blocked_and_preserves_state(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = "sdk-ios-" + "1" * 32
    worker_api._save_earnapp_state("earnapp-node-1", {"generation": 1, "device_id": device_id})

    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(
            worker_api.orchestrator,
            "remove_earnapp_service",
            return_value={"main_present": False, "sidecar_present": False},
        ) as remove,
        pytest.raises(HTTPException) as exc,
    ):
        await worker_api.api_remove_earnapp_docker_node(
            _request("/api/earnapp/docker-nodes/earnapp-node-1"),
            "earnapp-node-1",
            worker_api.EarnAppDockerNodeCasSpec(generation=1, device_id=device_id),
        )

    assert exc.value.status_code == 409
    remove.assert_not_called()
    assert worker_api._earnapp_state_path("earnapp-node-1").exists()


@pytest.mark.asyncio
async def test_worker_earnapp_docker_remove_preserves_state_when_sidecar_cleanup_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = "sdk-ios-" + "1" * 32
    worker_api._save_earnapp_state("earnapp-node-1", {"generation": 1, "device_id": device_id})

    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(
            worker_api.orchestrator,
            "remove_earnapp_service",
            side_effect=RuntimeError("EarnApp sidecar cleanup incomplete"),
        ),
        pytest.raises(HTTPException) as exc,
    ):
        await worker_api.api_remove_earnapp_docker_node(
            _request("/api/earnapp/docker-nodes/earnapp-node-1"),
            "earnapp-node-1",
            worker_api.EarnAppDockerNodeCasSpec(generation=1, device_id=device_id),
        )

    assert exc.value.status_code == 409
    assert worker_api._earnapp_state_path("earnapp-node-1").exists()


@pytest.mark.asyncio
async def test_worker_earnapp_docker_remove_rejects_stale_generation_before_cleanup(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    device_id = "sdk-ios-" + "6" * 32
    worker_api._save_earnapp_state("earnapp-node-1", {"generation": 7, "device_id": device_id})

    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(worker_api.orchestrator, "remove_earnapp_service") as remove,
        pytest.raises(HTTPException) as exc,
    ):
        await worker_api.api_remove_earnapp_docker_node(
            _request("/api/earnapp/docker-nodes/earnapp-node-1"),
            "earnapp-node-1",
            worker_api.EarnAppDockerNodeCasSpec(generation=6, device_id=device_id),
        )

    assert exc.value.status_code == 409
    remove.assert_not_called()
    assert worker_api._earnapp_state_path("earnapp-node-1").exists()
