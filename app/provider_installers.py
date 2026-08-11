"""Provider installer manifest helpers."""

from __future__ import annotations

import json
import platform
from io import BytesIO
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from docker.errors import ImageNotFound

_GRASS_IMAGE = "cashpilot/grass-desktop"
_GRASS_ALLOWED_HOST = "files.grass.io"


def _fetch_json(url: str) -> dict:
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "CashPilot/1.0"})
    with urlopen(req, timeout=30) as resp:  # noqa: S310 - URL is operator/provider config, validated by caller.
        return json.loads(resp.read().decode("utf-8"))


def _platform_key() -> str:
    os_name = platform.system().lower()
    machine = platform.machine().lower()
    arch = "aarch64" if machine in {"arm64", "aarch64"} else "x86_64"
    if os_name == "linux":
        return f"linux-{arch}"
    if os_name == "darwin":
        return f"darwin-{arch}"
    if os_name == "windows":
        return f"windows-{arch}"
    return f"{os_name}-{arch}"


def _safe_grass_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != _GRASS_ALLOWED_HOST:
        raise ValueError("Grass installer URL must be https://files.grass.io/...")


def resolve_installer_manifest(provider: str, manifest_url: str, platform_key: str | None = None) -> dict[str, str]:
    if provider != "grass":
        raise ValueError(f"Installer manifests are not supported for {provider!r}")
    _safe_grass_url(manifest_url)
    manifest = _fetch_json(manifest_url)
    key = platform_key or _platform_key()
    platforms = manifest.get("platforms") or {}
    item = platforms.get(key)
    if not isinstance(item, dict) or not item.get("url"):
        raise ValueError(f"Grass installer manifest has no {key!r} build; available: {sorted(platforms)}")
    url = str(item["url"])
    _safe_grass_url(url)
    return {"platform": key, "version": str(manifest.get("version") or "unknown"), "url": url}


def ensure_installer_image(client, provider: str, resolved: dict[str, str]) -> str:
    if provider != "grass":
        raise ValueError(f"Installer image builds are not supported for {provider!r}")
    version = "".join(c if c.isalnum() or c in ".-_" else "-" for c in resolved["version"])
    image = f"{_GRASS_IMAGE}:{version}"
    try:
        client.images.get(image)
        return image
    except ImageNotFound:
        pass

    dockerfile = _grass_dockerfile(resolved["url"])
    client.images.build(fileobj=BytesIO(dockerfile.encode("utf-8")), tag=image, rm=True, forcerm=True, pull=True)
    return image


def _grass_dockerfile(deb_url: str) -> str:
    _safe_grass_url(deb_url)
    return f"""FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive \\
    DISPLAY=:99 \\
    HOME=/data/profile \\
    XDG_CONFIG_HOME=/data/profile/.config \\
    XDG_CACHE_HOME=/data/profile/.cache \\
    ELECTRON_DISABLE_SECURITY_WARNINGS=true
RUN apt-get update \\
 && apt-get install -y --no-install-recommends ca-certificates curl xvfb x11vnc fluxbox novnc websockify dbus-x11 \\
 && rm -rf /var/lib/apt/lists/*
ADD {deb_url} /tmp/grass-desktop.deb
RUN apt-get update \\
 && apt-get install -y --no-install-recommends /tmp/grass-desktop.deb \\
 && rm -rf /var/lib/apt/lists/* /tmp/grass-desktop.deb
EXPOSE 6080
CMD ["bash", "-lc", "mkdir -p $HOME; rm -f /tmp/.X99-lock; Xvfb :99 -screen 0 1366x768x24 -nolisten tcp >/tmp/xvfb.log 2>&1 & fluxbox >/tmp/fluxbox.log 2>&1 & x11vnc -display :99 -forever -shared -nopw -listen 0.0.0.0 -xkb >/tmp/x11vnc.log 2>&1 & websockify --web=/usr/share/novnc/ 6080 localhost:5900 >/tmp/novnc.log 2>&1 & dbus-run-session sh -lc 'grass-desktop --no-sandbox || Grass --no-sandbox || /opt/Grass/grass-desktop --no-sandbox || /opt/Grass/grass --no-sandbox'"]
"""
