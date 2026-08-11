from __future__ import annotations

from unittest.mock import MagicMock, patch

from app import provider_installers


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

    assert image == "cashpilot/grass-desktop:v7.6.0"
    dockerfile = client.images.build.call_args.kwargs["fileobj"].getvalue().decode()
    assert "grass-desktop_7.6.0_amd64.deb" in dockerfile
    assert "novnc" in dockerfile
