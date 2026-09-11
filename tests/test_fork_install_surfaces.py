from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from app import update_check

ROOT = Path(__file__).resolve().parents[1]
FORK_REPO = "https://github.com/assetforgeai-tech/CashPilot"
FORK_GHCR = "ghcr.io/assetforgeai-tech"
UNRAID_IMAGES = {
    "cashpilot.xml": "cashpilot",
    "cashpilot-worker.xml": "cashpilot-worker",
}


def test_fleet_deploy_instructions_use_the_fork_worker_image():
    fleet = (ROOT / "app" / "templates" / "fleet.html").read_text(encoding="utf-8")

    assert f"{FORK_GHCR}/cashpilot-worker" in fleet
    assert "drumsergio/cashpilot-worker" not in fleet


@pytest.mark.parametrize("template_name,image_name", UNRAID_IMAGES.items())
def test_unraid_templates_install_the_fork_ghcr_images(template_name, image_name):
    template = ET.parse(ROOT / "unraid" / template_name).getroot()

    assert template.findtext("Repository") == f"{FORK_GHCR}/{image_name}:latest"
    assert template.findtext("Registry") == f"{FORK_REPO}/pkgs/container/{image_name}"


@pytest.mark.parametrize("template_name", UNRAID_IMAGES)
def test_unraid_templates_keep_support_and_updates_on_the_fork(template_name):
    template = ET.parse(ROOT / "unraid" / template_name).getroot()
    overview = template.findtext("Overview") or ""

    assert template.findtext("Support") == f"{FORK_REPO}/issues"
    assert template.findtext("Project") == FORK_REPO
    assert FORK_REPO in overview
    assert (
        template.findtext("Icon")
        == f"{FORK_REPO.replace('github.com', 'raw.githubusercontent.com')}/main/docs/icon.svg"
    )
    assert (
        template.findtext("TemplateURL")
        == f"{FORK_REPO.replace('github.com', 'raw.githubusercontent.com')}/main/unraid/{template_name}"
    )


def test_update_sources_distinguish_the_fork_server_from_upstream_android():
    assert update_check.ANDROID_LATEST_URL == ("https://api.github.com/repos/GeiserX/CashPilot-android/releases/latest")
    assert update_check.LATEST_URL == ("https://api.github.com/repos/assetforgeai-tech/CashPilot/releases/latest")


def test_update_banner_links_to_the_fork_release():
    app_js = (ROOT / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    expected = "https://github.com/assetforgeai-tech/CashPilot/releases/tag/${encodeURIComponent(state.latest)}"

    assert expected in app_js
    assert "https://github.com/GeiserX/CashPilot/releases/tag/" not in app_js


def test_public_repo_links_do_not_send_operators_to_upstream_cashpilot():
    base = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert 'href="https://github.com/assetforgeai-tech/CashPilot"' in base
    assert "https://github.com/GeiserX/CashPilot" not in base
    assert "github.com/assetforgeai-tech/CashPilot/actions/workflows/test.yml" in readme
    assert "github.com/GeiserX/CashPilot/actions/workflows/test.yml" not in readme
