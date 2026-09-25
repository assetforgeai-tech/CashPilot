"""Shared fail-closed proxy route primitives.

Provider identity, account, token, and allocation policy deliberately stay
outside this module.  This module only renders the in-container route shell.
"""

from __future__ import annotations

import shlex

ROUTE_READY_MARKER = "/run/cashpilot/route-ready"
ROUTE_BLOCKED_MARKER = "/run/cashpilot/route-blocked"
RESTART_EVIDENCE_FILE = "/run/cashpilot/restart-evidence.log"


def _watchdog_shell_contract(*, initialize: bool = True) -> str:
    """Return local fail-closed watchdog helpers shared by proxy wrappers."""
    initialize_lines = (
        'mkdir -p "$(dirname "$ROUTE_READY_MARKER")" "$(dirname "$RESTART_EVIDENCE_FILE")"\n'
        'rm -f "$ROUTE_READY_MARKER" "$ROUTE_BLOCKED_MARKER"\n'
        if initialize
        else 'mkdir -p "$(dirname "$RESTART_EVIDENCE_FILE")"\n'
    )
    return rf"""ROUTE_READY_MARKER="${{ROUTE_READY_MARKER:-{ROUTE_READY_MARKER}}}"
ROUTE_BLOCKED_MARKER="${{ROUTE_BLOCKED_MARKER:-{ROUTE_BLOCKED_MARKER}}}"
RESTART_EVIDENCE_FILE="${{RESTART_EVIDENCE_FILE:-{RESTART_EVIDENCE_FILE}}}"
RESTART_STATE_FILE="${{RESTART_STATE_FILE:-/run/cashpilot/restart-count}}"
STARTUP_GRACE_SECONDS="${{STARTUP_GRACE_SECONDS:-30}}"
RESTART_BUDGET="${{RESTART_BUDGET:-3}}"
ROUTE_TTL_SECONDS="${{ROUTE_TTL_SECONDS:-15}}"
{initialize_lines}

record_restart_evidence() {{
  local reason="${{1:-startup}}" count=0
  if [[ -s "$RESTART_STATE_FILE" ]]; then read -r count <"$RESTART_STATE_FILE" || count=0; fi
  count=$((count + 1))
  printf '%s\n' "$count" >"$RESTART_STATE_FILE"
  printf '%s reason=%s count=%s budget=%s\n' "$(date -u +%FT%TZ)" "$reason" "$count" "$RESTART_BUDGET" >>"$RESTART_EVIDENCE_FILE"
  (( count <= RESTART_BUDGET ))
}}

route_blocked() {{
  local reason="${{1:-untrusted-route}}"
  if [[ "${{ROUTE_MARKER_OWNER:-true}}" == true ]]; then
    rm -f "$ROUTE_READY_MARKER"
    printf '%s reason=%s\n' "$(date -u +%FT%TZ)" "$reason" >"$ROUTE_BLOCKED_MARKER"
  fi
  record_restart_evidence "$reason" || true
}}

route_is_ready() {{
  [[ -e "$ROUTE_READY_MARKER" && ! -e "$ROUTE_BLOCKED_MARKER" ]] || return 1
  local modified now
  modified=$(stat -c %Y "$ROUTE_READY_MARKER") || return 1
  now=$(date +%s)
  (( now - modified <= ROUTE_TTL_SECONDS ))
}}

route_ready() {{
  rm -f "$ROUTE_BLOCKED_MARKER"
  touch "$ROUTE_READY_MARKER"
}}
"""


