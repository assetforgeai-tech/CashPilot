#!/usr/bin/env bash
set -euo pipefail

SLOTS_FILE="${CASHPILOT_PUBLIC_IP_SLOTS_FILE:-/etc/cashpilot/public-ip-slots.json}"
SLOTS_VOLUME="${CASHPILOT_PUBLIC_IP_SLOTS_VOLUME:-cashpilot_public_ip_slots}"
INSTALLED_SCRIPT="/usr/local/sbin/cashpilot-bootstrap-worker"
INSTALL_ROOT="/usr/local/lib/cashpilot"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
DISCOVERY="${INSTALL_ROOT}/public_ip_slots.py"
NKN_AGENT="${INSTALL_ROOT}/cashpilot-nkn-agent.py"
NKN_CHAINDb_CONTRACT="${INSTALL_ROOT}/nkn_chaindb.py"
NKN_CHAINDb_RESTORE="${INSTALL_ROOT}/nkn_chaindb_restore.py"
NKN_CHAINDb_CACHE="${INSTALL_ROOT}/nkn_chaindb_cache.py"
NKN_HELPER_INSTALLER="${REPO_ROOT}/scripts/install-nkn-host-helper.sh"
NKN_AGENT_SOCKET="/run/cashpilot-nkn-agent/agent.sock"
EARNAPP_HELPER_INSTALLER="${REPO_ROOT}/scripts/install-earnapp-host-helper.sh"

publish_slots_volume() {
  local mountpoint
  docker volume create "${SLOTS_VOLUME}" >/dev/null
  mountpoint="$(docker volume inspect "${SLOTS_VOLUME}" --format '{{.Mountpoint}}')"
  test -n "${mountpoint}"
  install -d -m 0755 "${mountpoint}"
  install -m 0644 "${SLOTS_FILE}" "${mountpoint}/public-ip-slots.json"
}

publish_slots_to_worker_data() {
  local volume mountpoint
  while IFS= read -r volume; do
    [ -n "${volume}" ] || continue
    case "${volume}" in
      *cashpilot_worker_data) ;;
      *) continue ;;
    esac
    mountpoint="$(docker volume inspect "${volume}" --format '{{.Mountpoint}}' 2>/dev/null || true)"
    [ -n "${mountpoint}" ] || continue
    install -d -m 0755 "${mountpoint}"
    install -m 0644 "${SLOTS_FILE}" "${mountpoint}/public-ip-slots.json"
  done < <(docker volume ls --format '{{.Name}}')
}

publish_all_slot_state() {
  publish_slots_volume
  publish_slots_to_worker_data
}

prepare_networks() {
  test -s "${SLOTS_FILE}"
  while IFS=$'\t' read -r slot_id private_ip interface subnet gateway network bridge_subnet bridge_gateway ready; do
    test "${ready}" = "true" || continue
    prefix="${subnet#*/}"
    suffix="${slot_id#ipv4-}"
    table_id="$((20000 + 10#${suffix}))"
    bridge_iface="cp${suffix}"

    if ! ip -4 address show dev "${interface}" | grep -Fq "${private_ip}/${prefix}"; then
      ip address add "${private_ip}/${prefix}" dev "${interface}"
    fi

    if docker network inspect "${network}" >/dev/null 2>&1; then
      actual_subnet="$(docker network inspect "${network}" --format '{{(index .IPAM.Config 0).Subnet}}')"
      actual_masquerade="$(docker network inspect "${network}" --format '{{index .Options "com.docker.network.bridge.enable_ip_masquerade"}}')"
      test "${actual_subnet}" = "${bridge_subnet}"
      test "${actual_masquerade}" = "false"
    else
      docker network create \
        --driver bridge \
        --subnet "${bridge_subnet}" \
        --gateway "${bridge_gateway}" \
        --opt "com.docker.network.bridge.name=${bridge_iface}" \
        --opt "com.docker.network.bridge.enable_ip_masquerade=false" \
        "${network}" >/dev/null
    fi

    ip route replace "${subnet}" dev "${interface}" src "${private_ip}" table "${table_id}"
    ip route replace default via "${gateway}" dev "${interface}" src "${private_ip}" table "${table_id}"
    ip rule show | grep -Fq "from ${bridge_subnet} lookup ${table_id}" || \
      ip rule add from "${bridge_subnet}" lookup "${table_id}" priority "${table_id}"
    iptables -t nat -C POSTROUTING -s "${bridge_subnet}" ! -d "${bridge_subnet}" -j SNAT --to-source "${private_ip}" 2>/dev/null || \
      iptables -t nat -A POSTROUTING -s "${bridge_subnet}" ! -d "${bridge_subnet}" -j SNAT --to-source "${private_ip}"
  done < <(
    jq -r '.slots[] | [.slot_id,.private_ip,.interface,.subnet,.gateway,.docker_network,.bridge_subnet,.bridge_gateway,(.route_ready|tostring)] | @tsv' "${SLOTS_FILE}"
  )
}

