"""Secret-free helpers for the verified EarnApp platform wire contracts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app import provider_runtime

VPS_RUNTIME_BLOCK_REASON = provider_runtime.VPS_RUNTIME_BLOCK_REASON
VPS_RUNTIME_BLOCK_MESSAGE = provider_runtime.VPS_RUNTIME_BLOCK_MESSAGE


def runtime_deployment_allowed(platform: str = "", runtime_backend: str = "") -> bool:
    """Return the source-of-truth decision for one explicit EarnApp runtime."""
    return provider_runtime.platform_deployment_allowed("earnapp", platform, runtime_backend)


MAC_IDENTITY_ASSET_KIND = "mac_identity_profile"
MAC_PLATFORM = "darwin"
MAC_APPID = "mac_com.earnapp"
MAC_DEVICE_PREFIX = "sdk-mac-"
IOS_PLATFORM = "ios"
IOS_APPID = "com.brd.earnapp"
IOS_INSTALL_APPID = "ios_com.brd.earnapp"
IOS_DEVICE_PREFIX = "sdk-ios-"
UBUNTU_PLATFORM = "linux"
UBUNTU_APPID = "node_earnapp.com"
UBUNTU_DEVICE_PREFIX = "sdk-node-"
UBUNTU_RUNTIME_HOST = "earnapp_ubuntu"
UBUNTU_REFERENCE_IMAGE = "ghcr.io/assetforgeai-tech/cashpilot-earnapp-ubuntu"
# Pin the Linux/amd64 child manifest rather than the multi-platform index so
# the canary cannot silently select a different architecture.
UBUNTU_REFERENCE_DIGEST = "sha256:19b8d5831f0e83c0beb9a514bc9ed40c0be252ac101217fc01a6e2ac4714c559"
UBUNTU_REFERENCE_IMAGE_PIN = f"{UBUNTU_REFERENCE_IMAGE}@{UBUNTU_REFERENCE_DIGEST}"

# These are the only runtime artifacts copied into the canary image.  The
# binaries remain outside Git; the hashes pin the exact local source bundle
# used by the image build helper.
MAC_RUNTIME_ARTIFACT_HASHES = {
    "boot.js": "7b52a4bc06ec63bdb90f79b841af2d370ab9ed9665d5f0c786b1ad3207ac7eb9",
    "earn-supervisor": "550204505e47a29ca7d4b3853aefb8d05982a566744809fa65c10edf6c2531a2",
    "earnapp-mac": "d140b41ad1d7e851e2775aed4a77dc72fc306a206287c440829d6b47f35d6911",
    "entrypoint.sh": "eb1668a670f7e7b576975ddd77b29068074bea4bf7ff490a72657ce4d77d6dfd",
}

IOS_RUNTIME_ARTIFACT_HASHES = {
    "boot.js": "5de4b51eecdaf4b8b01bd5a2cafd019c701f877b9add727f405d6409f0c1793d",
    "earn-supervisor": "170c39c7821b7fd6110b96242b703fd6a0541dee29cf6c4525c3a70b67d42a25",
    "earnapp-bootstrap": "be9c4f6865134c87dbae373304e4b20bc55e91f60d2744ac03ebb864ca7fc2ee",
    "entrypoint.sh": "50b32e6f7280da75a7568cd25b6e4e43797f254517b1ee316f5b359f24e4144e",
}

UBUNTU_RUNTIME_ARTIFACT_HASHES = {
    "entrypoint.sh": "b03e12ed092f8386177910b9d9d89e6189c66730472a891d67192a958a4344bc",
}

_PLATFORM_CONTRACTS = {
    "macos": {
        "artifact_hashes": MAC_RUNTIME_ARTIFACT_HASHES,
        "runtime": "earnapp_mac_canary",
        "platform": MAC_PLATFORM,
        "appid": MAC_APPID,
        "device_prefix": MAC_DEVICE_PREFIX,
        "image": "cashpilot/earnapp-mac-canary",
    },
    "ios": {
        "artifact_hashes": IOS_RUNTIME_ARTIFACT_HASHES,
        "runtime": "earnapp_ios",
        "platform": IOS_PLATFORM,
        "appid": IOS_APPID,
        "device_prefix": IOS_DEVICE_PREFIX,
        "image": "cashpilot/earnapp-ios",
    },
    "ubuntu": {
        "artifact_hashes": UBUNTU_RUNTIME_ARTIFACT_HASHES,
        "runtime": UBUNTU_RUNTIME_HOST,
        "platform": UBUNTU_PLATFORM,
        "appid": UBUNTU_APPID,
        "device_prefix": UBUNTU_DEVICE_PREFIX,
        "image": "cashpilot/earnapp-ubuntu",
    },
}


def _image_platform(platform: str) -> str:
    value = str(platform or "macos").strip().lower()
    if value not in _PLATFORM_CONTRACTS:
        raise ValueError("unsupported EarnApp image platform")
    return value


def ios_registration_script() -> bytes:
    """Return the deterministic iOS control-plane registration helper."""
    script = """#!/usr/bin/env bash
set -euo pipefail
umask 077

STATE_DIR=/etc/earnapp
IDENTITY_FILE=/run/ios-spoof/identity.json
MARKER="$STATE_DIR/registered-ios-control-plane"
EXPECTED_EGRESS_IP="${EARNAPP_EXPECTED_EGRESS_IP:-}"
APPID=__IOS_INSTALL_APPID__

if [[ -z "$EXPECTED_EGRESS_IP" ]]; then
    echo '[earnapp] iOS registration requires an authoritative proxy egress' >&2
    exit 1
fi
if ! node -e 'const net=require("net"); process.exit(net.isIP(process.argv[1]) === 4 ? 0 : 1)' "$EXPECTED_EGRESS_IP"; then
    echo '[earnapp] iOS registration egress is not an IPv4 address' >&2
    exit 1
fi
[[ -s "$STATE_DIR/uuid" && -s "$STATE_DIR/ver" && -s "$IDENTITY_FILE" ]]

