#!/usr/bin/env bash
set -euo pipefail

slots_file=/etc/cashpilot/public-ip-slots.json

printf 'network_service=%s\n' "$(systemctl is-active cashpilot-network-slots.service)"
printf 'network_service_enabled=%s\n' "$(systemctl is-enabled cashpilot-network-slots.service)"
printf 'worker_status=%s\n' "$(docker ps --filter name=cashpilot-worker --format '{{.Status}}')"
printf 'direct_network_count=%s\n' "$(docker network ls --format '{{.Name}}' | grep -c '^cashpilot-direct-')"

python3 - "$slots_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    slots = json.load(handle)["slots"]

print(f"slot_count={len(slots)}")
print(f"ready_count={sum(bool(slot.get('ready')) for slot in slots)}")
print(f"unique_public_ipv4={len({slot['public_ip'] for slot in slots})}")
PY

printf 'policy_rule_count=%s\n' "$(ip rule show | grep -c '10.42.1.' || true)"
printf 'heartbeat_http_200_count=%s\n' "$(docker logs --since 10m cashpilot-worker 2>&1 | grep -c 'HTTP 200' || true)"
