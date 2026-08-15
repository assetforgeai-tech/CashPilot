"""Provider installer manifest helpers."""

from __future__ import annotations

import json
import platform
from io import BytesIO
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from docker.errors import ImageNotFound

_GRASS_IMAGE = "cashpilot/grass-desktop"
_UPROCK_IMAGE = "cashpilot/uprock-mining"
_PROXYBASE_XYZ_IMAGE = "cashpilot/proxybase-xyz-cli"
_RUNNER = "ubuntu24.04"
_GRASS_ALLOWED_HOST = "files.grass.io"
_UPROCK_ALLOWED_HOST = "edge.uprock.com"
_PROXYBASE_XYZ_INSTALLER = "https://proxybase.xyz/install.sh"

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

def _safe_uprock_url(url: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != _UPROCK_ALLOWED_HOST
        or "UpRock-Mining-v" not in parsed.path
        or not parsed.path.endswith(".deb")
    ):
        raise ValueError("Uprock installer URL must point to an official https://edge.uprock.com/... .deb")

def resolve_installer_manifest(provider: str, manifest_url: str, platform_key: str | None = None) -> dict[str, str]:
    if provider == "uprock":
        _safe_uprock_url(manifest_url)
        filename = manifest_url.rstrip("/").rsplit("/", 1)[-1]
        version = filename.removeprefix("UpRock-Mining-").removesuffix(".deb")
        return {"platform": platform_key or "linux-x86_64", "version": version, "url": manifest_url}
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
    if provider == "uprock":
        return _ensure_image(client, _UPROCK_IMAGE, resolved, _uprock_dockerfile)
    if provider == "grass":
        return _ensure_image(client, _GRASS_IMAGE, resolved, _grass_dockerfile)
    raise ValueError(f"Installer image builds are not supported for {provider!r}")

def ensure_proxybase_xyz_image(client) -> str:
    return _ensure_image(
        client,
        _PROXYBASE_XYZ_IMAGE,
        {"version": "latest", "url": _PROXYBASE_XYZ_INSTALLER},
        _proxybase_xyz_dockerfile,
    )

