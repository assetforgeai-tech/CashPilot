# Azure worker provisioning

`azure_create/create-worker.ps1` and `azure_create/create-worker.sh` generate an explicit `az vm create` command. Dry-run is side-effect free and deterministic; use SSH key mode by default.

```powershell
./azure_create/create-worker.ps1 -SubscriptionId $subscription -ResourceGroup cashpilot-workers -Name worker-01 -Region japaneast -SshPublicKey $key -DryRun
```

```bash
./azure_create/create-worker.sh --subscription "$SUBSCRIPTION" --resource-group cashpilot-workers --name worker-01 --location japaneast --size Standard_B2s --image Ubuntu2204 --ssh-key "$SSH_KEY" --dry-run
```

Only required provider-matrix ports may be added. `--full-tcp-udp` is rejected unless `FULL_TCP_UDP_APPROVED=true`; record approval and evidence before enabling it. Password mode emits a warning and never stores credentials in this repository. Post-create verification uses `az vm show --show-details`; no production or forbidden worker is implied by these commands.
