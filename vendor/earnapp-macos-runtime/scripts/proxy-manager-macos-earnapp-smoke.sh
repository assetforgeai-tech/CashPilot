#!/usr/bin/env bash
set -euo pipefail

ACTION=${1:-start}
INSTANCE=${INSTANCE:-earnapp-macos-001}
ROOT_DIR=${ROOT_DIR:-/opt/InternetIncome-run}
MAC_ROOT=${MAC_ROOT:-/opt/dockur-macos}
MAC_TOOLS=${MAC_TOOLS:-/opt/macos-on-vps}
SERVER_URL=${SERVER_URL:-https://proxy.acacondos.com}
PM_PROVIDER_ID=${PM_PROVIDER_ID:-earnapp}
PROVIDER_ID=${PROVIDER_ID:-earnapp-macos}
TARGET_EGRESS_IP=${TARGET_EGRESS_IP:-}
MANUAL_PROXY=${MANUAL_PROXY:-}
MANUAL_PROXY_SCHEME=${MANUAL_PROXY_SCHEME:-socks5}
MANUAL_PROXY_DNS_IPS=${MANUAL_PROXY_DNS_IPS:-1.1.1.1,8.8.8.8}
EARNAPP_SINGBOX_DNS_MODE=${EARNAPP_SINGBOX_DNS_MODE:-fakeip}
MAX_ATTEMPTS=${MAX_ATTEMPTS:-5}
RUNTIME=${RUNTIME:-internetincome-private}
RUNTIME_VERSION=${RUNTIME_VERSION:-macos-singbox-earnapp-smoke}
MACOS_IMAGE=${MACOS_IMAGE:-dockurr/macos@sha256:56f9f9dcf9a900cd47c8e21ab383a2b8164962a8325d42b492dcb7457ad752a3}
SING_BOX_IMAGE=${SING_BOX_IMAGE:-ghcr.io/sagernet/sing-box@sha256:c8b67944345dc84a226b648a71f854818606eae0813c4e6a452f192ef821b5b8}
PAUSE_IMAGE=${PAUSE_IMAGE:-registry.k8s.io/pause@sha256:ee6521f290b2168b6e0935a181d4cff9be1ac3f505666ef0e3c98fae8199917a}
MACOS_BASE_URL=${MACOS_BASE_URL:-}
MACOS_BASE_SHA256=${MACOS_BASE_SHA256:-}
MACOS_RECOVERY_URL=${MACOS_RECOVERY_URL:-}
MACOS_RECOVERY_SHA256=${MACOS_RECOVERY_SHA256:-}
MACOS_R2_ENV_FILE=${MACOS_R2_ENV_FILE:-$ROOT_DIR/secrets/macos-r2.env}
MACOS_R2_PRESIGN_EXPIRES_SECONDS=${MACOS_R2_PRESIGN_EXPIRES_SECONDS:-604800}
MACOS_RECOVERY_REQUIRED=${MACOS_RECOVERY_REQUIRED:-false}
MACOS_BASE_DOWNLOAD_TIMEOUT_SECONDS=${MACOS_BASE_DOWNLOAD_TIMEOUT_SECONDS:-3600}
BASE_IMAGE=${BASE_IMAGE:-$MAC_ROOT/storage/export/monterey12-os-only-1792m-v1-20260716T153103Z.qcow2}
BASE_SHA256=${BASE_SHA256:-${MACOS_BASE_SHA256:-cee45546058701852b822662971fbe1e8fc420e33eadc40c407ba239181324e3}}
RECOVERY_IMAGE=${RECOVERY_IMAGE:-$MAC_ROOT/assets/base.dmg}
NVRAM_TEMPLATE=${NVRAM_TEMPLATE:-$MAC_TOOLS/assets/macos_hd.vars.template}
API_TIMEOUT_SECONDS=${API_TIMEOUT_SECONDS:-90}
EARNAPP_AUTOINSTALL=${EARNAPP_AUTOINSTALL:-true}
EARNAPP_FAST_LINK=${EARNAPP_FAST_LINK:-false}
MACOS_ADMIN_USER=${MACOS_ADMIN_USER:-admin}
MACOS_ADMIN_PASSWORD=${MACOS_ADMIN_PASSWORD:-123456}
MACOS_RAM_SIZE=${MACOS_RAM_SIZE:-1200M}
MACOS_CPU_CORES=${MACOS_CPU_CORES:-1}
MACOS_START_STAGGER_SECONDS=${MACOS_START_STAGGER_SECONDS:-30}
MACOS_START_CONCURRENCY=${MACOS_START_CONCURRENCY:-3}
EARNAPP_EMAIL=${EARNAPP_EMAIL:-}
EARNAPP_AUTH_STATE_FILE=${EARNAPP_AUTH_STATE_FILE:-$ROOT_DIR/secrets/earnapp/earnapp-auth-state.json}
EARNAPP_MACOS_PKG_URL=${EARNAPP_MACOS_PKG_URL:-https://cdn.earnapp.com/static/earnapp-macos-1.605.415.pkg}
EARNAPP_MACOS_PKG_SHA256=${EARNAPP_MACOS_PKG_SHA256:-d1cdeec01a32a5ef3342ee67c42276af143b8b2a58e42211c476f515d0562f75}
EARNAPP_MACOS_VERSION=${EARNAPP_MACOS_VERSION:-1.605.415}
EARNAPP_LINK_ATTEMPTS=${EARNAPP_LINK_ATTEMPTS:-10}
EARNAPP_LINK_RETRY_SECONDS=${EARNAPP_LINK_RETRY_SECONDS:-20}
EARNAPP_LOCAL_RUNTIME_READY_MIN_HEARTBEATS=${EARNAPP_LOCAL_RUNTIME_READY_MIN_HEARTBEATS:-3}
EARNAPP_LOCAL_RUNTIME_READY_SECONDS=${EARNAPP_LOCAL_RUNTIME_READY_SECONDS:-300}
EARNAPP_LOCAL_RUNTIME_READY_POLL_SECONDS=${EARNAPP_LOCAL_RUNTIME_READY_POLL_SECONDS:-15}
EARNAPP_DASHBOARD_GREEN_SECONDS=${EARNAPP_DASHBOARD_GREEN_SECONDS:-600}
EARNAPP_DASHBOARD_GREEN_POLL_SECONDS=${EARNAPP_DASHBOARD_GREEN_POLL_SECONDS:-30}
EARNAPP_NETWORK_READY_SECONDS=${EARNAPP_NETWORK_READY_SECONDS:-300}
EARNAPP_NETWORK_RETRY_SLEEP_SECONDS=${EARNAPP_NETWORK_RETRY_SLEEP_SECONDS:-15}
EARNAPP_HEARTBEAT_INTERVAL_SECONDS=${EARNAPP_HEARTBEAT_INTERVAL_SECONDS:-600}
GUEST_NC_TIMEOUT_SECONDS=${GUEST_NC_TIMEOUT_SECONDS:-120}
MACOS_GUEST_SSH_WAIT_SECONDS=${MACOS_GUEST_SSH_WAIT_SECONDS:-2700}

suffix=${INSTANCE##*-}
case "$suffix" in
  ''|*[!0-9]*) echo "INSTANCE must end with numeric suffix, got $INSTANCE" >&2; exit 2 ;;
esac
ordinal=$((10#$suffix))
[ "$ordinal" -ge 1 ] && [ "$ordinal" -le 99 ] || { echo "INSTANCE suffix must be 001..099" >&2; exit 2; }
suffix3=$(printf "%03d" "$ordinal")
GROUP_ID=${GROUP_ID:-emac$suffix3}
WEB_PORT=${WEB_PORT:-$((18000 + ordinal))}
VNC_PORT=${VNC_PORT:-$((15900 + ordinal))}
SUBNET_OCTET=${SUBNET_OCTET:-$((120 + ordinal))}
NETNS_SUBNET="172.29.$SUBNET_OCTET.0/24"
NETNS_IP="172.29.$SUBNET_OCTET.2"
NETNS_GATEWAY="172.29.$SUBNET_OCTET.1"

FLEET_ID=${FLEET_ID:-}
FLEET_ENROLLMENT_TOKEN=${FLEET_ENROLLMENT_TOKEN:-}
HOST_ID_OVERRIDE=${HOST_ID:-}
HOST_ID_FILE=${HOST_ID_FILE:-${INTERNETINCOME_HOST_ID_FILE:-/var/lib/internetincome/host_id}}
HOST_ID=${HOST_ID_OVERRIDE:-$(hostname -f 2>/dev/null || hostname)}
if [ -f "$ROOT_DIR/secrets/internetincome-private.env" ]; then
  set -a
  # shellcheck disable=SC1090
  source <(sed '1s/^\xEF\xBB\xBF//;s/\r$//' "$ROOT_DIR/secrets/internetincome-private.env")
  set +a
fi
for config_file in "$ROOT_DIR/properties.conf"; do
  if [ -f "$config_file" ]; then
    set -a
    # shellcheck disable=SC1090
    source <(sed 's/\r$//' "$config_file")
    set +a
  fi
done
if [ -f "$MACOS_R2_ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source <(sed 's/\r$//' "$MACOS_R2_ENV_FILE")
  set +a
fi
EARNAPP_EMAIL=${EARNAPP_EMAIL:-}
if [ -z "$HOST_ID_OVERRIDE" ] && [ -s "$HOST_ID_FILE" ]; then
  HOST_ID=$(tr -d '\r\n' <"$HOST_ID_FILE")
fi
if [ "${CASHPILOT_STANDALONE:-false}" != "true" ]; then
  [ -n "$FLEET_ID" ] || { echo "missing FLEET_ID" >&2; exit 11; }
  [ -n "$FLEET_ENROLLMENT_TOKEN" ] || { echo "missing FLEET_ENROLLMENT_TOKEN" >&2; exit 12; }
fi

STATE="$ROOT_DIR/proxy-manager/groups/$GROUP_ID/$PROVIDER_ID"
INST_ROOT="$MAC_ROOT/fleet/instances/$INSTANCE"
COMPOSE="$INST_ROOT/compose.earnapp-singbox.yml"
REPORT="$STATE/macos-smoke-report.json"
export ROOT_DIR MAC_ROOT MAC_TOOLS INSTANCE GROUP_ID PROVIDER_ID PM_PROVIDER_ID SERVER_URL FLEET_ID FLEET_ENROLLMENT_TOKEN HOST_ID
export STATE INST_ROOT COMPOSE REPORT TARGET_EGRESS_IP MACOS_IMAGE SING_BOX_IMAGE PAUSE_IMAGE BASE_IMAGE BASE_SHA256 RECOVERY_IMAGE NVRAM_TEMPLATE
export WEB_PORT VNC_PORT NETNS_SUBNET NETNS_IP NETNS_GATEWAY SUBNET_OCTET MACOS_RAM_SIZE MACOS_CPU_CORES

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
}

run_start_step() {
  local label=$1
  shift
  local out="$STATE/start-failure-$label.log"
  mkdir -p "$STATE"
  if "$@" >"$out" 2>&1; then
    rm -f "$out"
    return 0
  fi
  {
    echo "--- docker ps ---"
    docker ps -a --format '{{.Names}} {{.Status}} {{.Image}}' || true
    echo "--- compose ps ---"
    [ -f "$COMPOSE" ] && docker compose -f "$COMPOSE" ps || true
  } >>"$out" 2>&1 || true
  cat "$out" >&2 || true
  return 1
}

is_valid_ip() {
  python3 - "$1" <<'PY'
import ipaddress
import sys

try:
    ipaddress.ip_address(sys.argv[1].strip())
except ValueError:
    sys.exit(1)
PY
}

api_post_json() {
  local path=$1 bearer=$2 payload=$3 out=$4 tmp body status
  tmp="$out.tmp"
  body="$out.error.json"
  mkdir -p "$(dirname "$out")"
  status=$(curl -sS --retry 4 --retry-delay 3 --retry-connrefused --connect-timeout 10 --max-time "$API_TIMEOUT_SECONDS" \
    -o "$tmp" \
    -w '%{http_code}' \
    -X POST "$SERVER_URL$path" \
    -H "Authorization: Bearer $bearer" \
    -H 'Content-Type: application/json' \
    -d "$payload") || {
      rm -f "$tmp"
      return 1
    }
  if [ "${status#2}" = "$status" ]; then
    mv "$tmp" "$body"
    jq 'del(.client_secret,.proxy.username,.proxy.password,.proxy.proxy_url,.token,.raw_token)' "$body" >&2 || true
    return 1
  fi
  chmod 0600 "$tmp"
  mv "$tmp" "$out"
  rm -f "$body"
}

with_file_lock() {
  local lock=$1
  shift
  mkdir -p "$(dirname "$lock")"
  if command -v flock >/dev/null 2>&1; then
    (
      flock -x 9
      "$@"
    ) 9>"$lock"
    return $?
  fi
  local lockdir="${lock}.d"
  while ! mkdir "$lockdir" 2>/dev/null; do
    sleep 5
  done
  "$@"
  local rc=$?
  rmdir "$lockdir" 2>/dev/null || true
  return "$rc"
}

acquire_macos_start_slot() {
  [ "$MACOS_START_CONCURRENCY" -gt 0 ] || return 0
  local i slot pid
  mkdir -p "$MAC_ROOT/locks"
  while :; do
    for i in $(seq 1 "$MACOS_START_CONCURRENCY"); do
      slot="$MAC_ROOT/locks/earnapp-macos-start.$i"
      if mkdir "$slot" 2>/dev/null; then
        printf '%s\n' "$$" >"$slot/pid"
        MACOS_START_SLOT="$slot"
        log "acquired macos slot $i/$MACOS_START_CONCURRENCY"
        return 0
      fi
      pid=$(cat "$slot/pid" 2>/dev/null || true)
      if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
        rm -rf "$slot"
      fi
    done
    sleep 10
  done
}

release_macos_start_slot() {
  [ -n "${MACOS_START_SLOT:-}" ] || return 0
  rm -rf "$MACOS_START_SLOT"
  MACOS_START_SLOT=""
}

ensure_macos_base_image() {
  with_file_lock "$BASE_IMAGE.lock" ensure_macos_base_image_locked
}

ensure_macos_base_image_locked() {
  local tmp actual expected
  expected=${BASE_SHA256#sha256:}
  if [ -s "$BASE_IMAGE" ]; then
    if [ -n "$expected" ] && command -v sha256sum >/dev/null 2>&1; then
      actual=$(sha256sum "$BASE_IMAGE" | awk '{print $1}')
      [ "$actual" = "$expected" ] || return 1
    fi
    return 0
  fi
  [ -n "$MACOS_BASE_URL" ] || return 1
  mkdir -p "$(dirname "$BASE_IMAGE")"
  tmp="$BASE_IMAGE.tmp.$$"
  rm -f "$tmp"
  if ! curl -fL --retry 3 --connect-timeout 20 --max-time "$MACOS_BASE_DOWNLOAD_TIMEOUT_SECONDS" -o "$tmp" "$MACOS_BASE_URL"; then
    rm -f "$tmp"
    return 1
  fi
  if [ -n "$expected" ]; then
    printf '%s  %s\n' "$expected" "$tmp" | sha256sum -c - >/dev/null || {
      rm -f "$tmp"
      return 1
    }
  fi
  chmod 0600 "$tmp"
  mv "$tmp" "$BASE_IMAGE"
}

ensure_macos_recovery_image() {
  [ -z "$RECOVERY_IMAGE" ] && return 0
  if [ ! -s "$RECOVERY_IMAGE" ] && [ "$MACOS_RECOVERY_REQUIRED" != "true" ] && [ -z "$MACOS_RECOVERY_URL" ]; then
    RECOVERY_IMAGE=""
    return 0
  fi
  with_file_lock "$RECOVERY_IMAGE.lock" ensure_macos_recovery_image_locked
}

ensure_macos_r2_urls() {
  [ -s "$MACOS_R2_ENV_FILE" ] || return 0
  [ -s "$ROOT_DIR/scripts/r2-presign-url.py" ] || return 0
  if [ -z "$MACOS_BASE_URL" ] && [ -n "${MACOS_R2_IMAGE_KEY:-}" ]; then
    MACOS_BASE_URL=$(python3 "$ROOT_DIR/scripts/r2-presign-url.py" \
      --env-file "$MACOS_R2_ENV_FILE" \
      --key "$MACOS_R2_IMAGE_KEY" \
      --expires "$MACOS_R2_PRESIGN_EXPIRES_SECONDS") || MACOS_BASE_URL=""
  fi
  if [ -z "$MACOS_RECOVERY_URL" ] && [ -n "${MACOS_R2_RECOVERY_KEY:-}" ]; then
    MACOS_RECOVERY_URL=$(python3 "$ROOT_DIR/scripts/r2-presign-url.py" \
      --env-file "$MACOS_R2_ENV_FILE" \
      --key "$MACOS_R2_RECOVERY_KEY" \
      --expires "$MACOS_R2_PRESIGN_EXPIRES_SECONDS") || MACOS_RECOVERY_URL=""
  fi
  export MACOS_BASE_URL MACOS_RECOVERY_URL
}

ensure_macos_recovery_image_locked() {
  local tmp actual expected
  expected=${MACOS_RECOVERY_SHA256#sha256:}
  if [ -s "$RECOVERY_IMAGE" ]; then
    if [ -n "$expected" ] && command -v sha256sum >/dev/null 2>&1; then
      actual=$(sha256sum "$RECOVERY_IMAGE" | awk '{print $1}')
      [ "$actual" = "$expected" ] || return 1
    fi
    return 0
  fi
  [ -n "$MACOS_RECOVERY_URL" ] || return 1
  mkdir -p "$(dirname "$RECOVERY_IMAGE")"
  tmp="$RECOVERY_IMAGE.tmp.$$"
  rm -f "$tmp"
  if ! curl -fL --retry 3 --connect-timeout 20 --max-time "$MACOS_BASE_DOWNLOAD_TIMEOUT_SECONDS" -o "$tmp" "$MACOS_RECOVERY_URL"; then
    rm -f "$tmp"
    return 1
  fi
  if [ -n "$expected" ]; then
    printf '%s  %s\n' "$expected" "$tmp" | sha256sum -c - >/dev/null || {
      rm -f "$tmp"
      return 1
    }
  fi
  chmod 0600 "$tmp"
  mv "$tmp" "$RECOVERY_IMAGE"
}

prune_macos_identity_claim() {
  python3 - "$INSTANCE" "$MAC_ROOT/identity/registry.jsonl" <<'PY'
import json
import os
import pathlib
import sys

instance_id, registry = sys.argv[1:3]
path = pathlib.Path(registry)
if not path.exists():
    raise SystemExit(0)
rows = []
for line in path.read_text().splitlines():
    try:
        row = json.loads(line)
    except Exception:
        continue
    if row.get("instance_id") != instance_id:
        rows.append(row)
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows))
os.replace(tmp, path)
PY
}

bootstrap_instance() {
  if [ -s "$INST_ROOT/bootstrap-result.json" ] \
    && jq -e '.status == "prepared" and (.paths.overlay // "") != ""' "$INST_ROOT/bootstrap-result.json" >/dev/null 2>&1 \
    && [ -s "$INST_ROOT/storage/12/data.qcow2" ] \
    && [ -s "$INST_ROOT/identity/controller_ed25519" ]; then
    return 0
  fi
  if [ -e "$INST_ROOT/bootstrap-result.json" ] || [ -e "$INST_ROOT/storage/12/data.qcow2" ]; then
    case "$(readlink -f "$INST_ROOT")" in
      "$(readlink -f "$MAC_ROOT/fleet/instances")/$INSTANCE") ;;
      *) echo "unsafe instance path: $INST_ROOT" >&2; exit 31 ;;
    esac
    stop_existing
    remove_instance_root
  fi
  mkdir -p "$INST_ROOT"
  local tmp_result="$INST_ROOT/bootstrap-result.json.tmp"
  local -a args=(
    --root "$MAC_ROOT/fleet/instances" \
    --instance-id "$INSTANCE" \
    --registry "$MAC_ROOT/identity/registry.jsonl" \
    --source-url "file://$BASE_IMAGE" \
    --source-sha256 "$BASE_SHA256" \
    --runtime-image "$MACOS_IMAGE" \
    --backing-directory "$(dirname "$BASE_IMAGE")" \
    --nvram-template "$NVRAM_TEMPLATE" \
    --preflight-path "$MAC_ROOT" \
  )
  [ -z "$RECOVERY_IMAGE" ] || args+=(--recovery-image "$RECOVERY_IMAGE")
  local attempt
  for attempt in 1 2; do
    rm -f "$tmp_result"
    if PYTHONPATH="$MAC_TOOLS/controller" python3 "$MAC_TOOLS/controller/bootstrap.py" bootstrap "${args[@]}" >"$tmp_result" \
      && jq -e '.status == "prepared" and (.paths.overlay // "") != ""' "$tmp_result" >/dev/null; then
      mv "$tmp_result" "$INST_ROOT/bootstrap-result.json"
      chmod 0600 "$INST_ROOT/bootstrap-result.json"
      return 0
    fi
    [ "$attempt" -eq 1 ] || return 1
    # ponytail: dockur SMBIOS probing can create a stale registry claim; retry once after pruning this instance.
    prune_macos_identity_claim
    remove_instance_root
    mkdir -p "$INST_ROOT"
  done
}

register_client() {
  local client_json="$STATE/client.json" reg_json="$STATE/register.json" enroll_json="$STATE/enrollment.json"
  local reg_id client_instance client_id client_secret
  mkdir -p "$STATE"
  reg_id="$FLEET_ID:$HOST_ID:$GROUP_ID:$PROVIDER_ID:v1"
  client_instance="$FLEET_ID:$HOST_ID:$GROUP_ID:$PROVIDER_ID"
  if [ -f "$client_json" ] && [ "$(jq -r '.host_id // empty' "$client_json")" = "$HOST_ID" ]; then
    return 0
  fi
  api_post_json "/api/client/register" "$FLEET_ENROLLMENT_TOKEN" "$(jq -n \
    --arg fleet_id "$FLEET_ID" \
    --arg host_id "$HOST_ID" \
    --arg client_instance "$client_instance" \
    --arg registration_id "$reg_id" \
    --arg runtime "$RUNTIME" \
    --arg runtime_version "$RUNTIME_VERSION" \
    '{fleet_id:$fleet_id,host_id:$host_id,client_instance:$client_instance,registration_id:$registration_id,runtime:$runtime,runtime_version:$runtime_version}')" "$reg_json"
  client_id=$(jq -r '.client_id // empty' "$reg_json")
  client_secret=$(jq -r '.client_secret // empty' "$reg_json")
  jq -n \
    --arg client_id "$client_id" \
    --arg client_secret "$client_secret" \
    --arg host_id "$HOST_ID" \
    --arg group_id "$GROUP_ID" \
    --arg provider_id "$PROVIDER_ID" \
    --arg client_instance "$client_instance" \
    --arg registration_id "$reg_id" \
    '{client_id:$client_id,client_secret:$client_secret,host_id:$host_id,group_id:$group_id,provider_id:$provider_id,client_instance:$client_instance,registration_id:$registration_id}' \
    >"$client_json"
  chmod 0600 "$client_json"
  api_post_json "/api/client/enrollment-ack" "$client_secret" "$(jq -n --arg client_id "$client_id" --arg registration_id "$reg_id" '{client_id:$client_id,registration_id:$registration_id}')" "$enroll_json"
}

request_lease() {
  local client_secret
  if [ -n "$MANUAL_PROXY" ]; then
    python3 - "$MANUAL_PROXY" "$MANUAL_PROXY_SCHEME" "$MANUAL_PROXY_DNS_IPS" "$TARGET_EGRESS_IP" >"$STATE/lease.json" <<'PY'
import json
import sys
from urllib.parse import urlparse

raw, scheme, dns_csv, egress = sys.argv[1:5]
host = port = username = password = ""
if "://" not in raw:
    parts = raw.split(":")
    if len(parts) >= 4:
        host, port, username, password = parts[0], int(parts[1]), parts[2], ":".join(parts[3:])
else:
    parsed = urlparse(raw)
    host = parsed.hostname or ""
    port = parsed.port or 0
    username = parsed.username or ""
    password = parsed.password or ""
dns_ips = [ip.strip() for ip in dns_csv.split(",") if ip.strip()]
if not host or not port:
    raise SystemExit("invalid_manual_proxy")
proxy = {
    "id": "manual",
    "scheme": scheme,
    "host": host,
    "endpoint_ip": host,
    "port": int(port),
    "status": "alive",
    "egress_ip": egress,
    "country": "",
    "dns_status": "manual",
    "dns": {"runtime_dns_ips": dns_ips, "resolver_ips": dns_ips, "status": "manual"},
}
if username:
    proxy["username"] = username
if password:
    proxy["password"] = password
print(json.dumps({"lease_id": "manual", "assignment_version": 1, "state": "ACTIVE", "provider_id": "earnapp", "proxy": proxy}))
PY
    jq 'del(.proxy.username,.proxy.password,.proxy.proxy_url)' "$STATE/lease.json" >"$STATE/lease.public.json"
    return 0
  fi
  client_secret=$(jq -r '.client_secret // empty' "$STATE/client.json")
  api_post_json "/api/client/request-proxy" "$client_secret" "$(jq -n \
    --arg provider_id "$PM_PROVIDER_ID" \
    --arg egress_ip "$TARGET_EGRESS_IP" \
    '{provider_id:$provider_id,workload:"macos-earnapp",requirements:({} + (if $egress_ip != "" then {egress_ip:$egress_ip} else {} end))}')" "$STATE/lease.json"
  jq 'del(.proxy.username,.proxy.password,.proxy.proxy_url)' "$STATE/lease.json" >"$STATE/lease.public.json"
}

request_earnapp_cookie() {
  local client_secret cookie_file cookie_file_name cookie_email
  client_secret=$(jq -r '.client_secret // empty' "$STATE/client.json")
  cookie_file="$STATE/earnapp-auth-state.json"
  api_post_json "/api/client/request-earnapp-cookie" "$client_secret" '{}' "$STATE/earnapp-cookie-lease.json"
  jq -e '.storage_state.cookies | length > 0' "$STATE/earnapp-cookie-lease.json" >/dev/null
  jq '.storage_state' "$STATE/earnapp-cookie-lease.json" >"$cookie_file"
  jq 'del(.storage_state)' "$STATE/earnapp-cookie-lease.json" >"$STATE/earnapp-cookie.public.json"
  chmod 0600 "$STATE/earnapp-cookie-lease.json" "$cookie_file" "$STATE/earnapp-cookie.public.json"
  cookie_file_name=$(jq -r '.file_name // empty' "$STATE/earnapp-cookie.public.json" 2>/dev/null || true)
  if [ -n "$cookie_file_name" ]; then
    cookie_email=${cookie_file_name%.json}
    case "$cookie_email" in
      *.gmail.com) EARNAPP_EMAIL="${cookie_email%.gmail.com}@gmail.com" ;;
      *@*) EARNAPP_EMAIL="$cookie_email" ;;
    esac
  fi
  EARNAPP_AUTH_STATE_FILE="$cookie_file"
  export EARNAPP_AUTH_STATE_FILE EARNAPP_EMAIL
}

