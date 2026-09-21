#!/usr/bin/env bash
set -euo pipefail

: "${CASHPILOT_RELEASE:?set CASHPILOT_RELEASE, e.g. 1.53.17}"
: "${CASHPILOT_API_KEY:?set CASHPILOT_API_KEY in the process environment}"
: "${CASHPILOT_UI_URL:?set CASHPILOT_UI_URL in the process environment}"

REPO_ROOT="${CASHPILOT_REPO_ROOT:-$HOME/CashPilot}"
WORKER_IMAGE="${CASHPILOT_WORKER_IMAGE:-ghcr.io/assetforgeai-tech/cashpilot-worker:${CASHPILOT_RELEASE}}"
WORKER_NAME="${CASHPILOT_WORKER_NAME:-$(hostname)}"
WORKER_URL="${CASHPILOT_WORKER_URL:?set CASHPILOT_WORKER_URL in the process environment}"
WORKER_BIND_ADDR="${CASHPILOT_WORKER_BIND_ADDR:?set CASHPILOT_WORKER_BIND_ADDR to the private/UI-reachable interface}"

# Keep the generated env file one-record-per-line; never interpret secret text
# as shell syntax while persisting it.
case "$CASHPILOT_API_KEY$CASHPILOT_UI_URL$WORKER_URL$WORKER_BIND_ADDR" in
  *$'\n'*|*$'\r'*) echo "CashPilot startup values must not contain newlines" >&2; exit 1 ;;
esac
case "$CASHPILOT_RELEASE$WORKER_NAME" in
  *$'\n'*|*$'\r'*) echo "CashPilot release/worker name must not contain newlines" >&2; exit 1 ;;
esac
case "$CASHPILOT_RELEASE" in
  *[!A-Za-z0-9._-]*) echo "CashPilot release contains unsupported characters" >&2; exit 1 ;;
esac

test -d "$REPO_ROOT/.git" || { echo "CashPilot checkout missing: $REPO_ROOT" >&2; exit 1; }
cd "$REPO_ROOT"
bash scripts/bootstrap-worker.sh

install -d -m 0755 /etc/cashpilot
umask 077
printf '%s\n' \
  "CASHPILOT_API_KEY=$CASHPILOT_API_KEY" \
  "CASHPILOT_UI_URL=$CASHPILOT_UI_URL" \
  "CASHPILOT_WORKER_NAME=$WORKER_NAME" \
  "CASHPILOT_WORKER_URL=$WORKER_URL" \
  "CASHPILOT_VERSION=$CASHPILOT_RELEASE" \
  "CASHPILOT_WORKER_BIND_ADDR=$WORKER_BIND_ADDR" \
  > /etc/cashpilot/worker.env
chmod 0600 /etc/cashpilot/worker.env

cat > docker-compose.worker-${CASHPILOT_RELEASE}.override.yml <<YAML
services:
  cashpilot-worker:
    image: ${WORKER_IMAGE}
    environment:
      CASHPILOT_API_KEY: \${CASHPILOT_API_KEY}
      CASHPILOT_UI_URL: \${CASHPILOT_UI_URL}
      CASHPILOT_WORKER_NAME: \${CASHPILOT_WORKER_NAME}
      CASHPILOT_WORKER_URL: \${CASHPILOT_WORKER_URL}
      CASHPILOT_VERSION: \${CASHPILOT_VERSION}
YAML

cat > /etc/systemd/system/cashpilot-worker.service <<UNIT
[Unit]
Description=CashPilot Worker
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target
[Service]
Type=oneshot
RemainAfterExit=yes
EnvironmentFile=/etc/cashpilot/worker.env
WorkingDirectory=$REPO_ROOT
ExecStart=/usr/bin/docker compose -f docker-compose.fleet.yml -f docker-compose.worker-${CASHPILOT_RELEASE}.override.yml -p cashpilot up -d --no-deps cashpilot-worker
ExecStop=/usr/bin/docker compose -f docker-compose.fleet.yml -f docker-compose.worker-${CASHPILOT_RELEASE}.override.yml -p cashpilot stop cashpilot-worker
TimeoutStartSec=0
[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now cashpilot-worker
