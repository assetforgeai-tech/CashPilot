# Production scope correction

Date: 2026-09-14

## Authoritative scope

- Production live-test scope is the two newly created Azure workers only.
- `test-sing` and `test-us` are excluded from production evidence and were not
  mutated.
- EarnApp proxy selection follows the operator's per-proxy OS/platform policy;
  no non-VN restriction is imposed by this gate.

## Current Azure inventory

- East Asia worker: one Earn.fm direct runtime.
- Japan East worker: one PacketStream proxy runtime plus its egress sidecar.
- Both workers now run `cashpilot-worker:1.50.18`, healthy, `restart=always`.
- Existing provider containers and worker data/identity were preserved.

## Evidence boundary

The existing repository contains accepted historical provider-dashboard earning
evidence for EarnApp and node-side accepted evidence for NKN. That evidence
does not substitute for a fresh Azure canary. A provider is not production-pass
until its Azure runtime is compared with the provider dashboard (or its
documented authoritative node signal), then usage/balance delta, egress,
fail-closed network, restart/reboot, and lease lifecycle are recorded.

## Next controlled gate

Deploy one owner-authorized canary lane at a time on the Azure workers. Start
with the provider/lane whose credentials and proxy capacity are already marked
ready in CashPilot. Stop on any missing credential, ambiguous topology, missing
provider-dashboard signal, or direct-fallback evidence. Do not bulk-deploy or
clean existing Azure provider containers.