def render_sidecar_guard_entrypoint(command: list[str]) -> bytes:
    """Render a provider guard for a separately managed route sidecar."""
    if not command:
        raise ValueError("provider command")
    provider_command = shlex.join(command)
    return rf"""#!/usr/bin/env bash
set -euo pipefail
umask 077
{_watchdog_shell_contract(initialize=False)}
ROUTE_MARKER_OWNER=false
PROVIDER_PID=""
for _ in $(seq 1 "$STARTUP_GRACE_SECONDS"); do
  route_is_ready && break
  sleep 1
done
route_is_ready || {{ route_blocked startup-grace-expired; exit 70; }}
record_restart_evidence provider-start || {{ route_blocked restart-budget-exhausted; exit 75; }}
{provider_command} &
PROVIDER_PID=$!
while kill -0 "$PROVIDER_PID" 2>/dev/null; do
  if ! route_is_ready; then
    route_blocked route-untrusted
    kill -TERM "$PROVIDER_PID" 2>/dev/null || true
    wait "$PROVIDER_PID" || true
    exit 75
  fi
  sleep 5
done
wait "$PROVIDER_PID"
""".encode()


def rotation_steps() -> tuple[str, ...]:
    """Return the ordered route rebuild contract used by provider adapters."""
    return (
        "stop_provider",
        "remove_route",
        "lease_provider_proxy",
        "install_route",
        "verify_route",
        "start_provider",
        "record_evidence",
    )


def render_route_teardown() -> bytes:
    """Render idempotent cleanup for a route before provider-specific rotation."""
    return b"""#!/usr/bin/env bash
set -euo pipefail
for pid in "${PROVIDER_PID:-}" "${REDSOCKS_PID:-}" "${DNS_PID:-}"; do
  [[ -n "$pid" ]] && kill -TERM "$pid" 2>/dev/null || true
done
iptables -t nat -D OUTPUT -p tcp -j CP_PROXY_REDSOCKS 2>/dev/null || true
iptables -t nat -D OUTPUT -p udp --dport 53 -j CP_PROXY_DNS 2>/dev/null || true
iptables -t nat -D OUTPUT -p tcp --dport 53 -j CP_PROXY_DNS 2>/dev/null || true
iptables -t nat -F CP_PROXY_REDSOCKS 2>/dev/null || true
iptables -t nat -X CP_PROXY_REDSOCKS 2>/dev/null || true
iptables -t nat -F CP_PROXY_DNS 2>/dev/null || true
iptables -t nat -X CP_PROXY_DNS 2>/dev/null || true
iptables -D OUTPUT -j CP_PROXY_OUT 2>/dev/null || true
iptables -F CP_PROXY_OUT 2>/dev/null || true
iptables -X CP_PROXY_OUT 2>/dev/null || true
ip6tables -D OUTPUT -j CP_PROXY6_OUT 2>/dev/null || true
ip6tables -F CP_PROXY6_OUT 2>/dev/null || true
ip6tables -X CP_PROXY6_OUT 2>/dev/null || true
rm -f "${ROUTE_READY_MARKER:-/run/cashpilot/route-ready}" "${ROUTE_BLOCKED_MARKER:-/run/cashpilot/route-blocked}"
"""


