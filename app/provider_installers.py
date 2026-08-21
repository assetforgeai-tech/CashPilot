"""Provider installer manifest helpers."""

from __future__ import annotations

from io import BytesIO
from urllib.parse import urlparse

from docker.errors import ImageNotFound

_UPROCK_IMAGE = "cashpilot/uprock-mining"
_PROXYBASE_XYZ_IMAGE = "cashpilot/proxybase-xyz-cli"
_RUNNER = "ubuntu24.04"
_UPROCK_ALLOWED_HOST = "edge.uprock.com"
_PROXYBASE_XYZ_INSTALLER = "https://proxybase.xyz/install.sh"


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
    raise ValueError(f"Installer manifests are not supported for {provider!r}")


def ensure_installer_image(client, provider: str, resolved: dict[str, str]) -> str:
    if provider == "uprock":
        return _ensure_image(client, _UPROCK_IMAGE, resolved, _uprock_dockerfile)
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
        'export HOME=/home/proxybase; mkdir -p "$HOME/.proxybase"; '
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
