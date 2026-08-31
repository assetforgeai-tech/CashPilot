#!/usr/bin/env python3
"""Restricted host-side LXD lifecycle agent for CashPilot EarnApp nodes."""

from __future__ import annotations

import argparse
import base64
import contextlib
import ipaddress
import json
import os
import re
import shlex
import socket
import socketserver
import subprocess
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

SOCKET_PATH = Path("/run/cashpilot-earnapp-agent/agent.sock")
INSTANCE_PREFIX = "cashpilot-earnapp-"
OFFICIAL_INSTALLER_URL = "https://brightdata.com/static/earnapp/install.sh"
OFFICIAL_INSTALLER_SHA256 = "2212fb2a39bc6f7fc176a39c43522a289bf837d5253e0b734cd4a395ddde82d0"
LXD_NETWORK = "lxdbr0"
_NODE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,120}$")
_DEVICE_RE = re.compile(r"^sdk-node-[0-9a-f]{32}$")
_MACHINE_RE = re.compile(r"^[0-9a-f]{32}$")
_STAGE_RE = re.compile(r"^[a-z][a-z0-9_]{1,64}$")
_LXD_ALLOC_LOCK = threading.Lock()


class AgentError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _run(
    args: list[str],
    *,
    input_bytes: bytes | None = None,
    check: bool = True,
    timeout: int = 900,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(args, input=input_bytes, capture_output=True, check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AgentError(f"host command failed: {args[0]}", 503) from exc
    if check and result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip().splitlines()
        raise AgentError(f"{args[0]} failed: {(detail[-1] if detail else 'command failed')[:240]}", 503)
    return result


def _json_command(args: list[str]) -> Any:
    try:
        return json.loads(_run(args).stdout.decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentError(f"{args[0]} returned invalid JSON", 503) from exc


def _required_text(payload: dict[str, Any], key: str, maximum: int = 512) -> str:
    value = str(payload.get(key) or "").strip()
    if not value or len(value) > maximum:
        raise AgentError(f"{key} is required")
    return value


def _bounded_int(payload: dict[str, Any], key: str, minimum: int, maximum: int) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        raise AgentError(f"{key} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise AgentError(f"{key} must be an integer") from exc
    if str(value).strip() != str(number) or not minimum <= number <= maximum:
        raise AgentError(f"{key} must be between {minimum} and {maximum}")
    return number


def instance_name(logical_node_id: str) -> str:
    value = str(logical_node_id or "").strip()
    if not _NODE_RE.fullmatch(value):
        raise AgentError("invalid EarnApp logical node id")
    return INSTANCE_PREFIX + value


def _proxy(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("proxy")
    if not isinstance(value, dict):
        raise AgentError("proxy is required")
    protocol = str(value.get("protocol") or "").strip().lower()
    if protocol not in {"http", "socks5"}:
        raise AgentError("proxy protocol is invalid")
    if str(value.get("ip_type") or "").strip().lower() != "residential":
        raise AgentError("EarnApp requires a residential proxy")
    host = _required_text(value, "host", 253)
    if not re.fullmatch(r"[A-Za-z0-9._:-]+", host):
        raise AgentError("proxy host is invalid")
    port = _bounded_int(value, "port", 1, 65535)
    username = str(value.get("username") or "")
    password = str(value.get("password") or "")
    if "\x00" in username or "\x00" in password or len(username) > 8192 or len(password) > 8192:
        raise AgentError("proxy credentials are invalid")
    return {
        "proxy_id": _bounded_int(value, "proxy_id", 1, 2_147_483_647),
        "host": host,
        "port": port,
        "protocol": protocol,
        "username": username,
        "password": password,
        "ip_type": "residential",
    }


def validate_deploy(logical_node_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if str(payload.get("logical_node_id") or logical_node_id) != logical_node_id:
        raise AgentError("logical node id does not match the request")
    device_id = _required_text(payload, "device_id", 96)
    if not _DEVICE_RE.fullmatch(device_id):
        raise AgentError("device_id is invalid")
    identity = payload.get("identity")
    if not isinstance(identity, dict):
        raise AgentError("identity is required")
    if (
        str(identity.get("platform") or "") != "ubuntu"
        or str(identity.get("device_id") or "") != device_id
        or not _MACHINE_RE.fullmatch(str(identity.get("machine_id") or ""))
        or not str(identity.get("hostname") or "").startswith("earnapp-")
        or str(identity.get("arch") or "") != "amd64"
    ):
        raise AgentError("EarnApp Ubuntu identity is invalid")
    return {
        "logical_node_id": logical_node_id,
        "generation": _bounded_int(payload, "generation", 1, 2_147_483_647),
        "account_id": _bounded_int(payload, "account_id", 1, 2_147_483_647),
        "device_id": device_id,
        "identity": dict(identity),
        "proxy": _proxy(payload),
        "lxd_cpu": _bounded_int(payload, "lxd_cpu", 1, 64),
        "lxd_memory_mib": _bounded_int(payload, "lxd_memory_mib", 128, 65536),
    }


def _cas(logical_node_id: str, payload: dict[str, Any]) -> tuple[int, str]:
    if str(payload.get("logical_node_id") or logical_node_id) != logical_node_id:
        raise AgentError("logical node id does not match the request")
    generation = _bounded_int(payload, "generation", 1, 2_147_483_647)
    device_id = _required_text(payload, "device_id", 96)
    if not _DEVICE_RE.fullmatch(device_id):
        raise AgentError("device_id is invalid")
    return generation, device_id


def _binding_version(payload: dict[str, Any]) -> str:
    value = str(payload.get("binding_version") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{8,128}", value):
        raise AgentError("binding_version is invalid")
    return value


def _artifact_status(name: str) -> dict[str, Any]:
    command = (
        "python3 - <<'PY'\n"
        "import json, pathlib\n"
        "root=pathlib.Path('/etc/cashpilot/earnapp')\n"
        "marker=root/'.cashpilot-binding-version'\n"
        "print(json.dumps({'binding_version': marker.read_text().strip() if marker.is_file() else '', "
        "'previous_present': (root/'proxy.env.cashpilot-prev').is_file(), "
        "'candidate_present': (root/'proxy.env.cashpilot-new').is_file()}))\n"
        "PY"
    )
    result = _run(["lxc", "exec", name, "--", "sh", "-lc", command], timeout=30)
    try:
        value = json.loads(result.stdout.decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentError("EarnApp binding status is invalid", 503) from exc
    if not isinstance(value, dict):
        raise AgentError("EarnApp binding status is invalid", 503)
    return {
        "binding_version": str(value.get("binding_version") or ""),
        "previous_present": bool(value.get("previous_present")),
        "candidate_present": bool(value.get("candidate_present")),
    }


def guest_bootstrap_script(payload: dict[str, Any]) -> str:
    """Return a secret-free bootstrap script; credentials arrive in an env file."""
    identity = payload["identity"]
    machine_id = shlex.quote(str(identity["machine_id"]))
    hostname = shlex.quote(str(identity["hostname"]))
    device_id = shlex.quote(str(payload["device_id"]))
    return f"""#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
install -d -m 0700 /etc/cashpilot/earnapp /etc/earnapp
STAGE_FILE=/etc/cashpilot/earnapp/bootstrap.stage
stage() {{ printf '%s\\n' "$1" >"$STAGE_FILE"; }}
stage apt_update
apt-get update
stage apt_install
apt-get install -y ca-certificates curl iproute2 iptables procps python3 redsocks
# Ubuntu enables the package's stock listener on port 12345. CashPilot owns
# that listener with its generated, credential-scoped service instead.
systemctl disable --now redsocks.service 2>/dev/null || true
stage identity
printf '%s\\n' {machine_id} >/etc/machine-id
ln -sfn /etc/machine-id /var/lib/dbus/machine-id
printf '%s\\n' {hostname} >/etc/hostname
hostname {hostname}
printf '%s\\n' {device_id} >/etc/earnapp/uuid
id -u cashpilot-redsocks >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin cashpilot-redsocks
chown root:cashpilot-redsocks /etc/cashpilot/earnapp/proxy.env
chmod 0640 /etc/cashpilot/earnapp/proxy.env
stage proxy_helper
cat >/usr/local/sbin/cashpilot-earnapp-proxy <<'PROXY'
#!/usr/bin/env python3
import base64
import os


def decoded(name):
    return base64.b64decode(os.environ[name], validate=True).decode("utf-8")


def quoted(value):
    return (
        value.replace("\\\\", "\\\\\\\\")
        .replace('"', '\\\\"')
        .replace("\\r", "\\\\r")
        .replace("\\n", "\\\\n")
    )


protocol = os.environ["PROXY_PROTOCOL"]
kind = "socks5" if protocol == "socks5" else "http-connect"
host = quoted(os.environ["PROXY_ENDPOINT_IPV4"])
username = quoted(decoded("PROXY_USERNAME_B64"))
password = quoted(decoded("PROXY_PASSWORD_B64"))
port = int(os.environ["PROXY_PORT"])
runtime = os.environ["RUNTIME_DIRECTORY"]
path = os.path.join(runtime, "redsocks.conf")
config = (
    "base {{ log_debug = off; log_info = off; log = stderr; daemon = off; redirector = iptables; }}\\n"
    "redsocks {{ local_ip = 127.0.0.1; local_port = 12345; ip = \\\""
    + host
    + "\\\"; port = "
    + str(port)
    + "; type = "
    + kind
    + ";\\nlogin = \\\""
    + username
    + "\\\"; password = \\\""
    + password
    + "\\\"; }}\\n"
    + "dnstc {{ local_ip = 127.0.0.1; local_port = 1053; }}\\n"
)
with open(path, "w", encoding="utf-8", newline="\\n") as handle:
    handle.write(config)
os.chmod(path, 0o600)
os.execv("/usr/sbin/redsocks", ["redsocks", "-c", path])
PROXY
chmod 0755 /usr/local/sbin/cashpilot-earnapp-proxy
stage proxy_rules
cat >/usr/local/sbin/cashpilot-earnapp-proxy-rules <<'RULES'
#!/usr/bin/env bash
set -euo pipefail
. /etc/cashpilot/earnapp/proxy.env
CHAIN=CASH_PILOT_EARNAPP
FILTER_CHAIN=CASH_PILOT_EARNAPP_FILTER
ALLOW_CHAIN=CASH_PILOT_EARNAPP_ALLOW
TEMP_FILTER_CHAIN=CASH_PILOT_EARNAPP_TEMP
V6_FILTER_CHAIN=CASH_PILOT_EARNAPP_V6_FILTER
V6_TEMP_FILTER_CHAIN=CASH_PILOT_EARNAPP_V6_TEMP

remove_jumps() {{
  while iptables -t nat -C OUTPUT -p tcp -j "$CHAIN" >/dev/null 2>&1; do
    iptables -t nat -D OUTPUT -p tcp -j "$CHAIN"
  done
  while iptables -t nat -C OUTPUT -p udp -j "$CHAIN" >/dev/null 2>&1; do
    iptables -t nat -D OUTPUT -p udp -j "$CHAIN"
  done
  while iptables -C OUTPUT -j "$FILTER_CHAIN" >/dev/null 2>&1; do
    iptables -D OUTPUT -j "$FILTER_CHAIN"
  done
  while iptables -C OUTPUT -j "$TEMP_FILTER_CHAIN" >/dev/null 2>&1; do
    iptables -D OUTPUT -j "$TEMP_FILTER_CHAIN"
  done
  while ip6tables -C OUTPUT -j "$V6_FILTER_CHAIN" >/dev/null 2>&1; do
    ip6tables -D OUTPUT -j "$V6_FILTER_CHAIN"
  done
  while ip6tables -C OUTPUT -j "$V6_TEMP_FILTER_CHAIN" >/dev/null 2>&1; do
    ip6tables -D OUTPUT -j "$V6_TEMP_FILTER_CHAIN"
  done
}}

if [ "${{1:-apply}}" = remove ]; then
  remove_jumps
  iptables -t nat -F "$CHAIN" >/dev/null 2>&1 || true
  iptables -t nat -X "$CHAIN" >/dev/null 2>&1 || true
  iptables -F "$ALLOW_CHAIN" >/dev/null 2>&1 || true
  iptables -X "$ALLOW_CHAIN" >/dev/null 2>&1 || true
  iptables -F "$FILTER_CHAIN" >/dev/null 2>&1 || true
  iptables -X "$FILTER_CHAIN" >/dev/null 2>&1 || true
  iptables -F "$TEMP_FILTER_CHAIN" >/dev/null 2>&1 || true
  iptables -X "$TEMP_FILTER_CHAIN" >/dev/null 2>&1 || true
  ip6tables -F "$V6_FILTER_CHAIN" >/dev/null 2>&1 || true
  ip6tables -X "$V6_FILTER_CHAIN" >/dev/null 2>&1 || true
  ip6tables -F "$V6_TEMP_FILTER_CHAIN" >/dev/null 2>&1 || true
  ip6tables -X "$V6_TEMP_FILTER_CHAIN" >/dev/null 2>&1 || true
  exit 0
fi

# Install a temporary deny guard before rebuilding any legacy chain. If this
# script fails, the guard intentionally remains fail-closed for the next retry.
iptables -N "$TEMP_FILTER_CHAIN" >/dev/null 2>&1 || true
iptables -I "$TEMP_FILTER_CHAIN" 1 -j DROP
iptables -I "$TEMP_FILTER_CHAIN" 1 -o lo -j RETURN
while iptables -C OUTPUT -j "$TEMP_FILTER_CHAIN" >/dev/null 2>&1; do
  iptables -D OUTPUT -j "$TEMP_FILTER_CHAIN"
done
iptables -I OUTPUT 1 -j "$TEMP_FILTER_CHAIN"

ip6tables -N "$V6_TEMP_FILTER_CHAIN" >/dev/null 2>&1 || true
ip6tables -I "$V6_TEMP_FILTER_CHAIN" 1 -j DROP
ip6tables -I "$V6_TEMP_FILTER_CHAIN" 1 -o lo -j RETURN
while ip6tables -C OUTPUT -j "$V6_TEMP_FILTER_CHAIN" >/dev/null 2>&1; do
  ip6tables -D OUTPUT -j "$V6_TEMP_FILTER_CHAIN"
done
ip6tables -I OUTPUT 1 -j "$V6_TEMP_FILTER_CHAIN"

# Rebuild the permanent filter deterministically. This also migrates guests
# where the allow-chain jump was appended after a legacy terminal DROP.
while iptables -C OUTPUT -j "$FILTER_CHAIN" >/dev/null 2>&1; do
  iptables -D OUTPUT -j "$FILTER_CHAIN"
done
iptables -N "$FILTER_CHAIN" >/dev/null 2>&1 || true
iptables -F "$FILTER_CHAIN"
iptables -N "$ALLOW_CHAIN" >/dev/null 2>&1 || true
iptables -F "$ALLOW_CHAIN"
iptables -A "$ALLOW_CHAIN" -o lo -j ACCEPT
iptables -A "$ALLOW_CHAIN" -m owner --uid-owner cashpilot-redsocks -j ACCEPT
iptables -A "$ALLOW_CHAIN" -p tcp -d "$PROXY_ENDPOINT_IPV4" --dport "$PROXY_PORT" -j ACCEPT
for subnet in 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/4 240.0.0.0/4; do
  iptables -A "$ALLOW_CHAIN" -d "$subnet" -j ACCEPT
done
iptables -A "$FILTER_CHAIN" -o lo -j RETURN
iptables -A "$FILTER_CHAIN" -j "$ALLOW_CHAIN"
iptables -A "$FILTER_CHAIN" -p udp -j REJECT --reject-with icmp-port-unreachable
iptables -A "$FILTER_CHAIN" -p tcp -j REJECT --reject-with tcp-reset
iptables -A "$FILTER_CHAIN" -j DROP
iptables -I OUTPUT 1 -j "$FILTER_CHAIN"

iptables -t nat -N "$CHAIN" >/dev/null 2>&1 || true
iptables -t nat -F "$CHAIN"
iptables -t nat -A "$CHAIN" -o lo -j RETURN
iptables -t nat -A "$CHAIN" -m owner --uid-owner cashpilot-redsocks -j RETURN
for subnet in 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/4 240.0.0.0/4; do
  iptables -t nat -A "$CHAIN" -d "$subnet" -j RETURN
done
iptables -t nat -A "$CHAIN" -p tcp -d "$PROXY_ENDPOINT_IPV4" --dport "$PROXY_PORT" -j RETURN
iptables -t nat -A "$CHAIN" -p udp --dport 53 -j REDIRECT --to-ports 1053
iptables -t nat -A "$CHAIN" -p tcp -j REDIRECT --to-ports 12345
while iptables -t nat -C OUTPUT -p tcp -j "$CHAIN" >/dev/null 2>&1; do
  iptables -t nat -D OUTPUT -p tcp -j "$CHAIN"
done
while iptables -t nat -C OUTPUT -p udp -j "$CHAIN" >/dev/null 2>&1; do
  iptables -t nat -D OUTPUT -p udp -j "$CHAIN"
done
iptables -t nat -I OUTPUT 1 -p tcp -j "$CHAIN"
iptables -t nat -I OUTPUT 1 -p udp -j "$CHAIN"

# Disable IPv6 where possible and keep a filter fallback when the sysctl is
# read-only inside the guest. No IPv6 packet may bypass the proxy.
sysctl -w net.ipv6.conf.all.disable_ipv6=1 >/dev/null 2>&1 || true
sysctl -w net.ipv6.conf.default.disable_ipv6=1 >/dev/null 2>&1 || true
while ip6tables -C OUTPUT -j "$V6_FILTER_CHAIN" >/dev/null 2>&1; do
  ip6tables -D OUTPUT -j "$V6_FILTER_CHAIN"
done
ip6tables -N "$V6_FILTER_CHAIN" >/dev/null 2>&1 || true
ip6tables -F "$V6_FILTER_CHAIN"
ip6tables -A "$V6_FILTER_CHAIN" -o lo -j RETURN
ip6tables -A "$V6_FILTER_CHAIN" -j DROP
ip6tables -I OUTPUT 1 -j "$V6_FILTER_CHAIN"

while iptables -C OUTPUT -j "$TEMP_FILTER_CHAIN" >/dev/null 2>&1; do
  iptables -D OUTPUT -j "$TEMP_FILTER_CHAIN"
done
iptables -F "$TEMP_FILTER_CHAIN"
iptables -X "$TEMP_FILTER_CHAIN"
while ip6tables -C OUTPUT -j "$V6_TEMP_FILTER_CHAIN" >/dev/null 2>&1; do
  ip6tables -D OUTPUT -j "$V6_TEMP_FILTER_CHAIN"
done
ip6tables -F "$V6_TEMP_FILTER_CHAIN"
ip6tables -X "$V6_TEMP_FILTER_CHAIN"
RULES
chmod 0755 /usr/local/sbin/cashpilot-earnapp-proxy-rules
stage proxy_service
cat >/etc/systemd/system/cashpilot-earnapp-proxy.service <<'UNIT'
[Unit]
Description=CashPilot EarnApp proxy
After=network-online.target
[Service]
Type=simple
User=cashpilot-redsocks
Group=cashpilot-redsocks
EnvironmentFile=/etc/cashpilot/earnapp/proxy.env
RuntimeDirectory=cashpilot-earnapp
RuntimeDirectoryMode=0750
ExecStartPre=+/usr/local/sbin/cashpilot-earnapp-proxy-rules apply
ExecStart=/usr/local/sbin/cashpilot-earnapp-proxy
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now cashpilot-earnapp-proxy.service
stage proxy_ready
proxy_ready=false
for _ in $(seq 1 30); do
  if systemctl is-active --quiet cashpilot-earnapp-proxy.service && \
     curl --fail --silent --show-error --connect-timeout 5 --max-time 10 https://api.ipify.org >/dev/null; then
    proxy_ready=true
    break
  fi
  sleep 1
done
if [ "$proxy_ready" != true ]; then
  echo "EarnApp transparent proxy did not become ready" >&2
  exit 1
fi
stage installer_download
OFFICIAL_INSTALLER_SHA256={OFFICIAL_INSTALLER_SHA256}
installer=/tmp/earnapp-install.sh
trap 'rm -f "$installer"' EXIT
curl --fail --silent --show-error --location {OFFICIAL_INSTALLER_URL} -o "$installer"
stage installer_verify
printf '%s  %s\\n' "$OFFICIAL_INSTALLER_SHA256" "$installer" | sha256sum -c - || {{
  echo "EarnApp installer checksum mismatch" >&2
  exit 1
}}
stage installer_execute
bash "$installer" -y
rm -f "$installer"
trap - EXIT
stage identity_check
test "$(cat /etc/earnapp/uuid)" = {device_id} || {{
  echo "EarnApp installer changed the persisted device identity" >&2
  exit 1
}}
stage register_retry
earnapp_version=$(tr -d '\\r\\n' </etc/earnapp/ver)
earnapp_serial=$(sha1sum /etc/machine-id | awk '{{print $1}}')
EARNAPP_REGISTER_ATTEMPTS="${{EARNAPP_REGISTER_ATTEMPTS:-10}}"
EARNAPP_REGISTER_RETRY_SECONDS="${{EARNAPP_REGISTER_RETRY_SECONDS:-15}}"

# Registration is deliberately performed inside the guest after the relay and
# fail-closed firewall are ready.  A successful HTTP response alone is not
# enough: the exact UUID must also be acknowledged by the registration API.
register_earnapp_device() {{
  local attempt install_body linked_body
  for attempt in $(seq 1 "$EARNAPP_REGISTER_ATTEMPTS"); do
    install_body=$(mktemp)
    linked_body=$(mktemp)
    if curl --fail --silent --show-error --connect-timeout 15 --max-time 45 \
      -H 'Content-Type: application/json' \
      -o "$install_body" \
      "https://client.earnapp.com/install_device?uuid={device_id}&version=${{earnapp_version}}&arch=x64&appid=node_earnapp.com&os=Ubuntu" \
      --data "$(printf '{{\"serial\":\"%s\"}}' "$earnapp_serial")" \
      && curl --fail --silent --show-error --connect-timeout 15 --max-time 45 \
      -o "$linked_body" \
      "https://client.earnapp.com/is_linked?uuid={device_id}&version=${{earnapp_version}}&appid=node_earnapp.com" \
      && python3 - "$install_body" "$linked_body" <<'PY'
import json
import sys

def read(path):
    with open(path, encoding="utf-8") as handle:
        value = json.load(handle)
    return value if isinstance(value, dict) else {{}}

install = read(sys.argv[1])
linked = read(sys.argv[2])
install_ok = install.get("ok") in (True, 1, "1")
linked_ok = linked.get("linked") is True
raise SystemExit(0 if install_ok and linked_ok else 1)
PY
    then
      rm -f "$install_body" "$linked_body"
      return 0
    fi
    rm -f "$install_body" "$linked_body"
    if [ "$attempt" -lt "$EARNAPP_REGISTER_ATTEMPTS" ]; then
      sleep "$EARNAPP_REGISTER_RETRY_SECONDS"
    fi
  done
  echo "install_device did not reach linked state" >&2
  return 1
}}

register_earnapp_device
systemctl restart earnapp.service
stage service_start
systemctl enable --now earnapp.service earnapp_upgrader.service
stage complete
    """


class Controller:
    def _exists(self, name: str) -> bool:
        return _run(["lxc", "info", name], check=False, timeout=30).returncode == 0

    def _status(self, name: str) -> str:
        value = _json_command(["lxc", "list", name, "--format=json"])
        return str(value[0].get("status") or "").lower() if isinstance(value, list) and value else "missing"

    def _config(self, name: str) -> dict[str, Any]:
        value = _json_command(["lxc", "query", f"/1.0/instances/{name}"])
        return value if isinstance(value, dict) else {}

    def _wait_ready(self, name: str) -> None:
        _run(["lxc", "exec", name, "--", "cloud-init", "status", "--wait"], timeout=900)

    def _set_metadata(self, name: str, payload: dict[str, Any]) -> None:
        values = {
            "user.cashpilot.provider": "earnapp",
            "user.cashpilot.earnapp.logical_node_id": str(payload["logical_node_id"]),
            "user.cashpilot.earnapp.generation": str(payload["generation"]),
            "user.cashpilot.earnapp.account_id": str(payload["account_id"]),
            "user.cashpilot.earnapp.device_id": str(payload["device_id"]),
            "user.cashpilot.earnapp.proxy_id": str(payload["proxy"]["proxy_id"]),
        }
        for key, value in values.items():
            _run(["lxc", "config", "set", name, key, value], timeout=30)

    def _set_proxy_metadata(self, name: str, proxy_id: int) -> None:
        _run(
            ["lxc", "config", "set", name, "user.cashpilot.earnapp.proxy_id", str(int(proxy_id))],
            timeout=30,
        )

    def _assigned(self, logical_node_id: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        name = instance_name(logical_node_id)
        if not self._exists(name):
            raise AgentError("EarnApp LXD node not found", 404)
        config = self._config(name)
        values = config.get("config") if isinstance(config.get("config"), dict) else {}
        generation, device_id = _cas(logical_node_id, payload)
        expected = (
            logical_node_id,
            generation,
            device_id,
        )
        actual = (
            str(values.get("user.cashpilot.earnapp.logical_node_id") or ""),
            int(values.get("user.cashpilot.earnapp.generation") or 0),
            str(values.get("user.cashpilot.earnapp.device_id") or ""),
        )
        if str(values.get("user.cashpilot.provider") or "") != "earnapp" or actual != expected:
            raise AgentError("EarnApp node assignment conflict", 409)
        return name, {"logical_node_id": logical_node_id, "generation": generation, "device_id": device_id}

    def _verify_lxd_contract(self, config: dict[str, Any], payload: dict[str, Any]) -> None:
        values = config.get("config") if isinstance(config.get("config"), dict) else {}
        expected = {
            "limits.cpu": str(payload["lxd_cpu"]),
            "limits.memory": f"{payload['lxd_memory_mib']}MiB",
            "limits.memory.enforce": "hard",
            "limits.memory.swap": "false",
            "boot.autostart": "true",
        }
        drift = [key for key, value in expected.items() if str(values.get(key) or "") != value]
        if drift:
            raise AgentError(f"EarnApp LXD runtime contract drift: {', '.join(drift)}", 409)

    def _evidence(self, name: str, assignment: dict[str, Any]) -> dict[str, Any]:
        running = self._status(name) == "running"
        result = {
            "instance_id": name,
            "running": running,
            "online": False,
            "runtime_backend": "lxd",
            "device_id": assignment["device_id"],
            "observed_egress_ip": "",
            "probe_ok": False,
        }
        if not running:
            return result
        command = (
            "python3 - <<'PY'\n"
            "import json, pathlib, subprocess\n"
            "def active(unit):\n"
            " p=subprocess.run(['systemctl','is-active','--quiet',unit])\n"
            " return p.returncode == 0\n"
            "uuid=pathlib.Path('/etc/earnapp/uuid').read_text().strip() if pathlib.Path('/etc/earnapp/uuid').is_file() else ''\n"
            "ver=pathlib.Path('/etc/earnapp/ver').read_text().strip() if pathlib.Path('/etc/earnapp/ver').is_file() else ''\n"
            "print(json.dumps({'device_id':uuid,'version':ver,'earnapp_active':active('earnapp.service'),'proxy_active':active('cashpilot-earnapp-proxy.service')}))\n"
            "PY"
        )
        probe = _run(["lxc", "exec", name, "--", "sh", "-lc", command], check=False, timeout=30)
        try:
            data = json.loads(probe.stdout.decode()) if probe.returncode == 0 else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            result.update({key: data[key] for key in ("version", "earnapp_active", "proxy_active") if key in data})
            result["online"] = bool(data.get("earnapp_active") and data.get("proxy_active"))
        observed = self._probe_egress(name)
        result["observed_egress_ip"] = observed
        result["probe_ok"] = bool(observed)
        return result

    def _write_guest_file(self, name: str, path: str, value: bytes, mode: str = "0600") -> None:
        command = f"umask 077; install -d -m 0700 {shlex.quote(str(Path(path).parent))}; cat > {shlex.quote(path)}; chmod {mode} {shlex.quote(path)}"
        _run(["lxc", "exec", name, "--", "sh", "-lc", command], input_bytes=value, timeout=60)

    def _configure_guest(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        proxy = payload["proxy"]
        env = self._proxy_env(proxy)
        script = guest_bootstrap_script(payload).encode()
        self._write_guest_file(name, "/etc/cashpilot/earnapp/proxy.env", env)
        self._write_guest_file(name, "/root/cashpilot-earnapp-bootstrap.sh", script, "0700")
        try:
            _run(["lxc", "exec", name, "--", "bash", "/root/cashpilot-earnapp-bootstrap.sh"], timeout=1800)
        except AgentError as exc:
            stage_result = _run(
                [
                    "lxc",
                    "exec",
                    name,
                    "--",
                    "sh",
                    "-lc",
                    "cat /etc/cashpilot/earnapp/bootstrap.stage 2>/dev/null || true",
                ],
                check=False,
                timeout=30,
            )
            stage_name = (stage_result.stdout.decode(errors="replace").strip().splitlines() or [""])[-1].strip()
            if _STAGE_RE.fullmatch(stage_name):
                raise AgentError(f"EarnApp guest bootstrap failed at {stage_name}", exc.status) from exc
            raise
        result = _run(
            ["lxc", "exec", name, "--", "sh", "-lc", "earnapp --version 2>/dev/null || true"],
            timeout=30,
        )
        return {"version": result.stdout.decode(errors="replace").strip()}

    @staticmethod
    def _parse_json_result(result: subprocess.CompletedProcess[bytes], description: str) -> Any:
        if result.returncode != 0:
            raise AgentError(f"{description} failed", 503)
        try:
            return json.loads(result.stdout.decode(errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AgentError(f"{description} returned invalid JSON", 503) from exc

    def _pin_instance_ip(self, name: str, address: str) -> None:
        """Pin the inherited default-profile NIC before the first boot."""
        try:
            parsed = ipaddress.ip_address(str(address))
        except ValueError as exc:
            raise AgentError("EarnApp LXD IPv4 address is invalid", 503) from exc
        if not isinstance(parsed, ipaddress.IPv4Address):
            raise AgentError("EarnApp LXD IPv4 address is invalid", 503)
        config = self._config(name)
        devices = config.get("devices") if isinstance(config.get("devices"), dict) else {}
        eth0 = devices.get("eth0") if isinstance(devices.get("eth0"), dict) else None
        if eth0 is None:
            _run(["lxc", "config", "device", "override", name, "eth0", f"ipv4.address={parsed}"], timeout=30)
        elif str(eth0.get("ipv4.address") or "") != str(parsed):
            _run(["lxc", "config", "device", "set", name, "eth0", "ipv4.address", str(parsed)], timeout=30)

    def _lxd_bridge_ipv4(self) -> ipaddress.IPv4Interface:
        network_result = _run(
            ["lxc", "network", "get", LXD_NETWORK, "ipv4.address"],
            check=False,
            timeout=30,
        )
        if network_result.returncode != 0:
            raise AgentError("EarnApp LXD bridge has no IPv4 subnet", 503)
        try:
            bridge = ipaddress.ip_interface(network_result.stdout.decode().strip().strip('"'))
        except (UnicodeDecodeError, ValueError) as exc:
            raise AgentError("EarnApp LXD bridge IPv4 subnet is invalid", 503) from exc
        if not isinstance(bridge, ipaddress.IPv4Interface) or bridge.network.prefixlen > 30:
            raise AgentError("EarnApp LXD bridge IPv4 subnet is too small", 503)
        return bridge

    def _configure_instance_network(self, name: str, address: str) -> None:
        """Give cloud-init the static IPv4 route that LXD's NIC pin does not install."""
        try:
            parsed = ipaddress.ip_address(str(address))
        except ValueError as exc:
            raise AgentError("EarnApp LXD IPv4 address is invalid", 503) from exc
        bridge = self._lxd_bridge_ipv4()
        network = bridge.network
        if (
            not isinstance(parsed, ipaddress.IPv4Address)
            or parsed not in network
            or parsed in {network.network_address, network.broadcast_address, bridge.ip}
        ):
            raise AgentError("EarnApp LXD IPv4 address is outside the bridge subnet", 503)
        config = (
            "version: 2\n"
            "ethernets:\n"
            "  eth0:\n"
            "    dhcp4: false\n"
            f"    addresses: [{parsed}/{network.prefixlen}]\n"
            "    routes:\n"
            "      - to: default\n"
            f"        via: {bridge.ip}\n"
            "    nameservers:\n"
            "      addresses: [1.1.1.1, 8.8.8.8]\n"
        )
        _run(["lxc", "config", "set", name, "cloud-init.network-config", config], timeout=30)

    def _allocate_lxd_ipv4(self, name: str) -> str:
        """Choose a collision-free address on the managed LXD bridge."""
        del name  # The address pool is shared; the instance name is not a key.
        bridge = self._lxd_bridge_ipv4()
        network = bridge.network

        used: set[ipaddress.IPv4Address] = {network.network_address, network.broadcast_address}
        used.add(bridge.ip)

        leases = self._parse_json_result(
            _run(["lxc", "network", "list-leases", LXD_NETWORK, "--format=json"], check=False, timeout=30),
            "EarnApp LXD bridge leases",
        )
        if not isinstance(leases, list):
            raise AgentError("EarnApp LXD bridge leases are invalid", 503)
        for row in leases:
            if not isinstance(row, dict):
                continue
            try:
                address = ipaddress.ip_address(str(row.get("address") or ""))
            except ValueError:
                continue
            if isinstance(address, ipaddress.IPv4Address):
                used.add(address)

        instances = self._parse_json_result(
            _run(["lxc", "list", "--format=json"], check=False, timeout=30),
            "EarnApp LXD instance inventory",
        )
        if not isinstance(instances, list):
            raise AgentError("EarnApp LXD instance inventory is invalid", 503)
        for instance in instances:
            if not isinstance(instance, dict):
                continue
            device_sets = (
                instance.get("devices") if isinstance(instance.get("devices"), dict) else {},
                instance.get("expanded_devices") if isinstance(instance.get("expanded_devices"), dict) else {},
            )
            for devices in device_sets:
                for device in devices.values():
                    if not isinstance(device, dict) or str(device.get("network") or "") != LXD_NETWORK:
                        continue
                    try:
                        address = ipaddress.ip_address(str(device.get("ipv4.address") or ""))
                    except ValueError:
                        continue
                    if isinstance(address, ipaddress.IPv4Address):
                        used.add(address)

            state = instance.get("state") if isinstance(instance.get("state"), dict) else {}
            state_network = state.get("network") if isinstance(state.get("network"), dict) else {}
            for row in state_network.values():
                if not isinstance(row, dict):
                    continue
                for address_row in row.get("addresses") or []:
                    if not isinstance(address_row, dict) or str(address_row.get("family") or "") != "inet":
                        continue
                    try:
                        address = ipaddress.ip_address(str(address_row.get("address") or ""))
                    except ValueError:
                        continue
                    if isinstance(address, ipaddress.IPv4Address):
                        used.add(address)

        for candidate in network.hosts():
            if candidate not in used:
                return str(candidate)
        raise AgentError("EarnApp LXD bridge has no free IPv4 address", 503)

    @staticmethod
    def _resolve_proxy_ipv4(host: str) -> str:
        try:
            values = socket.getaddrinfo(host, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
        except (OSError, socket.gaierror) as exc:
            raise AgentError("EarnApp proxy endpoint could not be resolved", 503) from exc
        addresses = sorted(
            {str(ipaddress.IPv4Address(item[4][0])) for item in values if len(item) >= 5 and item[4] and item[4][0]}
        )
        if not addresses:
            raise AgentError("EarnApp proxy endpoint did not resolve to IPv4", 503)
        return addresses[0]

    @staticmethod
    def _proxy_env(proxy: dict[str, Any]) -> bytes:
        def encoded(value: Any) -> str:
            return base64.b64encode(str(value).encode("utf-8")).decode("ascii")

        endpoint_value = str(proxy.get("endpoint_ip") or "").strip()
        try:
            endpoint_ip = str(ipaddress.IPv4Address(endpoint_value)) if endpoint_value else ""
        except ipaddress.AddressValueError as exc:
            raise AgentError("EarnApp proxy endpoint_ip is invalid") from exc
        if not endpoint_ip:
            endpoint_ip = Controller._resolve_proxy_ipv4(str(proxy["host"]))

        lines = (
            f"PROXY_ENDPOINT_IPV4={endpoint_ip}\n",
            f"PROXY_PORT={int(proxy['port'])}\n",
            f"PROXY_PROTOCOL={str(proxy['protocol'])}\n",
            f"PROXY_USERNAME_B64={encoded(proxy.get('username') or '')}\n",
            f"PROXY_PASSWORD_B64={encoded(proxy.get('password') or '')}\n",
        )
        return "".join(lines).encode("ascii")

    def _probe_egress(self, name: str) -> str:
        result = _run(
            [
                "lxc",
                "exec",
                name,
                "--",
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--max-time",
                "15",
                "https://api.ipify.org",
            ],
            check=False,
            timeout=30,
        )
        if result.returncode != 0:
            return ""
        try:
            return str(ipaddress.ip_address(result.stdout.decode(errors="replace").strip()))
        except ValueError:
            return ""

    def deploy(self, payload: dict[str, Any]) -> dict[str, Any]:
        logical_node_id = str(payload.get("logical_node_id") or "")
        data = validate_deploy(logical_node_id, payload)
        name = instance_name(logical_node_id)
        if not self._exists(name):
            # A launch is transactional: bootstrap failures must not leave an
            # unassigned guest that the CAS-scoped cleanup endpoint cannot see.
            try:
                # Reserve and pin the bridge address while the new instance is
                # still stopped. cloud-init must see IPv4 on its first boot.
                with _LXD_ALLOC_LOCK:
                    lxd_ip = self._allocate_lxd_ipv4(name)
                    _run(
                        [
                            "lxc",
                            "init",
                            "ubuntu:24.04",
                            name,
                            "-c",
                            f"limits.cpu={data['lxd_cpu']}",
                            "-c",
                            f"limits.memory={data['lxd_memory_mib']}MiB",
                            "-c",
                            "limits.memory.enforce=hard",
                            "-c",
                            "limits.memory.swap=false",
                            "-c",
                            "boot.autostart=true",
                        ],
                        timeout=300,
                    )
                    self._pin_instance_ip(name, lxd_ip)
                    self._configure_instance_network(name, lxd_ip)
                _run(["lxc", "start", name], timeout=120)
                self._wait_ready(name)
                self._configure_guest(name, data)
                self._set_metadata(name, data)
            except Exception:
                with contextlib.suppress(Exception):
                    _run(["lxc", "delete", name, "--force"], check=False, timeout=180)
                raise
            return {
                "logical_node_id": logical_node_id,
                "instance_id": name,
                "running": True,
                "online": False,
                "runtime_backend": "lxd",
                "device_id": str(data["device_id"]),
            }
        else:
            config = self._config(name)
            values = config.get("config") if isinstance(config.get("config"), dict) else {}
            assignment_values = (
                str(values.get("user.cashpilot.earnapp.logical_node_id") or ""),
                str(values.get("user.cashpilot.earnapp.generation") or ""),
                str(values.get("user.cashpilot.earnapp.device_id") or ""),
            )
            if not any(assignment_values):
                self._verify_lxd_contract(config, data)
                with _LXD_ALLOC_LOCK:
                    lxd_ip = self._allocate_lxd_ipv4(name)
                    self._pin_instance_ip(name, lxd_ip)
                    self._configure_instance_network(name, lxd_ip)
                if self._status(name) != "running":
                    _run(["lxc", "start", name], timeout=120)
                self._wait_ready(name)
                self._configure_guest(name, data)
                self._set_metadata(name, data)
            else:
                self._assigned(logical_node_id, data)
                self._verify_lxd_contract(config, data)
        assignment = {
            "logical_node_id": logical_node_id,
            "generation": int(data["generation"]),
            "device_id": str(data["device_id"]),
        }
        return {"logical_node_id": logical_node_id, **self._evidence(name, assignment)}

    def suspend(self, logical_node_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        name, _ = self._assigned(logical_node_id, payload)
        _run(["lxc", "config", "set", name, "boot.autostart", "false"], timeout=30)
        if self._status(name) == "running":
            _run(["lxc", "stop", name, "--timeout", "60"], timeout=90)
        return {"instance_id": name, "running": False, "runtime_backend": "lxd"}

    def resume(self, logical_node_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        name, _ = self._assigned(logical_node_id, payload)
        _run(["lxc", "config", "set", name, "boot.autostart", "true"], timeout=30)
        if self._status(name) != "running":
            _run(["lxc", "start", name], timeout=120)
        return {"instance_id": name, "running": True, "runtime_backend": "lxd"}

    def remove(self, logical_node_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        name, _ = self._assigned(logical_node_id, payload)
        _run(["lxc", "delete", name, "--force"], timeout=180)
        return {"instance_id": name, "running": False, "runtime_backend": "lxd"}

    def evidence(self, logical_node_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        name, assignment = self._assigned(logical_node_id, payload)
        return self._evidence(name, assignment)

    def presence(self, logical_node_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Prove whether the exact assignment exists from LXD metadata."""
        name, assignment = self._assigned(logical_node_id, payload)
        return {
            "present": True,
            "instance_id": name,
            "runtime_backend": "lxd",
            "device_id": assignment["device_id"],
        }

    def proxy_binding_status(self, logical_node_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        name, _ = self._assigned(logical_node_id, payload)
        return _artifact_status(name)

    def discard_proxy_binding(self, logical_node_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        name, _ = self._assigned(logical_node_id, payload)
        values = self._config(name).get("config") or {}
        expected_proxy_id = _bounded_int(payload, "expected_proxy_id", 1, 2_147_483_647)
        if int(values.get("user.cashpilot.earnapp.proxy_id") or 0) != expected_proxy_id:
            raise AgentError("EarnApp proxy assignment conflict", 409)
        version = _binding_version(payload)
        status = _artifact_status(name)
        if status["previous_present"]:
            raise AgentError("EarnApp node has an active rollback artifact", 409)
        if status["binding_version"] and status["binding_version"] != version:
            raise AgentError("EarnApp binding version does not match", 409)
        if status["candidate_present"] or status["binding_version"]:
            _run(
                [
                    "lxc",
                    "exec",
                    name,
                    "--",
                    "sh",
                    "-lc",
                    "rm -f /etc/cashpilot/earnapp/proxy.env.cashpilot-new /etc/cashpilot/earnapp/.cashpilot-binding-version",
                ],
                timeout=30,
            )
        after = _artifact_status(name)
        if after["previous_present"] or after["candidate_present"] or after["binding_version"]:
            raise AgentError("EarnApp candidate cleanup remains ambiguous", 409)
        return {
            "binding_version": version,
            "action": "rolled_back",
            "proxy_id": expected_proxy_id,
            "idempotent": True,
        }

    def apply_proxy_binding(self, logical_node_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        name, _ = self._assigned(logical_node_id, payload)
        values = self._config(name).get("config") or {}
        expected_proxy_id = _bounded_int(payload, "expected_proxy_id", 1, 2_147_483_647)
        if int(values.get("user.cashpilot.earnapp.proxy_id") or 0) != expected_proxy_id:
            raise AgentError("EarnApp proxy assignment conflict", 409)
        version = _binding_version(payload)
        proxy = _proxy(payload)
        candidate = "/etc/cashpilot/earnapp/proxy.env.cashpilot-new"
        previous = "/etc/cashpilot/earnapp/proxy.env.cashpilot-prev"
        marker = "/etc/cashpilot/earnapp/.cashpilot-binding-version"
        self._write_guest_file(name, candidate, self._proxy_env(proxy))
        command = (
            f"set -eu; cp /etc/cashpilot/earnapp/proxy.env {previous}; "
            f"mv {candidate} /etc/cashpilot/earnapp/proxy.env; "
            f"printf %s {shlex.quote(version)} > {marker}; "
            "systemctl restart cashpilot-earnapp-proxy.service earnapp.service"
        )
        try:
            _run(["lxc", "exec", name, "--", "sh", "-lc", command], timeout=120)
            observed = self._probe_egress(name)
            if not observed or observed != str(payload.get("proxy", {}).get("exit_ip") or "").strip():
                raise AgentError("EarnApp candidate proxy egress mismatch", 409)
        except Exception:
            rollback = (
                f"set -eu; test -f {previous} && mv {previous} /etc/cashpilot/earnapp/proxy.env; "
                f"rm -f {candidate} {marker}; "
                "systemctl restart cashpilot-earnapp-proxy.service earnapp.service"
            )
            with contextlib.suppress(Exception):
                _run(["lxc", "exec", name, "--", "sh", "-lc", rollback], timeout=120)
            raise
        return {
            "binding_version": version,
            "proxy_id": int(proxy["proxy_id"]),
            "observed_egress_ip": observed,
            "probe_ok": True,
        }

    def finalize_proxy_binding(self, logical_node_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        name, _ = self._assigned(logical_node_id, payload)
        version = _binding_version(payload)
        expected_proxy_id = _bounded_int(payload, "expected_proxy_id", 1, 2_147_483_647)
        new_proxy_id = _bounded_int(payload, "new_proxy_id", 1, 2_147_483_647)
        marker = "/etc/cashpilot/earnapp/.cashpilot-binding-version"
        previous = "/etc/cashpilot/earnapp/proxy.env.cashpilot-prev"
        preflight = f'test "$(cat {marker})" = {shlex.quote(version)}'
        _run(["lxc", "exec", name, "--", "sh", "-lc", preflight], timeout=30)
        if bool(payload.get("commit")):
            self._set_proxy_metadata(name, new_proxy_id)
            _run(
                ["lxc", "exec", name, "--", "sh", "-lc", f"rm -f {previous}"],
                timeout=30,
            )
            return {"binding_version": version, "action": "confirmed", "proxy_id": new_proxy_id}
        values = self._config(name).get("config") or {}
        if int(values.get("user.cashpilot.earnapp.proxy_id") or 0) != expected_proxy_id:
            raise AgentError("EarnApp proxy assignment conflict", 409)
        command = (
            f"set -eu; mv {previous} /etc/cashpilot/earnapp/proxy.env; rm -f {marker}; "
            "systemctl restart cashpilot-earnapp-proxy.service earnapp.service"
        )
        _run(["lxc", "exec", name, "--", "sh", "-lc", command], timeout=120)
        return {"binding_version": version, "action": "rolled_back", "proxy_id": expected_proxy_id}


def dispatch(method: str, path: str, payload: dict[str, Any], controller: Any) -> dict[str, Any]:
    match = re.fullmatch(
        r"/v1/nodes/([a-z0-9][a-z0-9-]{2,120})(?:/(suspend|resume|evidence|presence)|/proxy/(status|discard|apply|finalize))?",
        path,
    )
    if match is None:
        raise AgentError("unknown EarnApp helper endpoint", 404)
    logical_node_id, action, proxy_action = match.groups()
    if method == "POST" and action is None and proxy_action is None:
        payload = dict(payload)
        payload["logical_node_id"] = logical_node_id
        return controller.deploy(payload)
    if method == "POST" and action in {"suspend", "resume", "evidence", "presence"}:
        return getattr(controller, action)(logical_node_id, payload)
    if method == "POST" and proxy_action in {"status", "discard", "apply", "finalize"}:
        handler = "proxy_binding_status" if proxy_action == "status" else f"{proxy_action}_proxy_binding"
        return getattr(controller, handler)(logical_node_id, payload)
    if method == "DELETE" and action is None:
        return controller.remove(logical_node_id, payload)
    raise AgentError("method not allowed", 405)


class _Handler(BaseHTTPRequestHandler):
    controller = Controller()

    def _handle(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 200_000:
                raise AgentError("request body too large", 413)
            payload = json.loads((self.rfile.read(length) if length else b"{}").decode())
            if not isinstance(payload, dict):
                raise AgentError("request body must be an object")
            self._json(200, dispatch(self.command, self.path, payload, self.controller))
        except AgentError as exc:
            self._json(exc.status, {"error": str(exc)})
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            self._json(400, {"error": "invalid request"})
        except Exception:
            self._json(500, {"error": "EarnApp helper internal error"})

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        self._handle()

    def do_DELETE(self) -> None:  # noqa: N802
        self._handle()

    def log_message(self, format: str, *args: Any) -> None:
        return


if hasattr(socketserver, "UnixStreamServer"):

    class _UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        allow_reuse_address = True
        daemon_threads = True

else:
    _UnixServer = None


def _socket_group() -> int:
    try:
        return os.stat("/var/run/docker.sock").st_gid
    except OSError:
        return 0


def serve(path: Path) -> None:
    if _UnixServer is None:
        raise RuntimeError("Unix domain sockets are required")
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
    server = _UnixServer(str(path), _Handler)
    path.chmod(0o660)
    os.chown(path, 0, _socket_group())
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", type=Path, default=SOCKET_PATH)
    args = parser.parse_args()
    serve(args.socket)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
