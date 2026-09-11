# Azure Live-Test Preflight — 2026-09-11

Status: `infrastructure-pass`, provider live matrix pending.

- Subscription: `0e4b9f20-f92f-4883-a598-3251b0016d65`, enabled, Azure CLI `2.87.0`.
- VM size: `Standard_D8s_v4`, 8 x64 vCPU, accelerated networking; available in `eastasia`.
- Japan East: SKU exists; subscription restriction applies only to availability zone `3`, so the command omits an explicit zone.
- Image: `Canonical:ubuntu-24_04-lts:server:latest`, x64 Gen2, verified in both regions.
- Quota: 10 regional vCPU and 10 DSv4-family vCPU available in each region; 20 Standard public IPv4 available in each region.
- Planned topology: 2 VMs, 10 Standard static IPv4 per VM, 512 GB Premium SSD (`Premium_LRS`, P20), one NIC with one public/private mapping per slot.
- East Asia bootstrap: manual execution of the canonical client setup script.
- Japan East bootstrap: cloud-init execution plus CashPilot auto-deploy.
- Provisioned: `cashpilot-live-ea` and `cashpilot-live-je`; both report `VM running`.
- Addressing: 20 unique Standard static public IPv4 addresses; 10 NIC IP configurations and 10 route-ready CashPilot slots per VM.
- Runtime: both `cashpilot-worker` containers are healthy and send authenticated heartbeat responses (`HTTP 200`) every minute.
- Enrollment: CashPilot DB shows both new workers online: East Asia worker `112494`, Japan East worker `112444`; raw client IDs are intentionally omitted from this report.
- Storage: both managed OS disks are 512 GB `Premium_LRS`; the guest root partition is expanded and Docker uses `/opt/cashpilot-runtime/docker`.
- Safety: no password, API key, provider token, proxy credential, or GHCR token is recorded in this evidence.
- Exposure: full TCP/UDP requires explicit `-AllowInternetAllPorts`; NSG and UFW are both opened only in that mode.

Command artifact: `D:\1. WORK_true\CashPilot\azure_create_vps_cli.txt`.

Production caveat: the current bootstrap source embeds a CashPilot API key and cloud-init places the transformed payload in Azure VM metadata. Acceptable for isolated canary only; production must fetch the key through Managed Identity + Key Vault.

## Defects found and fixed

- Repository helper scripts were not executable after clone. Host bootstrap now invokes both installers explicitly with `bash`; regression suite passed.
- Azure IMDS returned empty `publicIpAddress` values for secondary NIC configurations. Discovery now accepts a provisioner-generated Azure CLI NIC/PIP manifest; malformed or absent mappings still fail closed.
- Existing test bridges created before the corrected manifest had stale subnets. Only unused `cashpilot-direct-*` networks on the two new canary VPSs were recreated.
- Initial manual worker-unit recovery omitted the bootstrap key. The composition was corrected and both workers now authenticate successfully; no secret was retained locally.

## Remaining gate

- Merge/release the bootstrap correction so a brand-new Japan East cloud-init attempt proves the canonical startup path without recovery intervention.
- Run provider inputs, auto-deploy, lifecycle, reboot, one-hour shutdown, lease/rotation, collector/payment, and packet-leak matrices.
