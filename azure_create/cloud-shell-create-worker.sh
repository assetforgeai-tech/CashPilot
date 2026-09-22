#!/usr/bin/env bash
set -euo pipefail

# Paste this file into Azure Cloud Shell. It intentionally reads no local files.
# Secrets are supplied as shell variables so the operator can rotate them later.

SUBSCRIPTION_ID="${SUBSCRIPTION_ID:-}"
RESOURCE_GROUP="${RESOURCE_GROUP:-cashpilot-live-eastasia}"
VM_NAME="${VM_NAME:-cashpilot-worker-eastasia}"
LOCATION="${LOCATION:-eastasia}"
IPV4_COUNT="${IPV4_COUNT:-20}"
VM_SIZE="${VM_SIZE:-Standard_D8s_v4}"
IMAGE="${IMAGE:-Ubuntu2404}"
OS_DISK_SIZE_GB="${OS_DISK_SIZE_GB:-512}"
ADMIN_USERNAME="${ADMIN_USERNAME:-kalinh}"
CASHPILOT_UI_URL="${CASHPILOT_UI_URL:-}"
CASHPILOT_WORKER_URL="${CASHPILOT_WORKER_URL:-}"
CASHPILOT_API_KEY="${CASHPILOT_API_KEY:-}"
CASHPILOT_RELEASE="${CASHPILOT_RELEASE:-}"
CASHPILOT_WORKER_IMAGE="${CASHPILOT_WORKER_IMAGE:-ghcr.io/assetforgeai-tech/cashpilot-worker}"
CASHPILOT_WORKER_IMAGE_DIGEST="${CASHPILOT_WORKER_IMAGE_DIGEST:-}"
GHCR_TOKEN="${GHCR_TOKEN:-}"
SSH_PUBLIC_KEY="${SSH_PUBLIC_KEY:-}"
DRY_RUN=false
PREINVENTORY=true
IDEMPOTENT=true

die() { printf 'error: %s\n' "$*" >&2; exit 2; }
run() { if "$DRY_RUN"; then printf '+ '; printf '%q ' "$@"; printf '\n'; else "$@"; fi; }
require_value() { [[ -n "${!1:-}" ]] || die "$1 is required"; }
valid_name() { [[ "$1" =~ ^[a-zA-Z0-9._-]+$ ]] || die "invalid Azure name: $1"; }

while (($#)); do
  case "$1" in
    --subscription) SUBSCRIPTION_ID=${2:?missing value}; shift 2 ;;
    --resource-group) RESOURCE_GROUP=${2:?missing value}; shift 2 ;;
    --name) VM_NAME=${2:?missing value}; shift 2 ;;
    --region|--location) LOCATION=${2:?missing value}; shift 2 ;;
    --ipv4-count|--public-ip-count) IPV4_COUNT=${2:?missing value}; shift 2 ;;
    --vm-size) VM_SIZE=${2:?missing value}; shift 2 ;;
    --image) IMAGE=${2:?missing value}; shift 2 ;;
    --os-disk-size-gb) OS_DISK_SIZE_GB=${2:?missing value}; shift 2 ;;
    --admin-username) ADMIN_USERNAME=${2:?missing value}; shift 2 ;;
    --ssh-public-key) SSH_PUBLIC_KEY=${2:?missing value}; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --no-preinventory) PREINVENTORY=false; shift ;;
    --no-idempotency) IDEMPOTENT=false; shift ;;
    *) die "unknown option: $1" ;;
  esac
done

