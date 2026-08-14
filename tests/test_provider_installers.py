from __future__ import annotations

from unittest.mock import MagicMock, patch

from app import provider_installers

def test_proxybase_xyz_runtime_command_imports_phrase_and_resolves_cli_path():
    command = provider_installers.proxybase_xyz_command()
    assert "apt-get" not in command
    assert "curl -fsSL https://proxybase.xyz/install.sh | sh" not in command
    assert 'PHASE="${PROXYBASE_XYZ_PHRASE:?missing wallet phrase}"' in command
    assert '"$CLI" wallet import "$PHASE"' in command
    assert '"$CLI" login' in command
    assert '"$CLI" seller start; ' in command
    assert "tail -n +1 -F /root/.proxybase/seller.log" in command

def test_proxybase_xyz_installer_image_installs_cli_at_build_time():
    client = MagicMock()
    client.images.get.side_effect = provider_installers.ImageNotFound("missing")

    image = provider_installers.ensure_proxybase_xyz_image(client)

    assert image == "cashpilot/proxybase-xyz-cli:latest-ubuntu24.04"
    dockerfile = client.images.build.call_args.kwargs["fileobj"].getvalue().decode()
    assert "FROM ubuntu:24.04" in dockerfile
    assert "apt-get install -y --no-install-recommends ca-certificates curl" in dockerfile
    assert "https://proxybase.xyz/install.sh" in dockerfile
    assert "proxybase-cli" in dockerfile


def test_grass_manifest_resolves_linux_amd64_url_and_version():
    manifest = {
        "version": "v7.6.0",
        "platforms": {
            "linux-x86_64": {
                "url": "https://files.grass.io/file/grass-extension-upgrades/v7.6.0/grass-desktop_7.6.0_amd64.deb"
            }
        },
    }

    with (
        patch.object(provider_installers, "_fetch_json", return_value=manifest),
        patch.object(provider_installers.platform, "system", return_value="Linux"),
        patch.object(provider_installers.platform, "machine", return_value="x86_64"),
    ):
        resolved = provider_installers.resolve_installer_manifest(
            "grass", "https://files.grass.io/file/grass-extension-upgrades/desktop-installer-latest.json"
        )

    assert resolved == {
        "platform": "linux-x86_64",
        "version": "v7.6.0",
        "url": "https://files.grass.io/file/grass-extension-upgrades/v7.6.0/grass-desktop_7.6.0_amd64.deb",
    }


def test_grass_manifest_build_tags_image_by_resolved_version():
    client = MagicMock()
    client.images.get.side_effect = provider_installers.ImageNotFound("missing")
    resolved = {
        "platform": "linux-x86_64",
        "version": "v7.6.0",
        "url": "https://files.grass.io/file/grass-extension-upgrades/v7.6.0/grass-desktop_7.6.0_amd64.deb",
    }

    image = provider_installers.ensure_installer_image(client, "grass", resolved)

    assert image == "cashpilot/grass-desktop:v7.6.0-ubuntu24.04"
    dockerfile = client.images.build.call_args.kwargs["fileobj"].getvalue().decode()
    assert "FROM ubuntu:24.04" in dockerfile
    assert "grass-desktop_7.6.0_amd64.deb" in dockerfile
    assert "novnc" in dockerfile

def test_uprock_deb_url_resolves_as_linux_amd64_installer():
    resolved = provider_installers.resolve_installer_manifest(
        "uprock", "https://edge.uprock.com/v1/app-download/UpRock-Mining-v0.0.38.deb"
    )

    assert resolved == {
        "platform": "linux-x86_64",
        "version": "v0.0.38",
        "url": "https://edge.uprock.com/v1/app-download/UpRock-Mining-v0.0.38.deb",
    }

def test_uprock_installer_image_copies_seed_state_before_launch():
    client = MagicMock()
    client.images.get.side_effect = provider_installers.ImageNotFound("missing")
    resolved = {
        "platform": "linux-x86_64",
        "version": "v0.0.38",
        "url": "https://edge.uprock.com/v1/app-download/UpRock-Mining-v0.0.38.deb",
    }

    image = provider_installers.ensure_installer_image(client, "uprock", resolved)

    assert image == "cashpilot/uprock-mining:v0.0.38-ubuntu24.04"
    dockerfile = client.images.build.call_args.kwargs["fileobj"].getvalue().decode()
    assert "UpRock-Mining-v0.0.38.deb" in dockerfile
    assert "/cashpilot/runtime-assets/uprock/credentials.json" in dockerfile
    assert "/cashpilot/runtime-assets/uprock/main.db" in dockerfile
    assert "/root/.local/share/UpRock/main.db" in dockerfile