heartbeat_earnapp_cookie() {
  local runtime_status=${1:-linked} out=${2:-$STATE/earnapp-cookie-heartbeat.json} client_secret cookie_id
  [ -f "$STATE/client.json" ] && [ -f "$STATE/earnapp-cookie-lease.json" ] || return 0
  client_secret=$(jq -r '.client_secret // empty' "$STATE/client.json")
  cookie_id=$(jq -r '.cookie_id // empty' "$STATE/earnapp-cookie-lease.json")
  [ -n "$client_secret" ] && [ -n "$cookie_id" ] || return 0
  api_post_json "/api/client/earnapp-cookie-heartbeat" "$client_secret" "$(jq -n \
    --arg cookie_id "$cookie_id" \
    --arg status "$runtime_status" \
    '{cookie_id:$cookie_id,status:$status}')" "$out" >/dev/null || return 1
}

release_lease() {
  local reason=${1:-INSTANCE_DESTROYED} client_secret lease_id assignment_version
  [ -z "$MANUAL_PROXY" ] || return 0
  [ -f "$STATE/client.json" ] && [ -f "$STATE/lease.json" ] || return 0
  client_secret=$(jq -r '.client_secret // empty' "$STATE/client.json")
  lease_id=$(jq -r '.lease_id // empty' "$STATE/lease.json")
  assignment_version=$(jq -r '.assignment_version // empty' "$STATE/lease.json")
  [ -n "$client_secret" ] && [ -n "$lease_id" ] && [ -n "$assignment_version" ] || return 0
  api_post_json "/api/client/release-proxy" "$client_secret" "$(jq -n \
    --arg lease_id "$lease_id" \
    --argjson assignment_version "$assignment_version" \
    --arg reason_code "$reason" \
    '{lease_id:$lease_id,assignment_version:$assignment_version,reason_code:$reason_code}')" "$STATE/lease.release.json" >/dev/null || true
}

