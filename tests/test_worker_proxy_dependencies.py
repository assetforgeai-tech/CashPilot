from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_worker_image_dependencies_include_httpx_socks_support():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = {str(value).lower() for value in project["project"]["dependencies"]}
    assert any(value.startswith("httpx[socks]") for value in dependencies)

    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked_packages = {str(package["name"]).lower() for package in lock["package"]}
    assert "socksio" in locked_packages

    exported = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    worker_compat = (ROOT / "requirements-worker.txt").read_text(encoding="utf-8").lower()
    assert "socksio==" in exported
    assert "httpx[socks]>=" in worker_compat