require_value SUBSCRIPTION_ID
require_value CASHPILOT_UI_URL
require_value CASHPILOT_WORKER_URL
require_value CASHPILOT_API_KEY
require_value CASHPILOT_RELEASE
require_value CASHPILOT_WORKER_IMAGE_DIGEST
[[ "$CASHPILOT_WORKER_IMAGE_DIGEST" =~ ^sha256:[0-9a-fA-F]{64}$ ]] || die 'CASHPILOT_WORKER_IMAGE_DIGEST must be sha256:<64 hex chars>'
[[ "$IPV4_COUNT" =~ ^[1-9][0-9]*$ && "$IPV4_COUNT" -le 256 ]] || die 'IPV4_COUNT must be 1..256'
[[ "$OS_DISK_SIZE_GB" =~ ^[0-9]+$ && "$OS_DISK_SIZE_GB" -ge 512 ]] || die 'OS_DISK_SIZE_GB must be >=512'
valid_name "$RESOURCE_GROUP"; valid_name "$VM_NAME"
[[ -n "$SSH_PUBLIC_KEY" ]] || die 'SSH_PUBLIC_KEY is required; password login is not supported'
case "$CASHPILOT_UI_URL$CASHPILOT_WORKER_URL$CASHPILOT_API_KEY$CASHPILOT_RELEASE$GHCR_TOKEN" in
  *$'\n'*|*$'\r'*) die 'startup values must not contain newlines' ;;
esac

if "$PREINVENTORY"; then
  printf '# pre-inventory (read-only)\n'
  run az account set --subscription "$SUBSCRIPTION_ID"
  run az group show --name "$RESOURCE_GROUP" --subscription "$SUBSCRIPTION_ID" --output table
  run az vm show --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --subscription "$SUBSCRIPTION_ID" --output table
  if "$IDEMPOTENT" && ! "$DRY_RUN" && az vm show --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --subscription "$SUBSCRIPTION_ID" --only-show-errors >/dev/null 2>&1; then
    die "VM already exists: $VM_NAME (use --no-idempotency only after reviewing inventory)"
  fi
fi