stop_existing() {
  local c
  for c in "macos-$INSTANCE" "macos-$INSTANCE-egress" "macos-$INSTANCE-netns"; do
    docker update --restart=no "$c" >/dev/null 2>&1 || true
    docker rm -f "$c" >/dev/null 2>&1 || true
  done
  docker network rm "macos-$INSTANCE-egress" >/dev/null 2>&1 || true
  cleanup_stale_netns_routes
}

cleanup_stale_netns_routes() {
  local dev
  command -v ip >/dev/null 2>&1 || return 0
  while IFS= read -r dev; do
    case "$dev" in
      br-*) ip link delete "$dev" >/dev/null 2>&1 || ip route del "$NETNS_SUBNET" dev "$dev" >/dev/null 2>&1 || true ;;
    esac
  done < <(ip -o route show "$NETNS_SUBNET" 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "dev") print $(i + 1)}')
}

remove_instance_root() {
  case "$(readlink -f "$INST_ROOT" 2>/dev/null || true)" in
    "$(readlink -f "$MAC_ROOT/fleet/instances")/$INSTANCE") rm -rf "$INST_ROOT" ;;
    "") ;;
    *) echo "unsafe instance path: $INST_ROOT" >&2; exit 31 ;;
  esac
  local registry="$MAC_ROOT/identity/registry.jsonl"
  [ -f "$registry" ] || return 0
  REGISTRY_PATH="$registry" INSTANCE_TO_REMOVE="$INSTANCE" python3 - <<'PY'