def render_entrypoint(command: list[str]) -> bytes:
    """Render a provider wrapper that starts the route before the provider."""
    if not command:
        raise ValueError("provider command")
    provider_command = shlex.join(command)
    script = rf"""#!/usr/bin/env bash
set -euo pipefail
umask 077

{_watchdog_shell_contract()}

REDSOCKS_PORT="${{REDSOCKS_PORT:-12345}}"
DNS_PORT="${{DNS_PORT:-1053}}"
EXPECTED_EGRESS_IP="${{EXPECTED_EGRESS_IP:?}}"
PROXY_HOST="${{PROXY_HOST:?}}"
PROXY_PORT="${{PROXY_PORT:?}}"
PROXY_TYPE=$(printf '%s' "${{PROXY_TYPE:-SOCKS5}}" | tr '[:lower:]' '[:upper:]')
case "$PROXY_TYPE" in
  SOCKS5) REDSOCKS_TYPE=socks5 ;;
  HTTP) REDSOCKS_TYPE=http-connect ;;
  *) echo "unsupported proxy type" >&2; exit 64 ;;
esac
PROXY_USER="${{PROXY_USER:-}}"
PROXY_PASS="${{PROXY_PASS:-}}"
REDSOCKS_CONF="${{REDSOCKS_CONF:-/tmp/cashpilot-redsocks.conf}}"
PROVIDER_PID=""
REDSOCKS_PID=""
DNS_PID=""

# Bootstrap resolution happens before the fail-closed firewall is installed;
# every later rule and connection uses the pinned IPv4 only.
PROXY_IP="${{PROXY_IP:-}}"
if [[ -z "$PROXY_IP" ]]; then
  PROXY_IP=$(getent ahostsv4 "$PROXY_HOST" | awk 'NR==1 {{print $1}}')
fi
[[ "$PROXY_IP" =~ ^([0-9]{{1,3}}\.){{3}}[0-9]{{1,3}}$ ]]

start_process() {{
  case "$1" in
    redsocks)
      escape_config_value() {{
        local value="$1"
        value=${{value//\\/\\\\}}
        value=${{value//\"/\\\"}}
        value=${{value//$'\\n'/}}
        printf '%s' "$value"
      }}
      cat >"${{REDSOCKS_CONF:?}}" <<EOF
base {{
    log_debug = off;
    log_info = off;
    log = "file:/tmp/redsocks.log";
    daemon = off;
    redirector = iptables;
}}
redsocks {{
    local_ip = 127.0.0.1;
    local_port = $REDSOCKS_PORT;
    ip = $PROXY_IP;
    port = $PROXY_PORT;
    type = ${{REDSOCKS_TYPE:-socks5}};
EOF
      if [[ -n "$PROXY_USER" || -n "$PROXY_PASS" ]]; then
        printf '    login = "%s";\n    password = "%s";\n' "$(escape_config_value "$PROXY_USER")" "$(escape_config_value "$PROXY_PASS")" >>"$REDSOCKS_CONF"
      fi
      printf '}}\n' >>"$REDSOCKS_CONF"
      chmod 0600 "$REDSOCKS_CONF"
      /usr/sbin/redsocks -c "$REDSOCKS_CONF" & REDSOCKS_PID=$!
      ;;
    dns) node /usr/local/lib/cashpilot-doh.js & DNS_PID=$! ;;
    *) echo "unknown route process: $1" >&2; return 64 ;;
  esac
}}

wait_tcp() {{
  local host="$1" port="$2" i
  for i in $(seq 1 30); do
    (exec 3<>"/dev/tcp/$host/$port") 2>/dev/null && return 0
    sleep 1
  done
  return 1
}}

wait_udp_dns() {{
  local host="$1" port="$2"
  if command -v dig >/dev/null 2>&1; then
    for _ in $(seq 1 30); do
      dig +time=1 +tries=1 @"$host" -p "$port" example.com A >/dev/null 2>&1 && return 0
      sleep 1
    done
  elif command -v getent >/dev/null 2>&1; then
    for _ in $(seq 1 30); do
      getent hosts example.com >/dev/null 2>&1 && return 0
      sleep 1
    done
  fi
  return 1
}}

verify_egress() {{
  local expected="$1" observed
  observed=$(curl -4fsS --max-time 15 https://api.ipify.org)
  [[ "$observed" == "$expected" ]]
}}

install_firewall() {{
  iptables -N CP_PROXY_OUT 2>/dev/null || iptables -F CP_PROXY_OUT
  iptables -A CP_PROXY_OUT -o lo -j ACCEPT
  iptables -A CP_PROXY_OUT -d 127.0.0.0/8 -j ACCEPT
  iptables -A CP_PROXY_OUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  iptables -A CP_PROXY_OUT -d "$PROXY_IP"/32 -p tcp --dport "$PROXY_PORT" -j ACCEPT
  iptables -A CP_PROXY_OUT -p udp -j DROP
  iptables -A CP_PROXY_OUT -j DROP
  iptables -C OUTPUT -j CP_PROXY_OUT 2>/dev/null || iptables -I OUTPUT 1 -j CP_PROXY_OUT
  iptables -t nat -N CP_PROXY_REDSOCKS 2>/dev/null || iptables -t nat -F CP_PROXY_REDSOCKS
  for cidr in 0.0.0.0/8 10.0.0.0/8 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/4 "$PROXY_IP/32"; do
    iptables -t nat -A CP_PROXY_REDSOCKS -d "$cidr" -j RETURN
  done
  iptables -t nat -A CP_PROXY_REDSOCKS -p tcp -j REDIRECT --to-ports "$REDSOCKS_PORT"
  iptables -t nat -C OUTPUT -p tcp -j CP_PROXY_REDSOCKS 2>/dev/null || iptables -t nat -I OUTPUT 1 -j CP_PROXY_REDSOCKS
  iptables -t nat -N CP_PROXY_DNS 2>/dev/null || iptables -t nat -F CP_PROXY_DNS
  iptables -t nat -A CP_PROXY_DNS -p udp --dport 53 -j REDIRECT --to-ports "$DNS_PORT"
  iptables -t nat -A CP_PROXY_DNS -p tcp --dport 53 -j REDIRECT --to-ports "$DNS_PORT"
  iptables -t nat -C OUTPUT -p udp --dport 53 -j CP_PROXY_DNS 2>/dev/null || iptables -t nat -I OUTPUT 1 -p udp --dport 53 -j CP_PROXY_DNS
  iptables -t nat -C OUTPUT -p tcp --dport 53 -j CP_PROXY_DNS 2>/dev/null || iptables -t nat -I OUTPUT 1 -p tcp --dport 53 -j CP_PROXY_DNS
  ip6tables -N CP_PROXY6_OUT 2>/dev/null || ip6tables -F CP_PROXY6_OUT
  ip6tables -A CP_PROXY6_OUT -o lo -j ACCEPT
  ip6tables -A CP_PROXY6_OUT -j DROP
  ip6tables -C OUTPUT -j CP_PROXY6_OUT 2>/dev/null || ip6tables -I OUTPUT 1 -j CP_PROXY6_OUT
}}

watchdog() {{
  local provider_pid="$1" redsocks_pid="$2" dns_pid="$3"
  local grace=0
  while kill -0 "$provider_pid" 2>/dev/null; do
    if (( grace < STARTUP_GRACE_SECONDS )); then
      grace=$((grace + 1))
      sleep 1
      continue
    fi
    [[ -e "$ROUTE_READY_MARKER" ]] || {{ route_blocked route-marker-missing; kill -TERM "$provider_pid"; return 1; }}
    kill -0 "$redsocks_pid" 2>/dev/null || {{ route_blocked redsocks-dead; kill -TERM "$provider_pid"; return 1; }}
    kill -0 "$dns_pid" 2>/dev/null || {{ route_blocked dns-dead; kill -TERM "$provider_pid"; return 1; }}
    if ! iptables -C OUTPUT -j CP_PROXY_OUT 2>/dev/null; then
      # install_firewall || route_blocked is intentionally not used here:
      # re-installing a missing chain could briefly permit an untrusted route.
      route_blocked firewall-chain-missing
      kill -TERM "$provider_pid"
      return 1
    fi
    ip6tables -C OUTPUT -j CP_PROXY6_OUT 2>/dev/null || {{ route_blocked ipv6-chain-missing; kill -TERM "$provider_pid"; return 1; }}
    touch "$ROUTE_READY_MARKER"
    sleep 5
  done
}}

command -v iptables >/dev/null 2>&1 || exit 69
command -v ip6tables >/dev/null 2>&1 || exit 69
command -v redsocks >/dev/null 2>&1 || exit 69
command -v node >/dev/null 2>&1 || exit 69
command -v curl >/dev/null 2>&1 || exit 69
command -v getent >/dev/null 2>&1 || exit 69
install_firewall
start_process "redsocks"
wait_tcp "127.0.0.1" "$REDSOCKS_PORT"
start_process "dns"
wait_udp_dns "127.0.0.1" "$DNS_PORT"
verify_egress "$EXPECTED_EGRESS_IP"
route_ready
record_restart_evidence provider-start || {{ route_blocked restart-budget-exhausted; exit 75; }}
{provider_command} &
PROVIDER_PID=$!
watchdog "$PROVIDER_PID" "$REDSOCKS_PID" "$DNS_PID"
wait "$PROVIDER_PID"
"""
    return script.encode("utf-8")