if test "${1:-}" = "--prepare-network-only"; then
  publish_all_slot_state
  prepare_networks
  exit 0
fi

if test "${1:-}" = "--sync-state-only"; then
  publish_all_slot_state
  exit 0
fi

if test "$(id -u)" -ne 0; then
  echo "Run this bootstrap as root." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
packages=(ufw curl jq iproute2 iptables python3 ca-certificates)
if ! command -v docker >/dev/null 2>&1; then
  packages=(docker.io "${packages[@]}")
fi
apt-get install -y "${packages[@]}"
systemctl enable --now docker

if ! command -v lxc >/dev/null 2>&1; then
  if command -v snap >/dev/null 2>&1; then
    snap install lxd
  else
    apt-get install -y lxd
  fi
fi
lxd waitready
if [ -z "$(lxc storage list --format csv 2>/dev/null)" ]; then
  lxd init --auto
fi

ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 30088/tcp
ufw allow 30000:30005/tcp
ufw allow 30000:30005/udp
ufw allow 32768:65535/tcp
ufw allow 32768:65535/udp
ufw --force enable

install -d -m 0755 /etc/cashpilot /etc/systemd/system/docker.service.d "${INSTALL_ROOT}"
install -d -m 0755 /var/lib/cashpilot/nkn-chaindb-cache
install -m 0755 "${BASH_SOURCE[0]}" "${INSTALLED_SCRIPT}"
# The installed bootstrap must remain self-contained; the source checkout is
# not present on a freshly provisioned VPS.
install -m 0644 "${REPO_ROOT}/app/public_ip_slots.py" "${DISCOVERY}"
install -m 0755 "${NKN_HELPER_INSTALLER}" "${INSTALL_ROOT}/install-nkn-host-helper.sh"
"${NKN_HELPER_INSTALLER}" "${REPO_ROOT}"
install -m 0755 "${EARNAPP_HELPER_INSTALLER}" "${INSTALL_ROOT}/install-earnapp-host-helper.sh"
"${EARNAPP_HELPER_INSTALLER}" "${REPO_ROOT}"

task_tmp="$(mktemp -d)"
trap 'rm -rf -- "${task_tmp}"' EXIT
printf '{"interface":[]}\n' >"${task_tmp}/imds.json"
curl --noproxy '*' --fail --silent --show-error \
  -H 'Metadata:true' \
  'http://169.254.169.254/metadata/instance/network/interface?api-version=2021-02-01' \
  -o "${task_tmp}/imds.json" || true
ip -j -4 address show >"${task_tmp}/addresses.json"
ip -j -4 route show table all >"${task_tmp}/routes.json"
fallback_public_ip="$(curl --fail --silent --show-error --max-time 10 https://api.ipify.org || true)"

python3 "${DISCOVERY}" discover \
  --imds-file "${task_tmp}/imds.json" \
  --addresses-file "${task_tmp}/addresses.json" \
  --routes-file "${task_tmp}/routes.json" \
  --fallback-public-ip "${fallback_public_ip}" \
  --output "${SLOTS_FILE}"

publish_all_slot_state

cat >/etc/systemd/system/docker.service.d/cashpilot-nofile.conf <<'EOF'
[Service]
LimitNOFILE=1048576
EOF

cat >/etc/systemd/system/cashpilot-network-slots.service <<EOF
[Unit]
Description=Prepare CashPilot public IPv4 slot routing
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
ExecStart=${INSTALLED_SCRIPT} --prepare-network-only
RemainAfterExit=yes
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/systemd/system/cashpilot-slots-sync.service <<EOF
[Unit]
Description=Sync CashPilot public IPv4 slots into worker data volumes
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=${INSTALLED_SCRIPT} --sync-state-only
EOF

cat >/etc/systemd/system/cashpilot-slots-sync.timer <<'EOF'
[Unit]
Description=Keep CashPilot worker slot state current

[Timer]
OnBootSec=30s
OnUnitActiveSec=30s
Unit=cashpilot-slots-sync.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
if [ -z "$(docker ps -q)" ]; then
  systemctl restart docker
else
  echo "Docker is already running CashPilot workloads; the new nofile limit will apply on the next planned daemon restart." >&2
fi
systemctl enable cashpilot-network-slots.service
systemctl enable --now cashpilot-slots-sync.timer
systemctl enable --now cashpilot-nkn-agent.service
systemctl enable --now cashpilot-earnapp-agent.service
prepare_networks
systemctl restart cashpilot-network-slots.service

echo "CashPilot host prerequisites, public IPv4 slots, and restricted LXD helpers are ready."