import json
import os
from pathlib import Path

registry = Path(os.environ["REGISTRY_PATH"])
instance = os.environ["INSTANCE_TO_REMOVE"]
kept = []
for line in registry.read_text().splitlines():
    if not line.strip():
        continue
    try:
        row = json.loads(line)
    except Exception:
        kept.append(line)
        continue
    if row.get("instance_id") != instance:
        kept.append(json.dumps(row, sort_keys=True, separators=(",", ":")))
registry.write_text("\n".join(kept) + ("\n" if kept else ""))
PY
  chmod 600 "$registry"
}

render_files() {
  python3 - <<'PY'
import json
import os
from pathlib import Path

state = Path(os.environ["STATE"])
inst = Path(os.environ["INST_ROOT"])
lease = json.loads((state / "lease.json").read_text())
identity = None
for line in Path("/opt/dockur-macos/identity/registry.jsonl").read_text().splitlines():
    row = json.loads(line)
    if row.get("instance_id") == os.environ["INSTANCE"]:
        identity = row
        break
if not identity:
    raise SystemExit("missing_identity")

proxy = lease["proxy"]
scheme = proxy["scheme"]
endpoint = proxy.get("endpoint_ip") or proxy.get("host")
port = int(proxy["port"])
if scheme not in ("http", "socks5"):
    raise SystemExit("unsupported_scheme_" + scheme)
proxy_out = {"type": "socks", "tag": "proxy", "server": endpoint, "server_port": port, "version": "5"} if scheme == "socks5" else {"type": "http", "tag": "proxy", "server": endpoint, "server_port": port}
if proxy.get("username"):
    proxy_out["username"] = proxy["username"]
if proxy.get("password"):
    proxy_out["password"] = proxy["password"]
dns_ips = []
for ip in proxy.get("dns", {}).get("runtime_dns_ips") or proxy.get("dns", {}).get("resolver_ips") or []:
    if ip and ip not in dns_ips:
        dns_ips.append(ip)
if not dns_ips:
    raise SystemExit("missing_pm_dns")
dns_mode = os.environ.get("EARNAPP_SINGBOX_DNS_MODE", "fakeip")
if dns_mode == "fakeip":
    dns_server_tag = "strict-dns-blackhole"
    dns_servers = [
        {"type": "udp", "tag": "strict-dns-blackhole", "server": "192.0.2.53", "server_port": 53},
        {"type": "fakeip", "tag": "proxy-remote-fakeip", "inet4_range": "198.18.0.0/15"},
    ]
    dns_rules = [
        {"query_type": ["A", "AAAA"], "action": "route", "server": "proxy-remote-fakeip"},
        {"query_type": ["A", "AAAA"], "invert": True, "action": "reject", "method": "drop"},
    ]
else:
    dns_server_tag = "pm-dns-1"
    dns_servers = [
        {"type": "tcp", "tag": f"pm-dns-{index}", "server": ip, "server_port": 53, "detour": "proxy"}
        for index, ip in enumerate(dns_ips[:2], start=1)
    ]
    dns_rules = [
        {"query_type": ["A", "AAAA"], "action": "route", "server": dns_server_tag},
        {"query_type": ["A", "AAAA"], "invert": True, "action": "reject", "method": "drop"},
    ]

config = {
    "log": {"level": "info", "timestamp": True},
    "dns": {
        "servers": dns_servers,
        "final": dns_server_tag,
        "strategy": "ipv4_only",
        "rules": dns_rules,
    },
    "route": {
        "auto_detect_interface": True,
        "rules": [
            {"action": "sniff"},
            {"protocol": "dns", "action": "hijack-dns"},
            {"domain_suffix": ["cloudflare-dns.com", "one.one.one.one", "dns.google", "quad9.net", "opendns.com", "nextdns.io", "adguard-dns.com", "cleanbrowsing.org", "mask.icloud.com", "mask-h2.icloud.com", "mask-api.icloud.com"], "action": "reject", "method": "drop"},
            {"port": 53, "action": "reject", "method": "drop"},
            {"port": 853, "action": "reject", "method": "drop"},
            {"network": "udp", "action": "reject", "method": "drop"},
            {"ip_cidr": [os.environ["NETNS_SUBNET"], "172.30.0.0/16"], "outbound": "direct"},
            {"ip_is_private": True, "action": "reject", "method": "drop"},
        ],
        "final": "proxy",
        "default_domain_resolver": {"server": dns_server_tag, "strategy": "ipv4_only"},
    },
    "inbounds": [
        {"type": "mixed", "tag": "mixed-in", "listen": "127.0.0.1", "listen_port": 2080},
        {"type": "tun", "tag": "tun-in", "interface_name": "sb-tun", "address": ["172.19.0.1/30"], "route_address": ["0.0.0.0/0"], "auto_route": True, "strict_route": True, "stack": "system", "route_exclude_address": [f"{endpoint}/32", os.environ["NETNS_SUBNET"], "172.30.0.0/16"]},
    ],
    "outbounds": [proxy_out, {"type": "direct", "tag": "direct"}],
}
(inst / "sing-box").mkdir(parents=True, exist_ok=True)
(inst / "sing-box/config.json").write_text(json.dumps(config, indent=2) + "\n")
recovery_volume = f'\n      - {os.environ["RECOVERY_IMAGE"]}:/storage/12/base.dmg:ro' if os.environ.get("RECOVERY_IMAGE") else ""

compose = f'''name: "macos-{os.environ["INSTANCE"]}"
services:
  netns:
    image: "{os.environ["PAUSE_IMAGE"]}"
    container_name: macos-{os.environ["INSTANCE"]}-netns
    restart: always
    read_only: true
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    ports:
      - "127.0.0.1:{os.environ["WEB_PORT"]}:8006"
      - "127.0.0.1:{os.environ["VNC_PORT"]}:5900/tcp"
      - "127.0.0.1:{os.environ["VNC_PORT"]}:5900/udp"
    networks:
      egress:
        ipv4_address: {os.environ["NETNS_IP"]}
  sing-box:
    image: "{os.environ["SING_BOX_IMAGE"]}"
    container_name: macos-{os.environ["INSTANCE"]}-egress
    network_mode: service:netns
    depends_on:
      netns:
        condition: service_started
        restart: true
    command: [run, -c, /etc/sing-box/config.json]
    restart: always
    read_only: true
    init: true
    cap_drop: [ALL]
    cap_add: [NET_ADMIN]
    devices: [/dev/net/tun]
    security_opt: [no-new-privileges:true]
    volumes:
      - {inst}/sing-box/config.json:/etc/sing-box/config.json:ro
    tmpfs: ["/tmp:rw,noexec,nosuid,size=16m"]
    pids_limit: 64
    mem_limit: 128m
    cpus: 0.50
    healthcheck:
      test: [CMD, sing-box, check, -c, /etc/sing-box/config.json]
      interval: 15s
      timeout: 5s
      retries: 5
  macos:
    image: "{os.environ["MACOS_IMAGE"]}"
    container_name: macos-{os.environ["INSTANCE"]}
    network_mode: service:netns
    depends_on:
      sing-box:
        condition: service_healthy
        restart: true
    environment:
      VERSION: "12"
      MODEL: "{identity["model"]}"
      SN: "{identity["serial"]}"
      MLB: "{identity["mlb"]}"
      UUID: "{identity["uuid"]}"
      MAC: "{identity["mac"]}"
      HOST: "{identity["hostname"]}"
      CPU_MODEL: "Skylake-Server-v3"
      CPU_FLAGS: "-avx512f,-avx512dq,-avx512cd,-avx512bw,-avx512vl,-clwb,-pku,-pdpe1gb,-xsavec,-xgetbv1,-xsaves"
      RAM_SIZE: "{os.environ["MACOS_RAM_SIZE"]}"
      CPU_CORES: "{os.environ["MACOS_CPU_CORES"]}"
      VGA: "vmware"
      AUDIO: "N"
      ADAPTER: "virtio-net-pci"
      DISK_TYPE: "blk"
      DISK_SIZE: "64G"
      DISK_FMT: "qcow2"
      WIDTH: "1024"
      HEIGHT: "768"
      PICKER: "N"
      DNSMASQ_OPTS: "--no-resolv --server=192.0.2.53"
    devices: [/dev/kvm, /dev/net/tun]
    cap_add: [NET_ADMIN]
    volumes:
      - {inst}/storage:/storage
      - {os.environ["MAC_ROOT"]}/storage/export:/storage/export:ro{recovery_volume}
    restart: always
    stop_grace_period: 2m
networks:
  egress:
    name: "macos-{os.environ["INSTANCE"]}-egress"
    driver: bridge
    ipam:
      config:
        - subnet: {os.environ["NETNS_SUBNET"]}
          gateway: {os.environ["NETNS_GATEWAY"]}
'''
(inst / "compose.earnapp-singbox.yml").write_text(compose)
public = {
    "target_egress_ip": os.environ["TARGET_EGRESS_IP"],
    "lease_egress_ip": proxy.get("egress_ip"),
    "scheme": scheme,
    "endpoint_ip": endpoint,
    "port": port,
    "runtime_dns_ips": dns_ips,
    "dns_mode": dns_mode,
    "compose": str(inst / "compose.earnapp-singbox.yml"),
    "novnc_port": int(os.environ["WEB_PORT"]),
    "vnc_port": int(os.environ["VNC_PORT"]),
}
(state / "macos-network.public.json").write_text(json.dumps(public, indent=2) + "\n")
PY
  chmod 0600 "$INST_ROOT/sing-box/config.json" "$COMPOSE" "$STATE/macos-network.public.json"
}