UUID=$(cat "$STATE_DIR/uuid")
VERSION=$(cat "$STATE_DIR/ver")
ARCH=$(node -e 'const d=require(process.argv[1]); process.stdout.write(String(d.arch || ""))' "$IDENTITY_FILE")
OS_VERSION=$(node -e 'const d=require(process.argv[1]); process.stdout.write(String(d.os_version || ""))' "$IDENTITY_FILE")
SERIAL=$(node -e 'const d=require(process.argv[1]); process.stdout.write(String(d.serial || ""))' "$IDENTITY_FILE")
FINGERPRINT=$(printf '%s\\0%s\\0%s\\0%s' "$UUID" "$VERSION" "$ARCH" "$SERIAL" | sha256sum | awk '{print $1}')

probe_egress() {
    local raw observed attempt
    for attempt in 1 2 3 4 5; do
        raw=$(curl --silent --show-error --http1.1 --noproxy '' \\
            --connect-timeout 10 --max-time 20 \\
            'https://api.ipify.org?format=json' 2>/dev/null || true)
        OBSERVED_EGRESS_IP=$(node -e '
const net=require("net");
const raw=process.argv[1] || "";
let value=raw.trim();
try { const body=JSON.parse(raw); value=String(body.ip || "").trim(); } catch {}
process.stdout.write(net.isIP(value) === 4 ? value : "");
' "$raw" 2>/dev/null || true)
        if [[ "$OBSERVED_EGRESS_IP" == "$EXPECTED_EGRESS_IP" ]]; then
            return 0
        fi
        sleep 2
    done
    echo '[earnapp] iOS registration proxy egress did not match the leased IP' >&2
    return 1
}

if [[ -s "$MARKER" ]] && test "$(cat "$MARKER")" = "$FINGERPRINT"; then
    exit 0
fi
probe_egress

register_body=$(mktemp)
register_error=$(mktemp)
linked_body=$(mktemp)
linked_error=$(mktemp)
TEMP_MARKER=$(mktemp "$STATE_DIR/.registered-ios-control-plane.XXXXXX")
cleanup() {
    rm -f "$register_body" "$register_error" "$linked_body" "$linked_error" "$TEMP_MARKER"
}
trap cleanup EXIT

REGISTER_URL=$(node -e '
const [uuid,version,arch,appid,osVersion]=process.argv.slice(1);
const url=new URL("https://client.earnapp.com/install_device");
url.searchParams.set("uuid", uuid);
url.searchParams.set("version", version);
url.searchParams.set("arch", arch);
url.searchParams.set("appid", "__IOS_INSTALL_APPID__");
url.searchParams.set("os", "iOS "+osVersion);
process.stdout.write(url.href);
' "$UUID" "$VERSION" "$ARCH" "$APPID" "$OS_VERSION")
REGISTER_BODY=$(node -e 'process.stdout.write(JSON.stringify({serial: process.argv[1]}))' "$SERIAL")
register_code=$(curl --silent --show-error --http1.1 --noproxy '' \\
    --connect-timeout 15 --max-time 45 \\
    --output "$register_body" --write-out '%{http_code}' \\
    -H 'Content-Type: application/json' -X POST \\
    "$REGISTER_URL" --data-binary "$REGISTER_BODY" 2>"$register_error" || true)
if [[ ! "$register_code" =~ ^2 ]]; then
    echo '[earnapp] iOS install_device request failed' >&2
    exit 1
fi
node -e '
const fs=require("fs");
let body;
try { body=JSON.parse(fs.readFileSync(process.argv[1],"utf8")); } catch { process.exit(1); }
if (body.ok !== 1 && body.ok !== "1") process.exit(1);
' "$register_body"

LINKED_URL=$(node -e '
const [uuid,version,appid]=process.argv.slice(1);
const url=new URL("https://client.earnapp.com/is_linked");
for (const [key,value] of Object.entries({uuid,version,appid})) url.searchParams.set(key,value);
process.stdout.write(url.href);
' "$UUID" "$VERSION" "$APPID")
linked_code=$(curl --silent --show-error --http1.1 --noproxy '' \\
    --connect-timeout 15 --max-time 45 \\
    --output "$linked_body" --write-out '%{http_code}' \\
    -G "$LINKED_URL" 2>"$linked_error" || true)
if [[ ! "$linked_code" =~ ^2 ]]; then
    echo '[earnapp] iOS is_linked request failed' >&2
    exit 1
fi
node -e '
const fs=require("fs");
let body;
try { body=JSON.parse(fs.readFileSync(process.argv[1],"utf8")); } catch { process.exit(1); }
if (!body || typeof body.linked !== "boolean") process.exit(1);
' "$linked_body"

printf '%s\\n' "$FINGERPRINT" > "$TEMP_MARKER"
chmod 0600 "$TEMP_MARKER"
mv -f "$TEMP_MARKER" "$MARKER"
""".replace("__IOS_INSTALL_APPID__", IOS_INSTALL_APPID)
    return script.encode("utf-8")


def ios_entrypoint_script() -> bytes:
    """Run iOS registration before the immutable upstream entrypoint."""
    return (
        b"#!/usr/bin/env bash\n"
        b"set -euo pipefail\n"
        b"/usr/local/bin/ios-register-device\n"
        b"unset PROXY_CREDENTIALS PROXY_HOST PROXY_PORT PROXY_USER PROXY_PASS\n"
        b'exec /usr/local/bin/entrypoint-original.sh "$@"\n'
    )


def proxy_entrypoint_script(platform: str = "macos") -> bytes:
    """Route one EarnApp container through its assigned proxy and fail closed."""
    selected = _image_platform(platform)
    next_entrypoint = "/usr/local/bin/ios-entrypoint" if selected == "ios" else "/usr/local/bin/entrypoint-original.sh"
    ios_route = (
        """
REDSOCKS_CONF=/tmp/cashpilot-redsocks.conf
cat >"$REDSOCKS_CONF" <<EOF
base {
    log_debug = off;
    log_info = off;
    log = "file:/tmp/redsocks.log";
    daemon = off;
    redirector = iptables;
}
redsocks {
    local_ip = 127.0.0.1;
    local_port = $REDSOCKS_PORT;
    ip = $PROXY_IP;
    port = $PROXY_PORT;
    type = $REDSOCKS_TYPE;
EOF
if [[ -n "${PROXY_USER:-}" && -n "${PROXY_PASS:-}" ]]; then
  printf '    login = "%s";\\n    password = "%s";\\n' "$PROXY_USER" "$PROXY_PASS" >>"$REDSOCKS_CONF"
fi
printf '}\\n' >>"$REDSOCKS_CONF"
/usr/sbin/redsocks -c "$REDSOCKS_CONF" &
sleep 1
        iptables -t nat -N CP_EARNAPP_IOS_REDSOCKS 2>/dev/null || iptables -t nat -F CP_EARNAPP_IOS_REDSOCKS
for cidr in 0.0.0.0/8 10.0.0.0/8 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/4 "$PROXY_IP/32"; do
          iptables -t nat -A CP_EARNAPP_IOS_REDSOCKS -d "$cidr" -j RETURN
done
        iptables -t nat -A CP_EARNAPP_IOS_REDSOCKS -p tcp -j REDIRECT --to-ports "$REDSOCKS_PORT"
        iptables -t nat -C OUTPUT -p tcp -j CP_EARNAPP_IOS_REDSOCKS 2>/dev/null || iptables -t nat -I OUTPUT 1 -p tcp -j CP_EARNAPP_IOS_REDSOCKS
unset PROXY_CREDENTIALS PROXY_HOST PROXY_PORT PROXY_USER PROXY_PASS
"""
        if selected == "ios"
        else ""
    )
    if selected == "ios":
        runtime_handoff = f'exec {next_entrypoint} "$@"'
    elif selected == "ubuntu":
        # The pinned official Linux image owns first-boot installation and UUID
        # generation. The outer wrapper only installs the fail-closed firewall;
        # requiring a control-plane UUID here would deadlock fresh deployment.
        runtime_handoff = r'''SANITIZED_ENTRYPOINT=/tmp/cashpilot-entrypoint-original.sh
sed '/^set -euo pipefail/a unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy NO_PROXY no_proxy' \
  /usr/local/bin/entrypoint-original.sh >"$SANITIZED_ENTRYPOINT"
chmod 0755 "$SANITIZED_ENTRYPOINT"
exec "$SANITIZED_ENTRYPOINT" "$@"'''
    else:
        runtime_handoff = r'''# The reference entrypoint starts redsocks and also exports application-level
# proxy variables. EarnApp's Axios client then sends absolute-form requests
# that some leased HTTP proxies reject with 400. Keep redsocks/iptables, but
# execute a sanitized copy without those variables so sockets use transparent
# routing and retain origin-form requests.
# A failed first install can leave a complete binary without the reference
# marker. Adopt only the content-addressed binary; partial installs must retry.
MAC_BINARY_SHA256=d140b41ad1d7e851e2775aed4a77dc72fc306a206287c440829d6b47f35d6911
if [[ -s "$STATE_DIR/uuid" && -s "$STATE_DIR/com.earnapp.cid" && -x /opt/earnapp-mac \
      && "$(sha256sum /opt/earnapp-mac | awk '{print $1}')" == "$MAC_BINARY_SHA256" ]]; then
  install -m 0755 /opt/earnapp-mac /usr/bin/earnapp
fi
if [[ -x /usr/bin/earnapp && "$(sha256sum /usr/bin/earnapp | awk '{print $1}')" != "$MAC_BINARY_SHA256" ]]; then
  rm -f /usr/bin/earnapp
fi
if [[ -f "$STATE_DIR/registered" && "$(cat "$STATE_DIR/registered")" == "complete" ]]; then
  rm -f "$STATE_DIR/registered"
fi
# The verified source entrypoint writes the proxy endpoint into an iptables
# destination rule. Pass the already-resolved IPv4 so hostname endpoints cannot
# produce an invalid rule or bypass the fail-closed route.
unset PROXY_CREDENTIALS
export PROXY_HOST="$PROXY_IP"
export PROXY_PORT PROXY_USER PROXY_PASS PROXY_TYPE
EXPECTED_DEVICE_ID="${EARNAPP_DEVICE_ID:?}"
[[ -s "$STATE_DIR/uuid" && "$(cat "$STATE_DIR/uuid")" == "$EXPECTED_DEVICE_ID" ]]
if [[ ! -s "$STATE_DIR/registered" || "$(cat "$STATE_DIR/registered")" != "$EXPECTED_DEVICE_ID" ]]; then
  version=$(/usr/bin/earnapp --version | awk '{print $2}')
  serial=${EXPECTED_DEVICE_ID#sdk-mac-}
  register_body=$(mktemp)
  trap 'rm -f "$register_body"' EXIT
  case "$PROXY_TYPE" in
    SOCKS5) register_proxy=(--socks5-hostname "$PROXY_HOST:$PROXY_PORT") ;;
    HTTP) register_proxy=(--proxy "http://$PROXY_HOST:$PROXY_PORT") ;;
  esac
  if [[ -n "${PROXY_USER:-}" || -n "${PROXY_PASS:-}" ]]; then
    register_proxy+=(--proxy-user "$PROXY_USER:$PROXY_PASS")
  fi
  registered=false
  for attempt in $(seq 1 10); do
    if curl -fsS --http1.1 --connect-timeout 15 --max-time 45 \
        "${register_proxy[@]}" -H 'Content-Type: application/json' \
        -o "$register_body" \
        "https://client.earnapp.com/install_device?uuid=$EXPECTED_DEVICE_ID&version=$version&arch=x64&appid=mac_com.earnapp&os=macOS" \
        --data "{\"serial\":\"$serial\"}" \
      && grep -Eq '"ok"[[:space:]]*:[[:space:]]*(1|true|"1")' "$register_body"; then
      printf '%s' "$EXPECTED_DEVICE_ID" >"$STATE_DIR/registered"
      registered=true
      break
    fi
    [[ "$attempt" -lt 10 ]] && sleep 15
  done
  [[ "$registered" == true ]]
  rm -f "$register_body"
  trap - EXIT
fi
SANITIZED_ENTRYPOINT=/tmp/cashpilot-entrypoint-original.sh
sed '/# ANTI-DETECTION: Docker \/ VM/i unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy NO_PROXY no_proxy' \
  /usr/local/bin/entrypoint-original.sh >"$SANITIZED_ENTRYPOINT"
chmod 0755 "$SANITIZED_ENTRYPOINT"
exec "$SANITIZED_ENTRYPOINT" "$@"'''
    return f"""#!/usr/bin/env bash
set -euo pipefail
STATE_DIR=/etc/earnapp
REDSOCKS_PORT=12345
PROXY_TYPE=$(printf '%s' "${{PROXY_TYPE:-SOCKS5}}" | tr '[:lower:]' '[:upper:]')
IFS=: read -r PROXY_HOST PROXY_PORT PROXY_USER PROXY_PASS <<<"${{PROXY_CREDENTIALS:?}}"
[[ -n "$PROXY_HOST" && "$PROXY_PORT" =~ ^[0-9]+$ ]]
PROXY_IP=$(getent ahostsv4 "$PROXY_HOST" | awk 'NR==1 {{print $1}}')
[[ -n "$PROXY_IP" ]]
case "$PROXY_TYPE" in
  SOCKS5) REDSOCKS_TYPE=socks5 ;;
  HTTP) REDSOCKS_TYPE=http-connect ;;
  *) exit 64 ;;
esac
printf "nameserver 8.8.8.8\noptions use-vc timeout:2 attempts:2\n" > /etc/resolv.conf
iptables -N CP_EARNAPP_OUT 2>/dev/null || iptables -F CP_EARNAPP_OUT
iptables -A CP_EARNAPP_OUT -o lo -j ACCEPT
iptables -A CP_EARNAPP_OUT -d 127.0.0.0/8 -j ACCEPT
iptables -A CP_EARNAPP_OUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A CP_EARNAPP_OUT -d "$PROXY_IP"/32 -p tcp --dport "$PROXY_PORT" -j ACCEPT
iptables -A CP_EARNAPP_OUT -j DROP
iptables -C OUTPUT -j CP_EARNAPP_OUT 2>/dev/null || iptables -I OUTPUT 1 -j CP_EARNAPP_OUT
iptables -t nat -N CP_EARNAPP_DNS 2>/dev/null || iptables -t nat -F CP_EARNAPP_DNS
iptables -t nat -A CP_EARNAPP_DNS -d 127.0.0.0/8 -j RETURN
iptables -t nat -A CP_EARNAPP_DNS -p tcp --dport 53 -j REDIRECT --to-ports 12345
iptables -t nat -C OUTPUT -p tcp --dport 53 -j CP_EARNAPP_DNS 2>/dev/null || iptables -t nat -I OUTPUT 1 -p tcp --dport 53 -j CP_EARNAPP_DNS
if command -v ip6tables >/dev/null 2>&1; then
  ip6tables -N CP_EARNAPP6_OUT 2>/dev/null || ip6tables -F CP_EARNAPP6_OUT
  ip6tables -A CP_EARNAPP6_OUT -o lo -j ACCEPT
  ip6tables -A CP_EARNAPP6_OUT -j DROP
  ip6tables -C OUTPUT -j CP_EARNAPP6_OUT 2>/dev/null || ip6tables -I OUTPUT 1 -j CP_EARNAPP6_OUT
fi
{ios_route}
{runtime_handoff}
        """.encode()


def generated_runtime_artifacts(platform: str = "macos") -> dict[str, bytes]:
    """Return generated scripts that are part of the platform image digest."""
    selected = _image_platform(platform)
    generated = {"cashpilot-proxy-entrypoint": proxy_entrypoint_script(selected)}
    if selected == "ios":
        generated.update(
            {
                "ios-entrypoint": ios_entrypoint_script(),
                "ios-register-device": ios_registration_script(),
            }
        )
    return generated


def ubuntu_entrypoint_script() -> bytes:
    """Return the persistent official Linux runtime bootstrap."""
    return rb"""#!/usr/bin/env bash
set -euo pipefail
umask 077

STATE_DIR=/etc/earnapp
IDENTITY_FILE=/run/cashpilot/identity.json
HOST_ID_FILE="$STATE_DIR/host-machine-id"
HOST_JSON_FILE="$STATE_DIR/host.json"
HOST_SERIAL_FILE="$STATE_DIR/host.serial"
EXPECTED_DEVICE_ID="${EARNAPP_DEVICE_ID:?}"
EXPECTED_EGRESS_IP="${EARNAPP_EXPECTED_EGRESS_IP:-}"
REDSOCKS_PORT=12345
REDSOCKS_CONF=/tmp/redsocks.conf
if [[ -z "$EXPECTED_EGRESS_IP" && -s "$STATE_DIR/expected_egress_ip" ]]; then
    EXPECTED_EGRESS_IP=$(tr -d '\r\n-' <"$STATE_DIR/expected_egress_ip")
fi
[[ -n "$EXPECTED_EGRESS_IP" ]]
mkdir -p "$STATE_DIR" /var/lib/dbus
rm -f /.dockerenv

read_identity() {
    python3 - "$IDENTITY_FILE" "$1" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    value = json.load(handle)
print(str(value.get(sys.argv[2]) or ""), end="")
PY
}

parse_proxy() {
    local raw="${PROXY_CREDENTIALS:-}"
    PROXY_HOST="${raw%%:*}"
    raw="${raw#*:}"
    PROXY_PORT="${raw%%:*}"
    raw="${raw#*:}"
    PROXY_USER="${raw%%:*}"
    PROXY_PASS="${raw#*:}"
    [[ "$PROXY_HOST" != "$raw" ]] || PROXY_PASS=""
    PROXY_TYPE=$(printf '%s' "${PROXY_TYPE:-SOCKS5}" | tr '[:lower:]' '[:upper:]')
    case "$PROXY_TYPE" in
        SOCKS5) REDSOCKS_TYPE=socks5 ;;
        HTTP) REDSOCKS_TYPE=http-connect ;;
        *) echo '[proxy] unsupported proxy type' >&2; return 1 ;;
    esac
}

