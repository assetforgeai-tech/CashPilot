#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run the NKN ChainDB publisher installer as root." >&2
  exit 1
fi

BUNDLE_DIR="${1:-}"
if [ -z "${BUNDLE_DIR}" ] || [ ! -d "${BUNDLE_DIR}" ]; then
  echo "Usage: install-nkn-chaindb-publisher.sh <bundle-directory>" >&2
  exit 1
fi
BUNDLE_DIR="$(cd -- "${BUNDLE_DIR}" && pwd)"

required=(
  publisher.json
  wallet.json
  wallet.pswd
  config.json
  nkn_chaindb.py
  nkn_chaindb_publisher.py
  cashpilot-nkn-chaindb-publisher.service
  cashpilot-nkn-chaindb-publisher-failure.service
  cashpilot-nkn-chaindb-publisher.timer
)
for name in "${required[@]}"; do
  test -s "${BUNDLE_DIR}/${name}" || { echo "Missing bundle file: ${name}" >&2; exit 1; }
done

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y docker.io zstd awscli python3 ca-certificates curl tar util-linux ufw
systemctl enable --now docker

# Keep the publisher's network contract identical to the tested official NKN
# setup. UFW rules are idempotent and are applied before the node starts.
SSH_PORT="$(python3 - "${BUNDLE_DIR}/publisher.json" <<'PY'
import json
import sys

value = int(json.load(open(sys.argv[1], encoding="utf-8")).get("ssh_port") or 0)
if not 1 <= value <= 65535:
    raise SystemExit("publisher ssh_port is invalid")
print(value)
PY
)"
ufw allow "${SSH_PORT}/tcp"
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 30088/tcp
ufw allow 30000:30005/tcp
ufw allow 30000:30005/udp
ufw allow 32768:65535/tcp
ufw allow 32768:65535/udp
ufw --force enable
ufw reload

install -d -m 0755 /etc/systemd/system/docker.service.d
cat >/etc/systemd/system/docker.service.d/cashpilot-nofile.conf <<'EOF'
[Service]
LimitNOFILE=1048576
EOF

install -d -m 0700 /etc/cashpilot /opt/nkn /var/lib/cashpilot/nkn-chaindb
install -d -m 0755 /usr/local/lib/cashpilot

# A redeploy may refresh scripts/config, but it must never replace a live NKN
# wallet. Compare before copying so an accidental lease change fails closed.
for name in wallet.json wallet.pswd; do
  if [ -s "/opt/nkn/${name}" ] && ! cmp -s "/opt/nkn/${name}" "${BUNDLE_DIR}/${name}"; then
    case "${name}" in
      wallet.json) echo "Existing wallet.json differs; refusing to replace NKN identity." >&2 ;;
      wallet.pswd) echo "Existing wallet.pswd differs; refusing to replace NKN identity." >&2 ;;
    esac
    exit 1
  fi
done
if [ -s /opt/nkn/config.json ] && ! cmp -s /opt/nkn/config.json "${BUNDLE_DIR}/config.json"; then
  echo "Existing config.json differs; refusing an implicit runtime change." >&2
  exit 1
fi

install -m 0600 "${BUNDLE_DIR}/wallet.json" /opt/nkn/wallet.json
install -m 0600 "${BUNDLE_DIR}/wallet.pswd" /opt/nkn/wallet.pswd
install -m 0644 "${BUNDLE_DIR}/config.json" /opt/nkn/config.json
install -m 0600 "${BUNDLE_DIR}/publisher.json" /etc/cashpilot/nkn-chaindb-publisher.json
chmod 0600 /etc/cashpilot/nkn-chaindb-publisher.json /opt/nkn/wallet.json /opt/nkn/wallet.pswd
install -m 0644 "${BUNDLE_DIR}/nkn_chaindb.py" /usr/local/lib/cashpilot/nkn_chaindb.py
install -m 0755 "${BUNDLE_DIR}/nkn_chaindb_publisher.py" /usr/local/lib/cashpilot/nkn_chaindb_publisher.py
install -m 0644 "${BUNDLE_DIR}/cashpilot-nkn-chaindb-publisher.service" /etc/systemd/system/cashpilot-nkn-chaindb-publisher.service
install -m 0644 "${BUNDLE_DIR}/cashpilot-nkn-chaindb-publisher-failure.service" /etc/systemd/system/cashpilot-nkn-chaindb-publisher-failure.service
install -m 0644 "${BUNDLE_DIR}/cashpilot-nkn-chaindb-publisher.timer" /etc/systemd/system/cashpilot-nkn-chaindb-publisher.timer

docker pull nknorg/nkn:latest
if docker inspect cashpilot-nkn >/dev/null 2>&1; then
  image="$(docker inspect cashpilot-nkn --format '{{.Config.Image}}')"
  network="$(docker inspect cashpilot-nkn --format '{{.HostConfig.NetworkMode}}')"
  mount="$(docker inspect cashpilot-nkn --format '{{range .Mounts}}{{if eq .Destination "/nkn/data"}}{{.Source}}{{end}}{{end}}')"
  if [ "${image}" != "nknorg/nkn:latest" ] || [ "${network}" != "host" ] || [ "${mount}" != "/opt/nkn" ]; then
    echo "Existing cashpilot-nkn container does not match the protected publisher contract." >&2
    exit 1
  fi
  docker update --restart always cashpilot-nkn >/dev/null
else
  docker run -d \
    --name cashpilot-nkn \
    --restart always \
    --network host \
    -v /opt/nkn:/nkn/data \
    nknorg/nkn:latest >/dev/null
fi

systemctl daemon-reload
systemctl restart docker
systemctl enable --now cashpilot-nkn-chaindb-publisher.timer
echo '{"status":"deployed","publisher":"cashpilot-nkn-chaindb"}'
