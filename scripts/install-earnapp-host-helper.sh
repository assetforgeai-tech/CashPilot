#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run the EarnApp host-helper installer as root." >&2
  exit 1
fi

REPO_ROOT="${1:-}"
if [ -z "${REPO_ROOT}" ] || [ ! -d "${REPO_ROOT}" ]; then
  echo "Usage: install-earnapp-host-helper.sh <CashPilot source root>" >&2
  exit 2
fi

INSTALL_ROOT="${CASHPILOT_EARNAPP_INSTALL_ROOT:-/usr/local/lib/cashpilot}"
AGENT_SOURCE="${REPO_ROOT}/scripts/cashpilot-earnapp-agent.py"
SERVICE_SOURCE="${REPO_ROOT}/scripts/cashpilot-earnapp-agent.service"

test -f "${AGENT_SOURCE}"
test -f "${SERVICE_SOURCE}"
install -d -o root -g root -m 0755 "${INSTALL_ROOT}" /etc/systemd/system
install -o root -g root -m 0755 "${AGENT_SOURCE}" "${INSTALL_ROOT}/cashpilot-earnapp-agent.py"
install -o root -g root -m 0644 "${SERVICE_SOURCE}" /etc/systemd/system/cashpilot-earnapp-agent.service

systemctl daemon-reload
systemctl enable cashpilot-earnapp-agent.service >/dev/null
if systemctl is-active --quiet cashpilot-earnapp-agent.service; then
  systemctl restart cashpilot-earnapp-agent.service
else
  systemctl start cashpilot-earnapp-agent.service
fi