apply_netns_firewall() {
  local pid endpoint port
  endpoint=$(jq -r '.proxy.endpoint_ip // .proxy.host' "$STATE/lease.json")
  port=$(jq -r '.proxy.port' "$STATE/lease.json")
  pid=$(docker inspect -f '{{.State.Pid}}' "macos-$INSTANCE-netns") || return 1
  [ -n "$pid" ] || return 1
  nsenter -t "$pid" -n iptables -F OUTPUT || true
  nsenter -t "$pid" -n iptables -P OUTPUT DROP || return 1
  nsenter -t "$pid" -n iptables -A OUTPUT -o lo -j ACCEPT || return 1
  nsenter -t "$pid" -n iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT || return 1
  nsenter -t "$pid" -n iptables -A OUTPUT -d "$NETNS_SUBNET" -j ACCEPT || return 1
  nsenter -t "$pid" -n iptables -A OUTPUT -d 172.30.0.0/16 -j ACCEPT || return 1
  nsenter -t "$pid" -n iptables -A OUTPUT -d 192.0.2.53/32 -j ACCEPT || return 1
  while IFS= read -r dns_ip; do
    [ -n "$dns_ip" ] || continue
    nsenter -t "$pid" -n iptables -A OUTPUT -d "$dns_ip/32" -p tcp --dport 53 -j ACCEPT || return 1
    nsenter -t "$pid" -n iptables -A OUTPUT -d "$dns_ip/32" -p udp --dport 53 -j ACCEPT || return 1
  done < <(jq -r '.proxy.dns.runtime_dns_ips[]?, .proxy.dns.resolver_ips[]?' "$STATE/lease.json" 2>/dev/null | awk 'NF && !seen[$0]++')
  nsenter -t "$pid" -n iptables -A OUTPUT -d "$endpoint" -p tcp --dport "$port" -j ACCEPT || return 1
}

wait_healthy() {
  local state
  for _ in $(seq 1 60); do
    state=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "macos-$INSTANCE-egress" 2>/dev/null || true)
    [ "$state" = healthy ] && return 0
    sleep 2
  done
  docker logs --tail 120 "macos-$INSTANCE-egress" >&2 || true
  return 1
}

capture_network_failure() {
  docker logs --tail 200 "macos-$INSTANCE-egress" >"$STATE/sing-box-failure.log" 2>&1 || true
  docker inspect "macos-$INSTANCE-netns" "macos-$INSTANCE-egress" >"$STATE/container-failure.inspect.json" 2>/dev/null || true
}

guest_ip() {
  docker logs "macos-$INSTANCE" 2>&1 | sed -n 's/.*Guest: \([^ ]*\).*/\1/p' | tail -1
}

guest_ssh_args() {
  local ip=$1 key=$2 nc_timeout=${3:-$GUEST_NC_TIMEOUT_SECONDS}
  printf '%s\n' \
    -i "$key" \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o ConnectTimeout=8 \
    -o "ProxyCommand=docker exec -i macos-$INSTANCE nc -w $nc_timeout $ip 22"
}

guest_password_ssh_args() {
  local ip=$1 nc_timeout=${2:-$GUEST_NC_TIMEOUT_SECONDS}
  printf '%s\n' \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o ConnectTimeout=8 \
    -o PubkeyAuthentication=no \
    -o PreferredAuthentications=password,keyboard-interactive \
    -o NumberOfPasswordPrompts=1 \
    -o "ProxyCommand=docker exec -i macos-$INSTANCE nc -w $nc_timeout $ip 22"
}

guest_password_ssh() {
  local ip=$1 command=$2
  command -v sshpass >/dev/null 2>&1 || return 1
  local -a ssh_args=()
  mapfile -t ssh_args < <(guest_password_ssh_args "$ip")
  SSHPASS="$MACOS_ADMIN_PASSWORD" sshpass -e ssh -n "${ssh_args[@]}" "$MACOS_ADMIN_USER@macos-smoke" "$command"
}

guest_password_scp_to() {
  local ip=$1 src=$2 dest=$3
  command -v sshpass >/dev/null 2>&1 || return 1
  local -a ssh_args=()
  mapfile -t ssh_args < <(guest_password_ssh_args "$ip")
  SSHPASS="$MACOS_ADMIN_PASSWORD" sshpass -e scp -q "${ssh_args[@]}" "$src" "$MACOS_ADMIN_USER@macos-smoke:$dest"
}

wait_guest_ssh() {
  local ip key
  local deadline=$((SECONDS + MACOS_GUEST_SSH_WAIT_SECONDS))
  while [ "$SECONDS" -lt "$deadline" ]; do
    ip=$(guest_ip)
    if [ -n "$ip" ]; then
      for key in "$INST_ROOT/identity/controller_ed25519" "$MAC_ROOT/keys/macos_admin_ed25519"; do
        [ -f "$key" ] || continue
        local -a ssh_args=()
        mapfile -t ssh_args < <(guest_ssh_args "$ip" "$key" 2)
        if ssh -n "${ssh_args[@]}" "$MACOS_ADMIN_USER@macos-smoke" true >/dev/null 2>&1; then
          printf '%s\n' "$ip"
          return 0
        fi
      done
      if guest_password_ssh "$ip" true >/dev/null 2>&1; then
        printf '%s\n' "$ip"
        return 0
      fi
    fi
    sleep 10
  done
  log "guest ssh timeout after ${MACOS_GUEST_SSH_WAIT_SECONDS}s"
  return 1
}

specialize_guest() {
  local ip=$1 boot_key instance_key script
  boot_key="$MAC_ROOT/keys/macos_admin_ed25519"
  instance_key="$INST_ROOT/identity/controller_ed25519"
  script="$INST_ROOT/identity/specialize-guest.sh"
  [ -f "$script" ] || return 0
  local -a ssh_args=()
  mapfile -t ssh_args < <(guest_ssh_args "$ip" "$instance_key")
  if ssh -n "${ssh_args[@]}" "$MACOS_ADMIN_USER@macos-smoke" true >/dev/null 2>&1; then
    return 0
  fi
  if [ -f "$boot_key" ]; then
    mapfile -t ssh_args < <(guest_ssh_args "$ip" "$boot_key")
    ssh "${ssh_args[@]}" "$MACOS_ADMIN_USER@macos-smoke" 'sudo -n /bin/bash -s' <"$script" && return 0
  fi
  if guest_password_ssh "$ip" true >/dev/null 2>&1; then
    local quoted_password
    printf -v quoted_password '%q' "$MACOS_ADMIN_PASSWORD"
    guest_password_scp_to "$ip" "$script" "/tmp/specialize-guest.sh"
    guest_password_ssh "$ip" "printf '%s\n' $quoted_password | sudo -S /bin/bash /tmp/specialize-guest.sh"
    return 0
  fi
  return 1
}

guest_ssh() {
  local ip=$1 command=$2 key="$INST_ROOT/identity/controller_ed25519"
  local -a ssh_args=()
  mapfile -t ssh_args < <(guest_ssh_args "$ip" "$key")
  ssh -n "${ssh_args[@]}" "$MACOS_ADMIN_USER@macos-smoke" "$command"
}

guest_pipe() {
  local ip=$1 command=$2 key="$INST_ROOT/identity/controller_ed25519"
  local -a ssh_args=()
  mapfile -t ssh_args < <(guest_ssh_args "$ip" "$key")
  ssh "${ssh_args[@]}" "$MACOS_ADMIN_USER@macos-smoke" "$command"
}

guest_scp_to() {
  local ip=$1 src=$2 dest=$3 key="$INST_ROOT/identity/controller_ed25519"
  local -a ssh_args=()
  mapfile -t ssh_args < <(guest_ssh_args "$ip" "$key")
  scp -q "${ssh_args[@]}" "$src" "$MACOS_ADMIN_USER@macos-smoke:$dest"
}

wait_earnapp_identity() {
  local ip=$1 uuid
  for _ in $(seq 1 60); do
    uuid=$(guest_ssh "$ip" 'defaults read com.earnapp registration_uuid 2>/dev/null || defaults read com.earnapp.brdsdk.shared uuid 2>/dev/null || true' | tr -d '\r' | tail -1)
    case "$uuid" in
      sdk-mac-????????????????????????????????)
        printf '%s\n' "$uuid" >"$STATE/earnapp-device-uuid.txt"
        return 0
      ;;
    esac
    sleep 5
  done
  return 1
}

wait_earnapp_local_runtime_ready() {
  local ip=$1 raw="$STATE/earnapp-local-runtime-ready.raw" result="$STATE/earnapp-local-runtime-ready.json"
  local deadline=$((SECONDS + EARNAPP_LOCAL_RUNTIME_READY_SECONDS))
  local ready app_config_file uuid cid support_cid_file brdsdk_log app_hb svc_hb
  while :; do
    ensure_earnapp_running "$ip" || true
    guest_pipe "$ip" 'bash -s' >"$raw" <<'GUEST' || true
support_dir="$HOME/Library/Application Support/com.earnapp"
app_config_file=$(find "$support_dir" -maxdepth 1 -type f -name '*perr_app_config_json_success.log' -print 2>/dev/null | sort | tail -1)
uuid=$(defaults read com.earnapp.brdsdk.shared uuid 2>/dev/null || defaults read com.earnapp registration_uuid 2>/dev/null || true)
cid=$(cat "$support_dir/com.earnapp.cid" 2>/dev/null || true)
support_cid_file=$(find "$support_dir" -maxdepth 1 -type f -name 'com.earnapp*.cid' -print 2>/dev/null | sort | tail -1)
brdsdk_log=$(find "$support_dir/brdsdk" -maxdepth 1 -type f -name 'lum_sdk_svc*.log' -print 2>/dev/null | sort | tail -1)
app_hb=$(defaults read com.earnapp.brdsdk.shared app_hb_count 2>/dev/null || true)
svc_hb=$(defaults read com.earnapp.brdsdk.shared svc_hb_count 2>/dev/null || true)
printf 'app_config_file=%s\n' "$app_config_file"
printf 'uuid=%s\n' "$uuid"
printf 'cid=%s\n' "$cid"
printf 'support_cid_file=%s\n' "$support_cid_file"
printf 'brdsdk_log=%s\n' "$brdsdk_log"
printf 'app_hb=%s\n' "$app_hb"
printf 'svc_hb=%s\n' "$svc_hb"
GUEST
    ready=false
    app_config_file=$(sed -n 's/^app_config_file=//p' "$raw" 2>/dev/null | tail -1)
    uuid=$(sed -n 's/^uuid=//p' "$raw" 2>/dev/null | tail -1)
    cid=$(sed -n 's/^cid=//p' "$raw" 2>/dev/null | tail -1)
    support_cid_file=$(sed -n 's/^support_cid_file=//p' "$raw" 2>/dev/null | tail -1)
    brdsdk_log=$(sed -n 's/^brdsdk_log=//p' "$raw" 2>/dev/null | tail -1)
    app_hb=$(sed -n 's/^app_hb=//p' "$raw" 2>/dev/null | tail -1)
    svc_hb=$(sed -n 's/^svc_hb=//p' "$raw" 2>/dev/null | tail -1)
    if [[ "$uuid" == sdk-mac-???????????????????????????????? ]] \
      && [ -n "$cid" ] \
      && [ -n "$support_cid_file" ] \
      && [ -n "$brdsdk_log" ] \
      && [[ "$app_hb" =~ ^[0-9]+$ ]] \
      && [[ "$svc_hb" =~ ^[0-9]+$ ]] \
      && [ "$app_hb" -ge "$EARNAPP_LOCAL_RUNTIME_READY_MIN_HEARTBEATS" ] \
      && [ "$svc_hb" -ge "$EARNAPP_LOCAL_RUNTIME_READY_MIN_HEARTBEATS" ]; then
      ready=true
    fi
    jq -n \
      --argjson ready "$ready" \
      --arg app_config_file "$app_config_file" \
      --arg uuid "$uuid" \
      --arg cid "$cid" \
      --arg support_cid_file "$support_cid_file" \
      --arg brdsdk_log "$brdsdk_log" \
      --arg app_hb "$app_hb" \
      --arg svc_hb "$svc_hb" \
      '{ready:$ready,app_config_file:$app_config_file,device_uuid:$uuid,cid:$cid,support_cid_file:$support_cid_file,brdsdk_log:$brdsdk_log,app_hb:$app_hb,svc_hb:$svc_hb,checked_at:(now|todate)}' \
      >"$result"
    [ "$ready" = true ] && return 0
    [ "$SECONDS" -ge "$deadline" ] && return 1
    sleep "$EARNAPP_LOCAL_RUNTIME_READY_POLL_SECONDS"
  done
}

