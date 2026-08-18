"""EarnApp macOS runtime launcher."""

from __future__ import annotations

import io
import json
import os
import tarfile
import urllib.parse
from pathlib import Path
from typing import Any

RUNTIME_ROOT = Path(__file__).resolve().parent.parent / "vendor" / "earnapp-macos-runtime"
SCRIPT = "scripts/proxy-manager-macos-earnapp-smoke.sh"

def _r2_env_source() -> Path | None:
    candidates = [
        Path(__file__).resolve().parent.parent / "secrets" / "macos-r2.env",
        Path("/opt/cashpilot-src/secrets/macos-r2.env"),
        Path(r"D:\1. WORK_true\Internetincome\archive\earnapp-runtime-20260807\secrets\macos-r2.env"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def dashboard_device_title(uuid: str) -> str:
    raw = str(uuid or "").strip()
    tail = raw[-8:]
    if raw.startswith("sdk-mac-"):
        return f"sdk-mac-{tail}"
    if raw.startswith("sdk-node-"):
        return f"sdk-node-{tail}"
    if raw.startswith("sdk-"):
        return f"sdk-{tail}"
    return raw


def runtime_script() -> str:
    return (RUNTIME_ROOT / SCRIPT).read_text(encoding="utf-8")


def _host_runtime_root() -> str:
    return (os.getenv("CASHPILOT_RUNTIME_ROOT", "/opt/cashpilot-runtime").strip() or "/opt/cashpilot-runtime").rstrip("/")


def _proxy_url(proxy: dict[str, Any]) -> str:
    scheme = str(proxy.get("protocol") or proxy.get("scheme") or "socks5").lower()
    if scheme == "socks":
        scheme = "socks5"
    host = str(proxy.get("host") or proxy.get("endpoint_ip") or "").strip()
    port = int(proxy.get("port") or 0)
    if not host or port <= 0:
        raise RuntimeError("EarnApp macOS proxy host/port is required")
    username = str(proxy.get("username") or "")
    password = str(proxy.get("password") or "")
    auth = f"{urllib.parse.quote(username, safe='')}:{urllib.parse.quote(password, safe='')}@" if username else ""
    return f"{scheme}://{auth}{host}:{port}"


def _dns_ips(proxy: dict[str, Any]) -> str:
    dns = proxy.get("dns") if isinstance(proxy.get("dns"), dict) else {}
    values = dns.get("runtime_dns_ips") or dns.get("resolver_ips") or proxy.get("dns_ips") or []
    ips = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in ips:
            ips.append(text)
    return ",".join(ips or ["1.1.1.1", "8.8.8.8"])


def _instance_name(slug: str) -> str:
    digits = "".join(ch for ch in slug if ch.isdigit())
    ordinal = max(1, min(99, int(digits[-2:] or "1")))
    return f"earnapp-macos-{ordinal:03d}"


def _auth_state(deploy_credentials: dict[str, str]) -> bytes:
    def cookie(name: str, value: str, domain: str = "earnapp.com") -> dict[str, Any]:
        return {"name": name, "value": value, "domain": domain, "path": "/", "expires": -1, "httpOnly": False, "secure": True, "sameSite": "Lax"}

    cookies = [
        cookie("auth", "1"),
        cookie("auth-method", "google"),
        cookie("oauth-refresh-token", str(deploy_credentials.get("oauth_refresh_token") or ""), ".earnapp.com"),
        cookie("oauth-token", str(deploy_credentials.get("oauth_token") or ""), ".earnapp.com"),
        cookie("xsrf-token", str(deploy_credentials.get("xsrf_token") or ""), "earnapp.com"),
        cookie("brd_sess_id", str(deploy_credentials.get("brd_sess_id") or ""), ".earnapp.com"),
        cookie("cg_uuid", str(deploy_credentials.get("cg_uuid") or ""), ".earnapp.com"),
    ]
    return (json.dumps({"cookies": [c for c in cookies if c["value"]], "origins": []}, separators=(",", ":")) + "\n").encode()

def _r2_env_bytes() -> bytes:
    source = _r2_env_source()
    if source is not None:
        return source.read_bytes()
    return b""


def _bundle_tar(deploy_credentials: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        if RUNTIME_ROOT.exists():
            for path in RUNTIME_ROOT.rglob("*"):
                if not path.is_file():
                    continue
                arcname = str(path.relative_to(RUNTIME_ROOT))
                info = tar.gettarinfo(str(path), arcname=arcname)
                if path.suffix == ".sh":
                    info.mode = 0o755
                with path.open("rb") as fh:
                    tar.addfile(info, fh)
        script = runtime_script().encode()
        info = tarfile.TarInfo(SCRIPT)
        info.size = len(script)
        info.mode = 0o755
        tar.addfile(info, io.BytesIO(script))
        data = _auth_state(deploy_credentials)
        auth = tarfile.TarInfo("earnapp-auth-state.json")
        auth.size = len(data)
        auth.mode = 0o600
        tar.addfile(auth, io.BytesIO(data))
        r2_env = _r2_env_bytes()
        env = tarfile.TarInfo("macos-r2.env")
        env.size = len(r2_env)
        env.mode = 0o600
        tar.addfile(env, io.BytesIO(r2_env))
    buf.seek(0)
    return buf.getvalue()


def deploy_container(
    client,
    *,
    slug: str,
    proxy: dict[str, Any],
    labels: dict[str, str],
    deploy_credentials: dict[str, str],
):
    name = f"cashpilot-{slug}"
    runtime_volume = f"cashpilot-{slug}-macos-runtime"
    mac_root = f"{_host_runtime_root()}/dockur-macos"
    env = {
        "CASHPILOT_STANDALONE": "true",
        "ROOT_DIR": "/runtime",
        "MAC_TOOLS": "/runtime/tools/macos-on-vps",
        "MAC_ROOT": mac_root,
        "INSTANCE": _instance_name(slug),
        "GROUP_ID": slug.replace("_", "-")[:40] or "earnapp",
        "PROVIDER_ID": "earnapp-macos",
        "PM_PROVIDER_ID": "earnapp",
        "MANUAL_PROXY": _proxy_url(proxy),
        "MANUAL_PROXY_SCHEME": str(proxy.get("protocol") or proxy.get("scheme") or "socks5").lower(),
        "MANUAL_PROXY_DNS_IPS": _dns_ips(proxy),
        "TARGET_EGRESS_IP": str(proxy.get("egress_ip") or proxy.get("exit_ip") or ""),
        "EARNAPP_AUTH_STATE_FILE": "/runtime/earnapp-auth-state.json",
        "MACOS_R2_ENV_FILE": "/runtime/macos-r2.env",
        "FLEET_ID": "cashpilot",
        "FLEET_ENROLLMENT_TOKEN": "cashpilot-standalone",
        "HOST_ID": "cashpilot-worker",
    }
    command = [
        "/bin/sh",
        "-lc",
        (
            f"while [ ! -x /runtime/{SCRIPT} ]; do sleep 2; done; "
            "export DEBIAN_FRONTEND=noninteractive NODE_TLS_REJECT_UNAUTHORIZED=0; "
            "apt-get update -y && apt-get install -y bash ca-certificates curl jq docker.io "
            "openssh-client sshpass python3 coreutils iproute2 iptables docker-compose-v2; "
            f"exec bash /runtime/{SCRIPT} start"
        ),
    ]
    container = client.containers.run(
        image="ubuntu:24.04",
        name=name,
        environment=env,
        command=command,
        volumes={
            runtime_volume: {"bind": "/runtime", "mode": "rw"},
            "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
            mac_root: {"bind": mac_root, "mode": "rw"},
            "/opt/cashpilot-secrets/earnapp-macos": {"bind": "/runtime/secrets", "mode": "ro"},
        },
        devices=["/dev/kvm:/dev/kvm:rwm", "/dev/net/tun:/dev/net/tun:rwm"],
        pid_mode="host",
        cap_add=["NET_ADMIN", "SYS_ADMIN"],
        privileged=True,
        labels={**labels, "cashpilot.host-runtime": "qemu_macos"},
        detach=True,
        restart_policy={"Name": "always"},
    )
    container.put_archive("/runtime", _bundle_tar(deploy_credentials))
    return container
