# Azure Live-Test Preflight — 2026-09-11

Status: `preflight-pass`, provisioning not started.

- Subscription: `0e4b9f20-f92f-4883-a598-3251b0016d65`, enabled, Azure CLI `2.87.0`.
- VM size: `Standard_D8s_v4`, 8 x64 vCPU, accelerated networking; available in `eastasia`.
- Japan East: SKU exists; subscription restriction applies only to availability zone `3`, so the command omits an explicit zone.
- Image: `Canonical:ubuntu-24_04-lts:server:latest`, x64 Gen2, verified in both regions.
- Quota: 10 regional vCPU and 10 DSv4-family vCPU available in each region; 20 Standard public IPv4 available in each region.
- Planned topology: 2 VMs, 10 Standard static IPv4 per VM, 512 GB Premium SSD (`Premium_LRS`, P20), one NIC with one public/private mapping per slot.
- East Asia bootstrap: manual execution of the canonical client setup script.
- Japan East bootstrap: cloud-init execution plus CashPilot auto-deploy.
- Safety: no Azure resource created; no password, API key, provider token, proxy credential, or GHCR token recorded.
- Exposure: full TCP/UDP requires explicit `-AllowInternetAllPorts`; NSG and UFW are both opened only in that mode.

Command artifact: `D:\1. WORK_true\CashPilot\azure_create_vps_cli.txt`.

Production caveat: the current bootstrap source embeds a CashPilot API key and cloud-init places the transformed payload in Azure VM metadata. Acceptable for isolated canary only; production must fetch the key through Managed Identity + Key Vault.
