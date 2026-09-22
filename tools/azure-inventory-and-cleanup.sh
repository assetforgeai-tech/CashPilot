#!/usr/bin/env bash
set -euo pipefail

# CP-014J: inventory first; deletion stays opt-in and exact-name scoped.
RESOURCE_GROUP="${RESOURCE_GROUP:-rg-cashpilot-live-test-20260911}"
DRY_RUN=true
CP014J_APPROVED="${CP014J_APPROVED:-false}"

usage() { printf '%s\n' "Usage: $0 [--dry-run] [--approve]"; }
while (($#)); do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --approve) CP014J_APPROVED=true; DRY_RUN=false; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
done

az resource list --resource-group "$RESOURCE_GROUP" \
  --query '[].{id:id,name:name,type:type,location:location,tags:tags}' --output json

if [[ "$DRY_RUN" == true || "$CP014J_APPROVED" != true ]]; then
  printf '%s\n' '# dry-run: no Azure mutation performed'
  exit 0
fi

[[ "$RESOURCE_GROUP" == "rg-cashpilot-live-test-20260911" ]] || {
  printf '%s\n' 'refusing mutation outside approved resource group' >&2; exit 3;
}

# Never target live workers or broad resource groups; callers must provide exact names.
IFS=',' read -r -a targets <<< "${CP014J_RESOURCE_NAMES:-}"
[[ ${#targets[@]} -gt 0 && -n "${targets[0]}" ]] || {
  printf '%s\n' 'CP014J_RESOURCE_NAMES is required for approved mutation' >&2; exit 3;
}
for name in "${targets[@]}"; do
  [[ "$name" == cashpilot-cp014j-* ]] || {
    printf 'refusing out-of-scope resource: %s\n' "$name" >&2; exit 3;
  }
  az resource show --resource-group "$RESOURCE_GROUP" --name "$name" --resource-type "Microsoft.Compute/virtualMachines" >/dev/null 2>&1 || {
    printf 'resource is not an exact CP-014J VM: %s\n' "$name" >&2; exit 3;
  }
  az resource delete --resource-group "$RESOURCE_GROUP" --name "$name" \
    --resource-type "Microsoft.Compute/virtualMachines"
done