earnapp_proxy_curl() {
  local output=$1 output_dir output_base
  shift
  output_dir=$(dirname "$output")
  output_base=$(basename "$output")
  docker run --rm \
    --user 0:0 \
    --network "container:macos-$INSTANCE-netns" \
    -v "$output_dir:/curl-out" \
    curlimages/curl:latest \
    -sS --connect-timeout 30 --max-time 90 \
    -x socks5h://127.0.0.1:2080 \
    -o "/curl-out/$output_base" \
    -w '%{http_code}' \
    "$@" || true
}

link_earnapp_device() {
  local ip=$1 prep_script="$INST_ROOT/earnapp-link-device.py" result="$STATE/earnapp-link-result.json" uuid_file="$STATE/earnapp-device-uuid.txt" effective_url_file="$STATE/earnapp-register-url.effective.txt" cookie_header_file="$INST_ROOT/earnapp-cookie-header.txt" xsrf_file="$INST_ROOT/earnapp-xsrf.txt"
  [ -s "$EARNAPP_AUTH_STATE_FILE" ] || { jq -n '{status:"skipped_missing_auth_state"}' >"$result"; return 2; }
  wait_earnapp_identity "$ip" || true
  cat >"$prep_script" <<'PY'
import json
import re
import urllib.parse
from pathlib import Path

auth_state = json.loads(Path("__AUTH_STATE_FILE__").read_text())
register_url = Path("__REGISTER_URL_FILE__").read_text().strip() if Path("__REGISTER_URL_FILE__").exists() else ""
fallback_uuid = Path("__DEVICE_UUID_FILE__").read_text().strip() if Path("__DEVICE_UUID_FILE__").exists() else ""
uuid_match = re.search(r"(sdk-(?:mac|node)-[0-9a-fA-F]{32})", register_url)
device_uuid = uuid_match.group(1) if uuid_match else fallback_uuid
if not register_url and device_uuid:
    register_url = f"https://earnapp.com/dashboard/link/{device_uuid}"
cookie_pairs = []
xsrf = ""
for cookie in auth_state.get("cookies", []):
    if "earnapp.com" not in str(cookie.get("domain", "")):
        continue
    cookie_pairs.append(f"{cookie.get('name', '')}={cookie.get('value', '')}")
    if cookie.get("name") == "xsrf-token":
        xsrf = urllib.parse.unquote(str(cookie.get("value", "")))
Path("__DEVICE_UUID_FILE__").write_text(device_uuid)
Path("__EFFECTIVE_REGISTER_URL_FILE__").write_text(register_url)
Path("__COOKIE_HEADER_FILE__").write_text("; ".join(cookie_pairs))
Path("__XSRF_FILE__").write_text(xsrf)
PY
  sed -i \
    -e "s#__AUTH_STATE_FILE__#$EARNAPP_AUTH_STATE_FILE#g" \
    -e "s#__REGISTER_URL_FILE__#$STATE/earnapp-register-url.txt#g" \
    -e "s#__DEVICE_UUID_FILE__#$uuid_file#g" \
    -e "s#__EFFECTIVE_REGISTER_URL_FILE__#$effective_url_file#g" \
    -e "s#__COOKIE_HEADER_FILE__#$cookie_header_file#g" \
    -e "s#__XSRF_FILE__#$xsrf_file#g" \
    "$prep_script"
  python3 "$prep_script"
  if [ ! -s "$uuid_file" ] || [ ! -s "$effective_url_file" ]; then
    jq -n --arg uuid "$(cat "$uuid_file" 2>/dev/null || true)" '{status:"failed_missing_device_uuid",device_uuid:$uuid,register_url_present:false}' >"$result"
    return 1
  fi
  chmod 0600 "$prep_script" "$effective_url_file" "$cookie_header_file" "$xsrf_file"
  local cookie xsrf uuid register_url user_body link_body devices_body user_status link_status devices_status device_present ok_marker not_found status link_attempt link_attempts
  cookie=$(cat "$cookie_header_file")
  xsrf=$(cat "$xsrf_file")
  uuid=$(cat "$uuid_file")
  register_url=$(cat "$effective_url_file")
  link_attempts=$EARNAPP_LINK_ATTEMPTS
  status=failed
  for link_attempt in $(seq 1 "$link_attempts"); do
    user_body=$(mktemp)
    link_body=$(mktemp)
    devices_body=$(mktemp)
    user_status=$(earnapp_proxy_curl "$user_body" -H "Cookie: $cookie" -H "User-Agent: Mozilla/5.0" https://earnapp.com/dashboard/api/user_data)
    link_status=$(earnapp_proxy_curl "$link_body" -H "Cookie: $cookie" -H "User-Agent: Mozilla/5.0" -H "Accept: application/json, text/plain, */*" -H "Origin: https://earnapp.com" -H "Referer: $register_url" -H "xsrf-token: $xsrf" -H "X-XSRF-TOKEN: $xsrf" -H "Content-Type: application/json" -X POST https://earnapp.com/dashboard/api/link_device -d "{\"data\":{\"uuid\":\"$uuid\",\"platform\":\"macos\"}}")
    devices_status=$(earnapp_proxy_curl "$devices_body" -H "Cookie: $cookie" -H "User-Agent: Mozilla/5.0" https://earnapp.com/dashboard/api/devices)
    grep -q "$uuid" "$devices_body" && device_present=true || device_present=false
    grep -q '"status":"ok"' "$link_body" && ok_marker=true || ok_marker=false
    grep -qi "device.*not.*found" "$link_body" && not_found=true || not_found=false
    if [ "$user_status" = 200 ] && [ "$not_found" = false ] && { [ "$device_present" = true ] || [ "$ok_marker" = true ]; }; then
      status=linked
    elif [ "$user_status" = 401 ] || [ "$user_status" = 403 ]; then
      status=auth_failed
    elif [ "$not_found" = true ]; then
      status=device_not_found
    elif [ "$link_status" = 429 ]; then
      status=rate_limited
    else
      status=failed
    fi
    jq -n \
      --arg status "$status" \
      --arg uuid "$uuid" \
      --arg attempt "$link_attempt" \
      --argjson register_url_present "$([ -n "$register_url" ] && echo true || echo false)" \
      --arg user_status "${user_status:-000}" \
      --arg link_status "${link_status:-000}" \
      --arg devices_status "${devices_status:-000}" \
      --argjson device_present "$device_present" \
      --argjson ok_marker "$ok_marker" \
      --argjson not_found "$not_found" \
      '{status:$status,attempt:($attempt|tonumber),register_url_present:$register_url_present,device_uuid:$uuid,user_data_status:$user_status,link_device_status:$link_status,devices_status:$devices_status,device_present:$device_present,link_ok:$ok_marker,not_found:$not_found}' \
      >"$result"
    rm -f "$user_body" "$link_body" "$devices_body"
    [ "$status" = linked ] && break
    [ "$status" = rate_limited ] && break
    [ "$status" = auth_failed ] && break
    [ "$link_attempt" -lt "$link_attempts" ] && sleep "$EARNAPP_LINK_RETRY_SECONDS"
  done
  rm -f "$cookie_header_file" "$xsrf_file"
  if [ "$status" = linked ]; then
    echo "EARNAPP_DEVICE_UUID=$uuid"
    heartbeat_earnapp_cookie linked || true
    guest_ssh "$ip" 'pkill -f "/Applications/EarnApp.app/Contents/MacOS/earnapp" >/dev/null 2>&1 || true; nohup open -a EarnApp >/dev/null 2>&1 & nohup open -a Safari https://earnapp.com/dashboard/me/passive-income >/dev/null 2>&1 &' || true
    return 0
  fi
  jq . "$result" >/dev/null 2>&1 || jq -n '{status:"failed"}' >"$result"
  if jq -e '(.user_data_status == "401") or (.user_data_status == "403")' "$result" >/dev/null 2>&1; then
    heartbeat_earnapp_cookie COOKIE_AUTH_FAILED || true
  fi
  return 1
}

ensure_earnapp_running() {
  local ip=$1
  for _ in $(seq 1 6); do
    if guest_ssh "$ip" 'pgrep -f "/Applications/EarnApp.app/Contents/MacOS/earnapp" >/dev/null'; then
      return 0
    fi
    guest_ssh "$ip" 'open -a EarnApp >/dev/null 2>&1' || true
    sleep 10
  done
  guest_ssh "$ip" 'pgrep -f "/Applications/EarnApp.app/Contents/MacOS/earnapp" >/dev/null'
}

close_earnapp_browsers() {
  local ip=$1
  guest_ssh "$ip" "pkill -x Safari >/dev/null 2>&1 || true; pkill -x 'Google Chrome' >/dev/null 2>&1 || true; pkill -x Chromium >/dev/null 2>&1 || true" || true
}

write_earnapp_dashboard_status() {
  local status_file="$STATE/earnapp-dashboard-status.json"
  [ -s "$EARNAPP_AUTH_STATE_FILE" ] || { jq -n '{status:"missing_auth_state",green_dot:false}' >"$status_file"; return 1; }
  [ -s "$STATE/earnapp-device-uuid.txt" ] || { jq -n '{status:"missing_device_uuid",green_dot:false}' >"$status_file"; return 1; }
  python3 - "$EARNAPP_AUTH_STATE_FILE" "$STATE/earnapp-device-uuid.txt" "$status_file" <<'PY'
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

auth_file, uuid_file, out_file = map(Path, sys.argv[1:4])
device_uuid = uuid_file.read_text().strip()
auth_state = json.loads(auth_file.read_text())
cookie_pairs = []
xsrf = ""
for cookie in auth_state.get("cookies", []):
    if "earnapp.com" not in str(cookie.get("domain", "")):
        continue
    name = str(cookie.get("name", ""))
    value = str(cookie.get("value", ""))
    if not name:
        continue
    cookie_pairs.append(f"{name}={value}")
    if name == "xsrf-token":
        xsrf = urllib.parse.unquote(value)
cookie_header = "; ".join(cookie_pairs)

def request_json(url, method="GET", payload=None):
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json, text/plain, */*"}
    if cookie_header:
        headers["Cookie"] = cookie_header
    if xsrf:
        headers["xsrf-token"] = xsrf
        headers["X-XSRF-TOKEN"] = xsrf
    body = None
    if payload is not None:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
        headers["Origin"] = "https://earnapp.com"
        headers["Referer"] = "https://earnapp.com/dashboard/me/passive-income"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers, method=method), timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw[:200]
        return exc.code, parsed
    except Exception as exc:
        return 0, {"error": str(exc)}

version = ""
try:
    headers = {"User-Agent": "Mozilla/5.0", "Cookie": cookie_header}
    with urllib.request.urlopen(urllib.request.Request("https://earnapp.com/dashboard/me/passive-income", headers=headers), timeout=30) as resp:
        html = resp.read().decode("utf-8", "replace")
    match = re.search(r'"ver"\s*:\s*"([^"]+)"', html)
    version = match.group(1) if match else ""
except Exception:
    pass

query = {"appid": "earnapp"}
if version:
    query["version"] = version
qs = urllib.parse.urlencode(query)
devices_http, devices_body = request_json(f"https://earnapp.com/dashboard/api/devices?{qs}")
device_rows = devices_body if isinstance(devices_body, list) else devices_body.get("devices", []) if isinstance(devices_body, dict) else []
device = next((item for item in device_rows if isinstance(item, dict) and item.get("uuid") == device_uuid), None)
devices = [item.get("uuid") for item in device_rows if isinstance(item, dict) and item.get("uuid")]
if device_uuid and device_uuid not in devices:
    devices.append(device_uuid)
statuses_http, statuses_body = request_json(
    f"https://earnapp.com/dashboard/api/device_statuses?{qs}",
    method="POST",
    payload={"data": {"devices": devices}},
)
meta = statuses_body.get(device_uuid) if isinstance(statuses_body, dict) else None
green = bool(meta[0]) if isinstance(meta, list) and meta else False
status = {
    "status": "green" if green else "gray",
    "device_uuid": device_uuid,
    "dashboard_version": version,
    "devices_http": devices_http,
    "device_statuses_http": statuses_http,
    "device_present": bool(device),
    "green_dot": green,
    "status_meta": meta,
    "device": {key: device.get(key) for key in ("uuid", "title", "rate", "earned", "earned_total", "country", "ips", "billing", "uptime", "total_uptime", "banned")} if device else {},
}
out_file.write_text(json.dumps(status, indent=2) + "\n")
sys.exit(0 if green else 1)
PY
}

wait_earnapp_dashboard_green() {
  local ip=$1
  local deadline=$((SECONDS + EARNAPP_DASHBOARD_GREEN_SECONDS))
  while :; do
    ensure_earnapp_running "$ip" || true
    if write_earnapp_dashboard_status; then
      close_earnapp_browsers "$ip"
      return 0
    fi
    [ "$SECONDS" -ge "$deadline" ] && return 1
    sleep "$EARNAPP_DASHBOARD_GREEN_POLL_SECONDS"
  done
}

install_earnapp_macos() {
  local ip=$1
  local package_script="$INST_ROOT/install-earnapp-package.sh"
  local config_script="$INST_ROOT/configure-earnapp-macos.sh"
  local registered_to_line
  [ "$EARNAPP_AUTOINSTALL" = true ] || return 0
  if [ -n "$EARNAPP_EMAIL" ]; then
    printf -v registered_to_line 'defaults write com.earnapp registered_to %q' "$EARNAPP_EMAIL"
  else
    registered_to_line='defaults delete com.earnapp registered_to >/dev/null 2>&1 || true'
  fi
  cat >"$package_script" <<EOF
#!/bin/bash
set -euo pipefail
pkg=/tmp/earnapp-macos.pkg
if [ ! -d /Applications/EarnApp.app ]; then
  curl -fL --retry 3 --connect-timeout 20 --max-time 180 -o "\$pkg" "$EARNAPP_MACOS_PKG_URL"
  printf '%s  %s\n' "$EARNAPP_MACOS_PKG_SHA256" "\$pkg" | shasum -a 256 -c -
  printf '%s\n' "$MACOS_ADMIN_PASSWORD" | sudo -S installer -pkg "\$pkg" -target /
fi
EOF
  chmod 0600 "$package_script"
  guest_scp_to "$ip" "$package_script" "/tmp/install-earnapp-package.sh"
  if ! guest_ssh "$ip" 'chmod 700 /tmp/install-earnapp-package.sh && /tmp/install-earnapp-package.sh'; then
    guest_ssh "$ip" 'test -d /Applications/EarnApp.app'
  fi
  guest_ssh "$ip" 'test -d /Applications/EarnApp.app && sleep 3'
  cat >"$config_script" <<EOF
#!/bin/bash
set -euo pipefail
mkdir -p "\$HOME/Library/Application Support/com.earnapp"
defaults write com.earnapp autorun -bool true
defaults write com.earnapp consent_displayed -bool true
defaults write com.earnapp enable_on_start -bool true
$registered_to_line
defaults write com.earnapp update_url ""
defaults write com.earnapp update_ver ""
defaults write com.earnapp zon_version "$EARNAPP_MACOS_VERSION"
defaults write com.earnapp.brdsdk.shared ver_install "$EARNAPP_MACOS_VERSION"
defaults write com.earnapp.brdsdk.shared http3Enabled -bool true
defaults write com.earnapp.brdsdk.shared proxyjsDNSResolve -bool true
nohup open -a EarnApp >/dev/null 2>&1 &
sleep 8
exit 0
EOF
  chmod 0600 "$config_script"
  guest_scp_to "$ip" "$config_script" "/tmp/configure-earnapp-macos.sh"
  guest_ssh "$ip" 'chmod 700 /tmp/configure-earnapp-macos.sh && /tmp/configure-earnapp-macos.sh'
  ensure_earnapp_running "$ip"
  wait_earnapp_identity "$ip" || true
  if [ -s "$STATE/earnapp-device-uuid.txt" ]; then
    local device_uuid
    device_uuid=$(cat "$STATE/earnapp-device-uuid.txt")
    guest_ssh "$ip" "defaults write com.earnapp registration_uuid '$device_uuid'; defaults write com.earnapp.brdsdk.shared uuid '$device_uuid'; pkill -f '/Applications/EarnApp.app/Contents/MacOS/earnapp' >/dev/null 2>&1 || true; sleep 2; open -a EarnApp >/dev/null 2>&1; sleep 5" || true
  fi
  if [ "$EARNAPP_FAST_LINK" = true ]; then
    link_earnapp_device "$ip"
    return $?
  fi
  wait_earnapp_local_runtime_ready "$ip" || return 1
  link_earnapp_device "$ip"
}

probe_egress_ip() {
  local url ip
  for url in https://api.ipify.org https://ifconfig.me/ip https://icanhazip.com; do
    ip=$(docker run --rm --network "container:macos-$INSTANCE-netns" curlimages/curl:latest -fsS --connect-timeout 15 --max-time 45 -x socks5h://127.0.0.1:2080 "$url" 2>/dev/null | tr -d '[:space:]' || true)
    if is_valid_ip "$ip" 2>/dev/null; then
      printf '%s\n' "$ip"
      return 0
    fi
  done
  return 1
}

probe_http_code() {
  local url=$1 code
  for _ in 1 2 3; do
    code=$(docker run --rm --network "container:macos-$INSTANCE-netns" curlimages/curl:latest -ksS -o /dev/null -w '%{http_code}' --connect-timeout 30 --max-time 90 -x socks5h://127.0.0.1:2080 "$url" 2>/dev/null || true)
    [ -n "$code" ] || code=000
    [ "$code" != 000 ] && break
    sleep 5
  done
  printf '%s\n' "${code:-000}"
}

probe_and_ack() {
  local egress client_code dashboard_code proxyjs_code client_secret lease_id assignment_version dns_status
  egress=$(probe_egress_ip || true)
  client_code=$(probe_http_code https://client.earnapp.com/)
  dashboard_code=$(probe_http_code https://earnapp.com/dashboard)
  proxyjs_code=$(probe_http_code https://proxyjs.brdtnet.com/)
  client_secret=$(jq -r '.client_secret // empty' "$STATE/client.json")
  lease_id=$(jq -r '.lease_id // empty' "$STATE/lease.json")
  assignment_version=$(jq -r '.assignment_version // empty' "$STATE/lease.json")
  dns_status=$(jq -r '.proxy.dns_status // "proxy_remote"' "$STATE/lease.json")
  if [ -n "$egress" ]; then
    if [ -z "$MANUAL_PROXY" ]; then
      api_post_json "/api/client/proxy-ack" "$client_secret" "$(jq -n \
        --arg lease_id "$lease_id" \
        --argjson assignment_version "$assignment_version" \
        --arg egress_ip "$egress" \
        --arg dns_status "$dns_status" \
        '{lease_id:$lease_id,assignment_version:$assignment_version,config_hash:"sha256:macos-singbox-earnapp-smoke",egress_ip:$egress_ip,dns_status:$dns_status,runtime_status:"healthy"}')" "$STATE/lease.ack.json" || true
      jq -s '.[0] * .[1]' "$STATE/lease.json" "$STATE/lease.ack.json" >"$STATE/lease.json.acked" 2>/dev/null && mv "$STATE/lease.json.acked" "$STATE/lease.json" || rm -f "$STATE/lease.json.acked"
    fi
    jq --arg egress_ip "$egress" --arg dns_status "$dns_status" '.proxy.runtime_egress_ip = $egress_ip | (if (.proxy.egress_ip // "") == "" then .proxy.egress_ip = $egress_ip else . end) | .egress_ip = $egress_ip | .dns_status = $dns_status | .runtime_status = "healthy" | .config_hash = "sha256:macos-singbox-earnapp-smoke"' "$STATE/lease.json" >"$STATE/lease.json.merged"
    mv "$STATE/lease.json.merged" "$STATE/lease.json"
    jq 'del(.proxy.username,.proxy.password,.proxy.proxy_url)' "$STATE/lease.json" >"$STATE/lease.public.json"
  fi
  jq -n \
    --arg target "$TARGET_EGRESS_IP" \
    --arg lease_egress "$(jq -r '.proxy.egress_ip // empty' "$STATE/lease.json")" \
    --arg observed "$egress" \
    --arg client "$client_code" \
    --arg dashboard "$dashboard_code" \
    --arg proxyjs "$proxyjs_code" \
    --slurpfile network "$STATE/macos-network.public.json" \
    '{target_egress_ip:$target,lease_egress_ip:$lease_egress,observed_egress_ip:$observed,egress_match:($lease_egress==$observed),tcp_client_earnapp_http_code:$client,tcp_dashboard_http_code:$dashboard,tcp_proxyjs_http_code:$proxyjs,network:$network[0]}' \
    >"$REPORT"
}

network_report_ready() {
  if [ -n "$MANUAL_PROXY" ]; then
    [ -n "$(jq -r '.observed_egress_ip // empty' "$REPORT")" ] || return 1
    ! jq -e '(.tcp_dashboard_http_code == "000") or (.tcp_proxyjs_http_code == "000")' "$REPORT" >/dev/null
    return $?
  fi
  [ "$(jq -r '.egress_match' "$REPORT")" = true ] || return 1
  ! jq -e '(.tcp_dashboard_http_code == "000") or (.tcp_proxyjs_http_code == "000")' "$REPORT" >/dev/null
}

wait_network_ready() {
  local deadline=$((SECONDS + EARNAPP_NETWORK_READY_SECONDS))
  while :; do
    probe_and_ack || return 1
    network_report_ready && return 0
    [ "$SECONDS" -ge "$deadline" ] && return 1
    sleep "$EARNAPP_NETWORK_RETRY_SLEEP_SECONDS"
  done
}

start_once() {
  rm -f \
    "$STATE/lease.json" "$STATE/lease.public.json" "$STATE/lease.ack.json" \
    "$REPORT" "$STATE/macos-network.public.json" \
    "$STATE/earnapp-local-runtime-ready.json" "$STATE/earnapp-local-runtime-ready.raw" \
    "$STATE/earnapp-link-result.json" "$STATE/earnapp-dashboard-status.json" \
    "$STATE/earnapp-device-uuid.txt" "$STATE/earnapp-register-url.txt" "$STATE/earnapp-register-url.effective.txt"
  ensure_macos_r2_urls
  if ! ensure_macos_base_image; then
    log "MACOS_BASE_UNAVAILABLE"
    return 8
  fi
  if ! ensure_macos_recovery_image; then
    log "MACOS_RECOVERY_UNAVAILABLE"
    return 8
  fi
  log "bootstrap instance"
  if ! run_start_step bootstrap bootstrap_instance; then
    remove_instance_root
    return 7
  fi
  stop_existing
  log "request lease"
  request_lease || { log "REQUEST_LEASE_FAILED"; return 9; }
  log "render files"
  render_files || { release_lease RUNTIME_UNHEALTHY; return 7; }
  run_start_step compose-config docker compose -f "$COMPOSE" config || { release_lease RUNTIME_UNHEALTHY; return 7; }
  run_start_step sing-box-check docker run --rm --network none -v "$INST_ROOT/sing-box/config.json:/etc/sing-box/config.json:ro" "$SING_BOX_IMAGE" check -c /etc/sing-box/config.json || { release_lease RUNTIME_UNHEALTHY; return 7; }
  log "start netns"
  run_start_step netns-up docker compose -f "$COMPOSE" up -d netns || { release_lease RUNTIME_UNHEALTHY; return 7; }
  apply_netns_firewall || { release_lease RUNTIME_UNHEALTHY; return 7; }
  log "start sing-box"
  run_start_step sing-box-up docker compose -f "$COMPOSE" up -d sing-box || { release_lease RUNTIME_UNHEALTHY; return 7; }
  wait_healthy || { release_lease RUNTIME_UNHEALTHY; return 7; }
  log "probe and ack"
  # ponytail: network/runtime failure is not provider IP_USED; add provider-block reason only after app log proves it.
  wait_network_ready || { capture_network_failure; release_lease RUNTIME_UNHEALTHY; stop_existing; return 3; }
  if [ "$MACOS_START_STAGGER_SECONDS" -gt 0 ]; then
    # ponytail: fixed stagger plus three slots caps launch pressure; tune slots above 20 macOS VMs.
    local stagger_delay=$(((10#$suffix - 1) * MACOS_START_STAGGER_SECONDS))
    if [ "$stagger_delay" -gt 0 ]; then
      log "stagger macos start ${stagger_delay}s"
      sleep "$stagger_delay"
    fi
  fi
  acquire_macos_start_slot
  log "start macos"
  if ! run_start_step macos-up docker compose -f "$COMPOSE" up -d macos; then
    release_macos_start_slot
    release_lease RUNTIME_UNHEALTHY
    return 7
  fi
  if [ "$EARNAPP_AUTOINSTALL" = true ]; then
    if ! guest_ip_value=$(wait_guest_ssh); then
      release_macos_start_slot
      release_lease RUNTIME_UNHEALTHY
      stop_existing
      remove_instance_root
      return 6
    fi
    specialize_guest "$guest_ip_value"
    if ! install_earnapp_macos "$guest_ip_value"; then
      local install_reason=RUNTIME_UNHEALTHY
      if jq -e '.status == "rate_limited"' "$STATE/earnapp-link-result.json" >/dev/null 2>&1; then
        install_reason=RATE_LIMITED
      elif jq -e '.status == "device_not_found"' "$STATE/earnapp-link-result.json" >/dev/null 2>&1; then
        install_reason=EARNAPP_DEVICE_NOT_FOUND
      fi
      release_macos_start_slot
      release_lease "$install_reason"
      stop_existing
      [ "$install_reason" = RATE_LIMITED ] && return 8
      [ "$install_reason" = EARNAPP_DEVICE_NOT_FOUND ] && return 10
      return 4
    fi
    heartbeat_earnapp_cookie linked || true
    if [ "$EARNAPP_FAST_LINK" = true ]; then
      close_earnapp_browsers "$guest_ip_value" || true
      return 0
    fi
    if ! wait_earnapp_dashboard_green "$guest_ip_value"; then
      release_macos_start_slot
      release_lease RUNTIME_UNHEALTHY
      return 4
    fi
  fi
  release_macos_start_slot
  return 0
}

start() {
  mkdir -p "$STATE"
  if [ "${CASHPILOT_STANDALONE:-false}" = "true" ]; then
    [ -n "$MANUAL_PROXY" ] || { echo "missing MANUAL_PROXY" >&2; return 9; }
    [ -s "$EARNAPP_AUTH_STATE_FILE" ] || { echo "missing EARNAPP_AUTH_STATE_FILE" >&2; return 2; }
  else
    register_client
    request_earnapp_cookie
  fi
  local attempts="$MAX_ATTEMPTS" start_once_rc
  [ -z "$TARGET_EGRESS_IP" ] || attempts=1
  for attempt in $(seq 1 "$attempts"); do
    if start_once; then
      jq . "$REPORT"
      return 0
    else
      start_once_rc=$?
    fi
    stop_existing
    remove_instance_root
    log "start attempt failed, rotating attempt=$attempt"
    [ "$start_once_rc" -eq 8 ] && return 8
    [ "$start_once_rc" -eq 10 ] && return 10
    sleep 2
  done
  heartbeat_earnapp_cookie STOPPED || true
  jq . "$REPORT" >&2 || true
  return 1
}

status() {
  docker ps --format '{{.Names}} {{.Status}} {{.Ports}}' | grep -E "macos-$INSTANCE($|-egress|-netns)" || true
  [ -f "$REPORT" ] && jq . "$REPORT" || true
}

install_only() {
  local ip
  ip=$(wait_guest_ssh)
  specialize_guest "$ip"
  install_earnapp_macos "$ip"
}

cleanup() {
  pkill -f "proxy-manager-macos-earnapp-smoke.sh heartbeat-loop $GROUP_ID $PROVIDER_ID $INSTANCE" >/dev/null 2>&1 || true
  heartbeat_earnapp_cookie STOPPED || true
  release_lease "${RELEASE_REASON:-INSTANCE_DESTROYED}"
  stop_existing
  remove_instance_root
}

case "$ACTION" in
  start) start ;;
  install) install_only ;;
  status) status ;;
  cleanup|release) cleanup ;;
  *) echo "usage: $0 {start|install|status|cleanup}" >&2; exit 2 ;;
esac