VNET="${VM_NAME}-vnet"; SUBNET="${VM_NAME}-subnet"; NSG="${VM_NAME}-nsg"; NIC="${VM_NAME}-nic"
encode() { printf '%s' "$1" | base64 -w0; }
UI_B64=$(encode "$CASHPILOT_UI_URL")
WORKER_URL_B64=$(encode "$CASHPILOT_WORKER_URL")
API_KEY_B64=$(encode "$CASHPILOT_API_KEY")
RELEASE_B64=$(encode "$CASHPILOT_RELEASE")
IMAGE_B64=$(encode "$CASHPILOT_WORKER_IMAGE")
DIGEST_B64=$(encode "$CASHPILOT_WORKER_IMAGE_DIGEST")
GHCR_B64=$(encode "$GHCR_TOKEN")
cloud_init=$(cat <<EOF
#cloud-config
package_update: true
packages: [docker.io, git, ca-certificates]
runcmd:
  - usermod -aG docker ${ADMIN_USERNAME}
  - install -d -m 0700 /etc/cashpilot
  - printf '%s' '${UI_B64}' | base64 -d > /etc/cashpilot/ui.url
  - printf '%s' '${WORKER_URL_B64}' | base64 -d > /etc/cashpilot/worker.url
  - printf '%s' '${API_KEY_B64}' | base64 -d > /etc/cashpilot/api.key
  - printf '%s' '${RELEASE_B64}' | base64 -d > /etc/cashpilot/release
  - printf '%s' '${IMAGE_B64}' | base64 -d > /etc/cashpilot/image
  - printf '%s' '${DIGEST_B64}' | base64 -d > /etc/cashpilot/digest
  - printf '%s' '${GHCR_B64}' | base64 -d > /etc/cashpilot/ghcr.token
  - chmod 0600 /etc/cashpilot/*
  - test -z "\$(cat /etc/cashpilot/ghcr.token)" || cat /etc/cashpilot/ghcr.token | docker login ghcr.io -u cashpilot --password-stdin
  - docker pull "\$(cat /etc/cashpilot/image)@\$(cat /etc/cashpilot/digest)"
  - docker run --restart unless-stopped --init --network host --env CASHPILOT_UI_URL="\$(cat /etc/cashpilot/ui.url)" --env CASHPILOT_WORKER_URL="\$(cat /etc/cashpilot/worker.url)" --env CASHPILOT_API_KEY="\$(cat /etc/cashpilot/api.key)" --env CASHPILOT_VERSION="\$(cat /etc/cashpilot/release)" --volume /var/run/docker.sock:/var/run/docker.sock --name cashpilot-worker "\$(cat /etc/cashpilot/image)@\$(cat /etc/cashpilot/digest)"
EOF
)
custom_data_file=$(mktemp)
trap 'rm -f "$custom_data_file"' EXIT
printf '%s\n' "$cloud_init" > "$custom_data_file"

run az account set --subscription "$SUBSCRIPTION_ID"
run az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --subscription "$SUBSCRIPTION_ID" --tags cashpilot=true
run az network vnet create --resource-group "$RESOURCE_GROUP" --name "$VNET" --location "$LOCATION" --address-prefixes 10.90.0.0/16 --subnet-name "$SUBNET" --subnet-prefixes 10.90.0.0/24 --subscription "$SUBSCRIPTION_ID"
run az network nsg create --resource-group "$RESOURCE_GROUP" --name "$NSG" --location "$LOCATION" --subscription "$SUBSCRIPTION_ID"
rule=100
for spec in '22:Tcp:ssh' '4449:Tcp:mysterium-ui' '30000-30005:Tcp:nkn-tcp' '30000-30005:Udp:nkn-udp' '56000-56100:Udp:mysterium-udp'; do
  IFS=: read -r port protocol name <<<"$spec"
  run az network nsg rule create --resource-group "$RESOURCE_GROUP" --nsg-name "$NSG" --name "$name" --priority "$rule" --access Allow --direction Inbound --protocol "$protocol" --source-address-prefixes Internet --source-port-ranges '*' --destination-address-prefixes '*' --destination-port-ranges "$port" --subscription "$SUBSCRIPTION_ID"
  rule=$((rule + 10))
done
NIC_NAMES=("${VM_NAME}-nic-1" "${VM_NAME}-nic-2" "${VM_NAME}-nic-3")
for nic_name in "${NIC_NAMES[@]}"; do
  run az network nic create --resource-group "$RESOURCE_GROUP" --name "$nic_name" --vnet-name "$VNET" --subnet "$SUBNET" --network-security-group "$NSG" --location "$LOCATION" --subscription "$SUBSCRIPTION_ID"
done
for ((i=1; i<=IPV4_COUNT; i++)); do
  nic_index=$(( (i - 1) / 7 )); config_index=$(( (i - 1) % 7 + 1 )); NIC="${NIC_NAMES[$nic_index]}"
  pip="${VM_NAME}-pip-${i}"
  run az network public-ip create --resource-group "$RESOURCE_GROUP" --name "$pip" --location "$LOCATION" --sku Standard --allocation-method Static --subscription "$SUBSCRIPTION_ID"
  if ((i > 1)); then
    run az network nic ip-config create --resource-group "$RESOURCE_GROUP" --nic-name "$NIC" --name "ipcfg-${i}" --private-ip-address "10.90.0.$((i + 3))" --public-ip-address "$pip" --subscription "$SUBSCRIPTION_ID"
  else
    run az network nic ip-config update --resource-group "$RESOURCE_GROUP" --nic-name "$NIC" --name ipconfig1 --public-ip-address "$pip" --subscription "$SUBSCRIPTION_ID"
  fi
done
run az vm create --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --location "$LOCATION" --size "$VM_SIZE" --image "$IMAGE" --os-disk-size-gb "$OS_DISK_SIZE_GB" --storage-sku Premium_LRS --nics "${NIC_NAMES[@]}" --admin-username "$ADMIN_USERNAME" --ssh-key-values "$SSH_PUBLIC_KEY" --custom-data "$custom_data_file" --subscription "$SUBSCRIPTION_ID" --tags cashpilot=true release="$CASHPILOT_RELEASE"
run az vm show --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --show-details --subscription "$SUBSCRIPTION_ID" --output table
