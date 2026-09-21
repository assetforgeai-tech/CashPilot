#!/usr/bin/env bash
set -euo pipefail

dry_run=false
subscription= resource_group= name= location= size= image= public_ip_count=1
admin_username=cashpilot ssh_key= admin_password= startup_script=azure_create/worker-startup.sh
allowed_ports=(22)
while (($#)); do
  case "$1" in
    --subscription) subscription=${2:?missing value}; shift 2 ;;
    --resource-group) resource_group=${2:?missing value}; shift 2 ;;
    --name) name=${2:?missing value}; shift 2 ;;
    --location|--region) location=${2:?missing value}; shift 2 ;;
    --size) size=${2:?missing value}; shift 2 ;;
    --image) image=${2:?missing value}; shift 2 ;;
    --os-disk-size-gb) os_disk=${2:?missing value}; shift 2 ;;
    --public-ip-count|--public-ip-addresses) public_ip_count=${2:?missing value}; shift 2 ;;
    --startup-script) startup_script=${2:?missing value}; shift 2 ;;
    --ssh-key) ssh_key=${2:?missing value}; shift 2 ;;
    --admin-username) admin_username=${2:?missing value}; shift 2 ;;
    --admin-password) admin_password=${2:?missing value}; shift 2 ;;
    --allow-port) allowed_ports+=("${2:?missing value}"); shift 2 ;;
    --full-tcp-udp) [[ ${FULL_TCP_UDP_APPROVED:-} == true ]] || { echo 'full TCP+UDP requires FULL_TCP_UDP_APPROVED=true' >&2; exit 2; }; shift ;;
    --dry-run) dry_run=true; shift ;;
    --verify) verify=true; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
for value in "$subscription" "$resource_group" "$name" "$location" "$size" "$image"; do [[ $value != *$'\n'* && $value != *$'\r'* ]] || { echo 'values must not contain newlines' >&2; exit 2; }; done
[[ -n $ssh_key || -n $admin_password ]] || { echo 'provide --ssh-key or --admin-password' >&2; exit 2; }
args=(vm create --subscription "$subscription" --resource-group "$resource_group" --name "$name" --location "$location" --size "$size" --image "$image" --os-disk-size-gb "${os_disk:-64}" --public-ip-sku Standard --nsg-rule NONE --tags cashpilot=true "startup-script=$startup_script" "public-ip-count=$public_ip_count")
for port in "${allowed_ports[@]}"; do args+=(--nsg-rule "$port"); done
if [[ -n $ssh_key ]]; then args+=(--admin-username "$admin_username" --ssh-key-values "$ssh_key"); else args+=(--admin-username "$admin_username" --admin-password "$admin_password"); fi
if $dry_run; then printf '%s\n' "az ${args[*]}"; exit 0; fi
az "${args[@]}"
if [[ ${verify:-false} == true ]]; then az vm show --subscription "$subscription" --resource-group "$resource_group" --name "$name" --show-details --output json; fi