setup_proxy() {
    [[ -n "${PROXY_CREDENTIALS:-}" ]] || return 0
    parse_proxy
    local proxy_ip
    proxy_ip=$(getent ahostsv4 "$PROXY_HOST" 2>/dev/null | awk 'NR==1 {print $1}')
    [[ -n "$proxy_ip" && "$PROXY_PORT" =~ ^[0-9]+$ ]] || { echo '[proxy] cannot resolve proxy' >&2; return 1; }
    pkill -x redsocks 2>/dev/null || true
    iptables -t nat -D OUTPUT -p tcp -j REDSOCKS 2>/dev/null || true
    iptables -t nat -F REDSOCKS 2>/dev/null || true
    iptables -t nat -N REDSOCKS 2>/dev/null || true
    cat >"$REDSOCKS_CONF" <<EOF
base {
    log_debug = off;
    log_info = off;
    log = "file:/tmp/redsocks.log";
    daemon = off;
    redirector = iptables;
}
redsocks {
    local_ip = 127.0.0.1;
    local_port = $REDSOCKS_PORT;
    ip = $proxy_ip;
    port = $PROXY_PORT;
    type = $REDSOCKS_TYPE;
EOF
    if [[ -n "${PROXY_USER:-}" && -n "${PROXY_PASS:-}" ]]; then
        printf '    login = "%s";\n    password = "%s";\n' "$PROXY_USER" "$PROXY_PASS" >>"$REDSOCKS_CONF"
    fi
    printf '}\n' >>"$REDSOCKS_CONF"
    /usr/sbin/redsocks -c "$REDSOCKS_CONF" &
    sleep 1
    iptables -t nat -F REDSOCKS
    for cidr in 0.0.0.0/8 10.0.0.0/8 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/4 "$proxy_ip/32"; do
        iptables -t nat -A REDSOCKS -d "$cidr" -j RETURN
    done
    iptables -t nat -A REDSOCKS -p tcp -j REDIRECT --to-ports "$REDSOCKS_PORT"
    iptables -t nat -A OUTPUT -p tcp -j REDSOCKS
    echo '[proxy] redsocks route installed'
}

install -m 0600 "$IDENTITY_FILE" "$HOST_JSON_FILE"

PROFILE_DEVICE_ID=$(read_identity device_id)
PROFILE_MACHINE_ID=$(read_identity machine_id | tr -d '\r\n-' | tr 'A-F' 'a-f')
CONFIG_HOSTNAME=$(read_identity hostname)
[[ "$PROFILE_DEVICE_ID" == "$EXPECTED_DEVICE_ID" ]]
[[ "$PROFILE_MACHINE_ID" =~ ^[0-9a-f]{32}$ ]]

if [[ -s "$STATE_DIR/tracking_id" ]]; then
    tracking=$(tr -d '\r\n-' <"$STATE_DIR/tracking_id" | tr 'A-F' 'a-f')
    [[ "$tracking" =~ ^[0-9a-f]{32}$ ]] || tracking="$PROFILE_MACHINE_ID"
    printf '%s\n' "$tracking" >"$HOST_ID_FILE"
elif [[ ! -s "$HOST_ID_FILE" ]]; then
    printf '%s\n' "$PROFILE_MACHINE_ID" >"$HOST_ID_FILE"
fi
if [[ -w /etc/machine-id ]]; then
    install -m 0444 "$HOST_ID_FILE" /etc/machine-id
    ln -sfn /etc/machine-id /var/lib/dbus/machine-id
else
    echo "[host] read-only machine-id; skip host helper apply"
fi
printf '%s\n' "${CONFIG_HOSTNAME:-earnapp-ubuntu}" >/etc/hostname
read_identity serial >"$HOST_SERIAL_FILE"

if [[ -w /etc/machine-id ]] && command -v earnapp-host >/dev/null 2>&1; then
    earnapp-host ensure
    eval "$(earnapp-host apply)"
fi

printf '%s\n' "$EXPECTED_DEVICE_ID" >"$STATE_DIR/uuid"
printf '%s\n' enabled >"$STATE_DIR/status"
printf '%s\n' "$(cat /etc/machine-id)" >"$STATE_DIR/tracking_id"

echo "[host] Hostname: $(cat /etc/hostname)"
echo "[host] Machine ID: $(cat /etc/machine-id)"
echo "[host] OS: $(. /etc/os-release && printf '%s' "$PRETTY_NAME")"
echo "[host] Architecture: $(dpkg --print-architecture)"

setup_proxy

for _ in $(seq 1 30); do
    observed=$(curl -fsS --connect-timeout 5 --max-time 15 https://api.ipify.org || true)
    [[ "$observed" == "$EXPECTED_EGRESS_IP" ]] && break
    sleep 2
done
[[ "${observed:-}" == "$EXPECTED_EGRESS_IP" ]]

version=$(/usr/bin/earnapp --version | awk '{print $2}')
printf '%s\n' "$version" >"$STATE_DIR/ver"
serial=$(sha1sum /etc/machine-id | awk '{print $1}')
for attempt in $(seq 1 10); do
    install_body=$(mktemp)
    linked_body=$(mktemp)
    if curl -fsS --connect-timeout 15 --max-time 45 -H 'Content-Type: application/json' \
        -o "$install_body" \
        "https://client.earnapp.com/install_device?uuid=$EXPECTED_DEVICE_ID&version=$version&arch=x64&appid=node_earnapp.com&os=Ubuntu" \
        --data "{\"serial\":\"$serial\"}" \
      && curl -fsS --connect-timeout 15 --max-time 45 -o "$linked_body" \
        "https://client.earnapp.com/is_linked?uuid=$EXPECTED_DEVICE_ID&version=$version&appid=node_earnapp.com" \
      && python3 - "$install_body" "$linked_body" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    installed = json.load(handle)
with open(sys.argv[2], encoding="utf-8") as handle:
    linked = json.load(handle)
raise SystemExit(0 if installed.get("ok") in (1, True, "1") and linked.get("linked") is True else 1)
PY
    then
        printf '%s\n' "$EXPECTED_DEVICE_ID" >"$STATE_DIR/registered"
        rm -f "$install_body" "$linked_body"
        break
    fi
    rm -f "$install_body" "$linked_body"
    [[ "$attempt" -lt 10 ]] || exit 1
    sleep 15
done

/usr/bin/earnapp autoupgrade &
exec /usr/bin/earnapp run
"""


def runtime_asset_manifest(
    artifact_hashes: Mapping[str, str] | None = None,
    *,
    platform: str = "macos",
) -> dict[str, Any]:
    """Return the canonical manifest used to pin one emulated runtime build."""
    selected = _image_platform(platform)
    hashes = dict(artifact_hashes or _PLATFORM_CONTRACTS[selected]["artifact_hashes"])
    for path, payload in generated_runtime_artifacts(selected).items():
        hashes[path] = hashlib.sha256(payload).hexdigest()
    manifest: dict[str, Any] = {
        "version": 1,
        "artifacts": [{"path": str(path), "sha256": str(digest).lower()} for path, digest in sorted(hashes.items())],
    }
    if selected == "ubuntu":
        manifest["base_image"] = f"{UBUNTU_REFERENCE_IMAGE}@{UBUNTU_REFERENCE_DIGEST}"
    return manifest


def runtime_asset_manifest_bytes(
    artifact_hashes: Mapping[str, str] | None = None,
    *,
    platform: str = "macos",
) -> bytes:
    payload = json.dumps(
        runtime_asset_manifest(artifact_hashes, platform=platform),
        sort_keys=True,
        separators=(",", ":"),
    )
    return (payload + "\n").encode("utf-8")


def runtime_asset_manifest_sha256(
    artifact_hashes: Mapping[str, str] | None = None,
    *,
    platform: str = "macos",
) -> str:
    return hashlib.sha256(runtime_asset_manifest_bytes(artifact_hashes, platform=platform)).hexdigest()


MAC_RUNTIME_ASSET_MANIFEST_SHA256 = runtime_asset_manifest_sha256()
MAC_RUNTIME_IMAGE = f"cashpilot/earnapp-mac-canary:asset-{MAC_RUNTIME_ASSET_MANIFEST_SHA256[:12]}"
MAC_RUNTIME_HOST = "earnapp_mac_canary"
IOS_RUNTIME_ASSET_MANIFEST_SHA256 = runtime_asset_manifest_sha256(platform="ios")
IOS_RUNTIME_IMAGE = f"cashpilot/earnapp-ios:asset-{IOS_RUNTIME_ASSET_MANIFEST_SHA256[:12]}"
UBUNTU_RUNTIME_ASSET_MANIFEST_SHA256 = runtime_asset_manifest_sha256(platform="ubuntu")
UBUNTU_RUNTIME_IMAGE = f"cashpilot/earnapp-ubuntu:asset-{UBUNTU_RUNTIME_ASSET_MANIFEST_SHA256[:12]}"
IOS_RUNTIME_HOST = "earnapp_ios"
MAC_PROFILE_MAGIC = b"ESPF"
MAC_PROFILE_VERSION = 1
# Keep this precomputed key in lock-step with the official ``boot.js`` fallback
# derivation. It is a protocol compatibility value, never a credential hash.
MAC_PROFILE_KEY_HEX = "c0f6e9049acba2e1980b0dfd3dbe0fdbde5df4706235f814651722592bd6fa55"
MAC_PROFILE_KEY = bytes.fromhex(MAC_PROFILE_KEY_HEX)


def runtime_image(platform: str = "macos") -> str:
    selected = _image_platform(platform)
    contract = _PLATFORM_CONTRACTS[selected]
    digest = runtime_asset_manifest_sha256(platform=selected)
    return f"{contract['image']}:asset-{digest[:12]}"


def required_image_labels(platform: str = "macos") -> dict[str, str]:
    selected = _image_platform(platform)
    contract = _PLATFORM_CONTRACTS[selected]
    return {
        "com.cashpilot.earnapp.runtime": str(contract["runtime"]),
        "com.cashpilot.earnapp.platform": str(contract["platform"]),
        "com.cashpilot.earnapp.appid": str(contract["appid"]),
        "com.cashpilot.earnapp.device-prefix": str(contract["device_prefix"]),
        "com.cashpilot.earnapp.assets-sha256": runtime_asset_manifest_sha256(platform=selected),
    }


def validate_image_labels(labels: Any, platform: str = "macos") -> None:
    actual = labels if isinstance(labels, dict) else {}
    missing = [
        key for key, expected in required_image_labels(platform).items() if str(actual.get(key) or "") != expected
    ]
    if missing:
        raise ValueError(f"EarnApp image is missing verified labels: {', '.join(missing)}")


def validate_canary_spec(spec: dict[str, Any]) -> None:
    """Fail closed on the worker boundary for the owner-only Mac lane."""
    if str(spec.get("provider_slug") or "") != "earnapp":
        raise ValueError("EarnApp canary provider is required")
    if str(spec.get("host_runtime") or "") != MAC_RUNTIME_HOST:
        raise ValueError("EarnApp Mac canary host runtime is required")
    if str(spec.get("image") or "") != MAC_RUNTIME_IMAGE:
        raise ValueError("EarnApp image is not the verified Mac canary image")
    if spec.get("privileged") or spec.get("devices"):
        raise ValueError("EarnApp canary cannot request privilege or devices")
    if {str(value).upper() for value in (spec.get("cap_add") or [])} != {"NET_ADMIN"}:
        raise ValueError("EarnApp canary requires NET_ADMIN for its fail-closed proxy route")
    if spec.get("network_mode") != "bridge":
        raise ValueError("EarnApp canary network mode is invalid")
    if str(spec.get("egress_mode") or "") != "proxy":
        raise ValueError("EarnApp canary must use proxy egress")
    contract = spec.get("runtime_contract") or {}
    if contract != {"platform": MAC_PLATFORM, "appid": MAC_APPID, "device_id_prefix": MAC_DEVICE_PREFIX}:
        raise ValueError("EarnApp Mac runtime contract is not verified")
    labels = spec.get("labels") or {}
    for key, expected in {
        "cashpilot.provider": "earnapp",
        "cashpilot.earnapp.platform": MAC_PLATFORM,
        "cashpilot.earnapp.runtime_contract": MAC_APPID,
    }.items():
        if str(labels.get(key) or "") != expected:
            raise ValueError(f"EarnApp canary label {key} is invalid")
    device_id = validate_device_id(str(spec.get("env", {}).get("EARNAPP_DEVICE_ID") or ""))
    if not str(labels.get("cashpilot.earnapp.device_id") or "") == device_id:
        raise ValueError("EarnApp device label does not match the runtime identity")
    assets = spec.get("runtime_assets") or []
    if len(assets) != 1:
        raise ValueError("EarnApp canary requires exactly one encrypted Mac profile")
    asset = assets[0]
    if (
        str(asset.get("provider") or "") != "earnapp"
        or str(asset.get("asset_kind") or "") != MAC_IDENTITY_ASSET_KIND
        or str(asset.get("target") or "") != "/etc/earnapp-spoof/profile.json.enc"
        or str(asset.get("encoding") or "") != "base64"
        or not str(asset.get("asset_id") or "").strip()
    ):
        raise ValueError("EarnApp Mac profile asset reference is invalid")
    for source, mount in (spec.get("volumes") or {}).items():
        if str(source).startswith("/"):
            raise ValueError("EarnApp canary cannot use host system mounts")
        if str(mount.get("bind") or "") == "/etc/earnapp" and str(mount.get("mode") or "") != "rw":
            raise ValueError("EarnApp state volume must be writable")
    proxy = spec.get("proxy") or {}
    if not str(proxy.get("host") or "").strip() or not 1 <= int(proxy.get("port") or 0) <= 65535:
        raise ValueError("EarnApp canary proxy is incomplete")
    if str(proxy.get("protocol") or "").lower() not in {"http", "socks5"}:
        raise ValueError("EarnApp canary proxy protocol is invalid")


def validate_runtime_spec(spec: dict[str, Any]) -> None:
    labels = spec.get("labels") or {}
    platform_label = str(labels.get("cashpilot.earnapp.platform") or "").strip().lower()
    selected = (
        "macos"
        if platform_label == MAC_PLATFORM
        else ("ubuntu" if platform_label == UBUNTU_PLATFORM else platform_label)
    )
    if selected == "macos":
        validate_canary_spec(spec)
        return
    if selected == "ubuntu":
        _validate_ubuntu_runtime_spec(spec)
        return
    if selected != "ios":
        raise ValueError("EarnApp Docker runtime supports only MacOS, iOS, or Ubuntu")
    if str(spec.get("provider_slug") or "") != "earnapp":
        raise ValueError("EarnApp provider is required")
    if str(spec.get("host_runtime") or "") != IOS_RUNTIME_HOST:
        raise ValueError("EarnApp iOS runtime is required")
    if str(spec.get("image") or "") != IOS_RUNTIME_IMAGE:
        raise ValueError("EarnApp image is not the verified iOS image")
    if spec.get("privileged") or spec.get("devices"):
        raise ValueError("EarnApp iOS runtime cannot request host privilege")
    if {str(value).upper() for value in (spec.get("cap_add") or [])} != {"NET_ADMIN"}:
        raise ValueError("EarnApp iOS runtime requires NET_ADMIN for its fail-closed proxy route")
    if spec.get("network_mode") != "bridge" or str(spec.get("egress_mode") or "") != "proxy":
        raise ValueError("EarnApp iOS runtime must use proxy bridge egress")
    contract = spec.get("runtime_contract") or {}
    expected_contract = {
        "platform": IOS_PLATFORM,
        "appid": IOS_APPID,
        "device_id_prefix": IOS_DEVICE_PREFIX,
    }
    if contract != expected_contract:
        raise ValueError("EarnApp iOS runtime contract is not verified")
    device_id = str((spec.get("env") or {}).get("EARNAPP_DEVICE_ID") or "")
    if not re.fullmatch(r"sdk-ios-[A-Za-z0-9-]{4,96}", device_id):
        raise ValueError("EarnApp iOS device identity is invalid")
    if str(labels.get("cashpilot.earnapp.device_id") or "") != device_id:
        raise ValueError("EarnApp iOS device label does not match")
    expected_egress = str((spec.get("env") or {}).get("EARNAPP_EXPECTED_EGRESS_IP") or "").strip()
    if not re.fullmatch(r"(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}", expected_egress):
        raise ValueError("EarnApp iOS runtime requires an authoritative egress IP")
    proxy = spec.get("proxy") if isinstance(spec.get("proxy"), Mapping) else {}
    host = str(proxy.get("host") or "").strip()
    try:
        port = int(proxy.get("port") or 0)
    except (TypeError, ValueError):
        port = 0
    if not host or not 1 <= port <= 65535:
        raise ValueError("EarnApp iOS proxy is incomplete")
    if str(proxy.get("protocol") or "").strip().lower() not in {"http", "socks5"}:
        raise ValueError("EarnApp iOS proxy protocol is invalid")
    if (
        str(proxy.get("country_code") or "").strip().upper() != "VN"
        or str(proxy.get("ip_type") or "").strip().lower() != "residential"
    ):
        raise ValueError("EarnApp iOS runtime requires a VN residential proxy")
    if str(proxy.get("exit_ip") or "").strip() != expected_egress:
        raise ValueError("EarnApp iOS runtime egress does not match proxy lease")
    assets = spec.get("runtime_assets") or []
    if len(assets) != 1:
        raise ValueError("EarnApp iOS runtime requires one identity profile")
    asset = assets[0]
    if (
        str(asset.get("provider") or "") != "earnapp"
        or str(asset.get("asset_kind") or "") != "ios_identity_profile"
        or str(asset.get("target") or "") != "/etc/earnapp-spoof/profile.json.enc"
        or str(asset.get("encoding") or "") != "base64"
        or not str(asset.get("asset_id") or "").strip()
    ):
        raise ValueError("EarnApp iOS identity asset is invalid")


def _validate_ubuntu_runtime_spec(spec: dict[str, Any]) -> None:
    if str(spec.get("provider_slug") or "") != "earnapp":
        raise ValueError("EarnApp provider is required")
    if str(spec.get("host_runtime") or "") != UBUNTU_RUNTIME_HOST:
        raise ValueError("EarnApp Ubuntu runtime is required")
    if str(spec.get("image") or "") != UBUNTU_RUNTIME_IMAGE:
        raise ValueError("EarnApp image is not the verified Ubuntu image")
    if spec.get("privileged") or spec.get("devices"):
        raise ValueError("EarnApp Ubuntu runtime cannot request host privilege")
    cap_add = {str(value).upper() for value in (spec.get("cap_add") or [])}
    if cap_add - {"NET_ADMIN"}:
        raise ValueError("EarnApp Ubuntu runtime only permits NET_ADMIN")
    if spec.get("network_mode") not in (None, "", "bridge") or str(spec.get("egress_mode") or "") != "proxy":
        raise ValueError("EarnApp Ubuntu runtime must use proxy bridge egress")
    if (spec.get("runtime_contract") or {}) != {
        "platform": UBUNTU_PLATFORM,
        "appid": UBUNTU_APPID,
        "device_id_prefix": UBUNTU_DEVICE_PREFIX,
    }:
        raise ValueError("EarnApp Ubuntu runtime contract is not verified")
    device_id = str(spec.get("expected_device_id") or "")
    if device_id and not re.fullmatch(r"sdk-node-[0-9a-f]{32}", device_id):
        raise ValueError("EarnApp Ubuntu expected device identity is invalid")
    labels = spec.get("labels") or {}
    if (spec.get("env") or {}).get("EARNAPP_DEVICE_ID") or labels.get("cashpilot.earnapp.device_id"):
        raise ValueError("EarnApp Ubuntu identity must be generated by the reference runtime")
    expected_egress = str((spec.get("env") or {}).get("EARNAPP_EXPECTED_EGRESS_IP") or "").strip()
    if not re.fullmatch(r"(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}", expected_egress):
        raise ValueError("EarnApp Ubuntu runtime requires an authoritative egress IP")
    proxy = spec.get("proxy") if isinstance(spec.get("proxy"), Mapping) else {}
    if str(proxy.get("country_code") or "").strip().upper() == "VN":
        raise ValueError("EarnApp Ubuntu runtime requires a non-VN residential proxy")
    if str(proxy.get("ip_type") or "").strip().lower() != "residential":
        raise ValueError("EarnApp Ubuntu runtime requires a residential proxy")
    if str(proxy.get("exit_ip") or "").strip() != expected_egress:
        raise ValueError("EarnApp Ubuntu runtime egress does not match proxy lease")
    if spec.get("runtime_assets"):
        raise ValueError("EarnApp Ubuntu reference runtime cannot mount an identity profile")


def encrypt_mac_profile(identity: dict[str, Any]) -> str:
    """Encode the official ESPF v1 profile consumed by ``boot.js``."""
    import base64
    import os

    plaintext = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    salt = os.urandom(16)
    nonce = os.urandom(12)
    aad = MAC_PROFILE_MAGIC + bytes([MAC_PROFILE_VERSION]) + salt
    ciphertext = AESGCM(MAC_PROFILE_KEY).encrypt(nonce, plaintext, aad)
    blob = aad + nonce + ciphertext
    return base64.b64encode(blob).decode("ascii")


def decrypt_mac_profile(value: str) -> dict[str, Any]:
    import base64

    blob = base64.b64decode(str(value or ""), validate=True)
    minimum = 4 + 1 + 16 + 12 + 16
    if len(blob) < minimum or blob[:4] != MAC_PROFILE_MAGIC or blob[4] != MAC_PROFILE_VERSION:
        raise ValueError("invalid EarnApp Mac profile envelope")
    nonce = blob[21:33]
    ciphertext = blob[33:]
    plaintext = AESGCM(MAC_PROFILE_KEY).decrypt(nonce, ciphertext, blob[:21])
    identity = json.loads(plaintext.decode("utf-8"))
    if not isinstance(identity, dict):
        raise ValueError("EarnApp Mac profile is not an object")
    validate_identity_contract(identity)
    return identity


def validate_identity_contract(identity: dict[str, Any]) -> None:
    required = {
        "id",
        "platform",
        "appid",
        "arch",
        "release",
        "ifname",
        "serial",
        "confdir",
        "uname_r",
        "os_version",
        "device_model",
        "ua",
        "perr_os_version",
        "makeflags",
        "lan_ip",
        "local_hostname",
    }
    missing = sorted(key for key in required if key not in identity)
    if missing:
        raise ValueError(f"EarnApp Mac profile is missing: {', '.join(missing)}")
    if identity.get("platform") != MAC_PLATFORM or identity.get("appid") != MAC_APPID:
        raise ValueError("EarnApp profile is not the Mac wire contract")
    if identity.get("idle") is not False or identity.get("ipv6_supported"):
        raise ValueError("EarnApp Mac profile has unsafe runtime flags")
    if "2movn" in json.dumps(identity, sort_keys=True).lower():
        raise ValueError("EarnApp lab identity is not allowed")


def validate_identity_asset_kind(asset_kind: str) -> str:
    value = str(asset_kind or "").strip().lower()
    if value != MAC_IDENTITY_ASSET_KIND:
        raise ValueError(f"EarnApp identity asset must be {MAC_IDENTITY_ASSET_KIND}")
    return value


def ensure_mac_identity(root: str | Path, *, seed: str) -> dict[str, str]:
    """Create a stable per-node identity marker without storing account secrets."""
    directory = Path(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "identity-contract.json"
    if path.is_file():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and value.get("platform") == MAC_PLATFORM:
                return {str(k): str(v) for k, v in value.items()}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
    digest = hashlib.sha256(str(seed).encode("utf-8")).hexdigest()[:32]
    value = {
        "platform": MAC_PLATFORM,
        "appid": MAC_APPID,
        "device_id": MAC_DEVICE_PREFIX + digest,
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
    return value


def validate_device_id(device_id: str) -> str:
    value = str(device_id or "").strip()
    if not re.fullmatch(r"sdk-mac-[A-Za-z0-9-]{4,96}", value):
        raise ValueError("EarnApp Mac device_id must use the sdk-mac- prefix")
    return value


def redacted_evidence(value: dict[str, Any] | None = None) -> dict[str, Any]:
    """Keep heartbeat evidence non-secret even if a caller passes raw metadata."""
    value = value if isinstance(value, dict) else {}
    blocked = {
        "password",
        "proxy_password",
        "proxy_username",
        "proxy_credentials",
        "username",
        "oauth-refresh-token",
        "xsrf-token",
        "credentials",
        "token",
        "identity",
        "machine_id",
        "serial",
    }

    def clean(item: Any) -> Any:
        if isinstance(item, dict):
            return {str(key): clean(child) for key, child in item.items() if str(key).lower() not in blocked}
        if isinstance(item, list):
            return [clean(child) for child in item]
        return item

    return clean(value)
