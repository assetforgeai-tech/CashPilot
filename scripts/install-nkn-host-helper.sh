#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run the NKN host-helper installer as root." >&2
  exit 1
fi

REPO_ROOT="${1:-}"
if [ -z "${REPO_ROOT}" ] || [ ! -d "${REPO_ROOT}" ]; then
  echo "Usage: install-nkn-host-helper.sh <CashPilot source root>" >&2
  exit 2
fi

INSTALL_ROOT="${CASHPILOT_NKN_INSTALL_ROOT:-/usr/local/lib/cashpilot}"
CACHE_ROOT="${CASHPILOT_NKN_CACHE_ROOT:-/var/lib/cashpilot/nkn-chaindb-cache}"
SERVICE_SOURCE="${REPO_ROOT}/scripts/cashpilot-nkn-agent.service"

for source in \
  "${REPO_ROOT}/scripts/cashpilot-nkn-agent.py" \
  "${REPO_ROOT}/app/nkn_chaindb.py" \
  "${REPO_ROOT}/scripts/nkn_chaindb_restore.py" \
  "${REPO_ROOT}/scripts/nkn_chaindb_cache.py" \
  "${SERVICE_SOURCE}"; do
  test -f "${source}"
done

install -d -o root -g root -m 0755 "${INSTALL_ROOT}" "${CACHE_ROOT}" /etc/systemd/system
install -o root -g root -m 0755 "${REPO_ROOT}/scripts/cashpilot-nkn-agent.py" \
  "${INSTALL_ROOT}/cashpilot-nkn-agent.py"
install -o root -g root -m 0644 "${REPO_ROOT}/app/nkn_chaindb.py" \
  "${INSTALL_ROOT}/nkn_chaindb.py"
install -o root -g root -m 0755 "${REPO_ROOT}/scripts/nkn_chaindb_restore.py" \
  "${INSTALL_ROOT}/nkn_chaindb_restore.py"
install -o root -g root -m 0644 "${REPO_ROOT}/scripts/nkn_chaindb_cache.py" \
  "${INSTALL_ROOT}/nkn_chaindb_cache.py"
install -o root -g root -m 0644 "${SERVICE_SOURCE}" \
  /etc/systemd/system/cashpilot-nkn-agent.service

# Keep archives readable by LXD while keeping cache mutation root-only.
chmod 0755 "${CACHE_ROOT}"
chown root:root "${CACHE_ROOT}"
find "${CACHE_ROOT}" -maxdepth 1 -type f -name '*.tar.zst' \
  -exec chown root:root {} + -exec chmod 0644 {} +

systemctl daemon-reload
systemctl enable cashpilot-nkn-agent.service >/dev/null
if systemctl is-active --quiet cashpilot-nkn-agent.service; then
  systemctl restart cashpilot-nkn-agent.service
else
  systemctl start cashpilot-nkn-agent.service
fi