def _ensure_image(client, image_base: str, resolved: dict[str, str], dockerfile_builder) -> str:
    version = "".join(c if c.isalnum() or c in ".-_" else "-" for c in resolved["version"])
    image = f"{image_base}:{version}-{_RUNNER}"
    try:
        client.images.get(image)
        return image
    except ImageNotFound:
        pass
    dockerfile = dockerfile_builder(resolved["url"])
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
 && apt-get install -y --no-install-recommends ca-certificates curl xvfb x11vnc fluxbox novnc websockify dbus-x11 python3-minimal \\
 && rm -rf /var/lib/apt/lists/*
ADD {deb_url} /tmp/grass-desktop.deb
RUN apt-get update \\
 && apt-get install -y --no-install-recommends /tmp/grass-desktop.deb xdotool \\
 && rm -rf /var/lib/apt/lists/* /tmp/grass-desktop.deb
RUN cat >/usr/local/bin/cashpilot-grass <<'SH' && chmod +x /usr/local/bin/cashpilot-grass
#!/bin/sh
set -eu
mkdir -p "$HOME"
rm -f /tmp/.X99-lock
Xvfb :99 -screen 0 1280x720x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
fluxbox >/tmp/fluxbox.log 2>&1 &
x11vnc -display :99 -forever -shared -nopw -listen 0.0.0.0 -xkb >/tmp/x11vnc.log 2>&1 &
websockify --web=/usr/share/novnc/ 6080 localhost:5900 >/tmp/novnc.log 2>&1 &
dbus-run-session sh -lc 'grass-desktop --no-sandbox || Grass --no-sandbox || /opt/Grass/grass-desktop --no-sandbox || /opt/Grass/grass --no-sandbox' &
grass_pid=$!
if [ "${{TRY_AUTOLOGIN:-true}}" = "true" ] && [ -n "${{USER_EMAIL:-}}" ] && [ -n "${{USER_PASSWORD:-}}" ]; then
  for _ in $(seq 1 90); do
    wid="$(DISPLAY=:99 xdotool search --onlyvisible --name '^Grass$' 2>/dev/null | head -n1 || true)"
    [ -n "$wid" ] && break
    sleep 1
  done
  if [ -n "${{wid:-}}" ]; then
    DISPLAY=:99 xdotool windowactivate --sync "$wid" || true
    sleep 2
    DISPLAY=:99 xdotool mousemove 150 226 click 1 key ctrl+a BackSpace type --delay 80 -- "$USER_EMAIL" || true
    DISPLAY=:99 xdotool mousemove 145 296 click 1 || true
    sleep 6
    DISPLAY=:99 xdotool mousemove 177 479 click 1 || true
    sleep 3
    DISPLAY=:99 xdotool mousemove 130 226 click 1 type --delay 80 -- "$USER_PASSWORD" || true
    DISPLAY=:99 xdotool mousemove 160 340 click 1 || true
    sleep 20
    date -u +%FT%TZ > "$HOME/.grass-configured"
  fi
fi
wait "$grass_pid"
SH
EXPOSE 6080
CMD ["cashpilot-grass"]
"""

def _uprock_dockerfile(deb_url: str) -> str:
    _safe_uprock_url(deb_url)
    return f"""FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive \\
    DISPLAY=:99 \\
    UPROCK_OS_CONSENT_SKIP=true
RUN apt-get update \\
 && apt-get install -y --no-install-recommends ca-certificates curl xvfb x11vnc fluxbox novnc websockify dbus-x11 \\
 && rm -rf /var/lib/apt/lists/*
ADD {deb_url} /tmp/uprock-mining.deb
RUN apt-get update \\
 && apt-get install -y --no-install-recommends /tmp/uprock-mining.deb \\
 && rm -rf /var/lib/apt/lists/* /tmp/uprock-mining.deb
EXPOSE 6080
CMD ["bash", "-lc", "set -e; mkdir -p /root/.local/share/UpRock; if [ -s /cashpilot/runtime-assets/uprock/credentials.json ]; then cp /cashpilot/runtime-assets/uprock/credentials.json /root/.local/share/UpRock/credentials.json; chmod 600 /root/.local/share/UpRock/credentials.json; fi; if [ -s /cashpilot/runtime-assets/uprock/main.db ]; then cp /cashpilot/runtime-assets/uprock/main.db /root/.local/share/UpRock/main.db; chmod 600 /root/.local/share/UpRock/main.db; fi; rm -f /tmp/.X99-lock; Xvfb :99 -screen 0 1200x800x24 -nolisten tcp >/tmp/xvfb.log 2>&1 & fluxbox >/tmp/fluxbox.log 2>&1 & x11vnc -display :99 -forever -shared -nopw -listen 0.0.0.0 -xkb >/tmp/x11vnc.log 2>&1 & websockify --web=/usr/share/novnc/ 6080 localhost:5900 >/tmp/novnc.log 2>&1 & dbus-run-session sh -lc 'uprock-mining'"]
"""

def _proxybase_xyz_dockerfile(installer_url: str) -> str:
    if installer_url != _PROXYBASE_XYZ_INSTALLER:
        raise ValueError("ProxyBase Markets installer URL is fixed to the official install.sh")
    return f"""FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \\
 && apt-get install -y --no-install-recommends ca-certificates curl \\
 && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL {installer_url} | sh \\
 && CLI="$(command -v proxybase-cli || true)" \\
 && if [ -z "$CLI" ]; then for p in "$HOME/.local/bin/proxybase-cli" "/root/.local/bin/proxybase-cli" "/usr/local/bin/proxybase-cli"; do if [ -x "$p" ]; then CLI="$p"; break; fi; done; fi \\
 && if [ -z "$CLI" ]; then echo "proxybase-cli not found" >&2; exit 1; fi \\
 && cp "$CLI" /usr/local/bin/proxybase-cli
"""

def proxybase_xyz_command() -> str:
    return (
        "sh -lc 'set -e; "
        "export HOME=/home/proxybase; mkdir -p \"$HOME/.proxybase\"; "
        'CLI="$(command -v proxybase-cli || true)"; '
        'if [ -z "$CLI" ]; then '
        'for p in "$HOME/.local/bin/proxybase-cli" "/root/.local/bin/proxybase-cli" "/usr/local/bin/proxybase-cli"; do '
        'if [ -x "$p" ]; then CLI="$p"; break; fi; done; fi; '
        'if [ -z "$CLI" ]; then echo "proxybase-cli not found" >&2; exit 1; fi; '
        'PHASE="${PROXYBASE_XYZ_PHRASE:?missing wallet phrase}"; '
        '"$CLI" wallet import "$PHASE"; '
        '"$CLI" login; '
        'if [ ! -s "$HOME/.proxybase/seller_config.json" ]; then printf \'{"upstream_proxies":[],"no_direct":false}\' > "$HOME/.proxybase/seller_config.json"; fi; '
        'exec "$CLI" seller start --foreground\''
    )
