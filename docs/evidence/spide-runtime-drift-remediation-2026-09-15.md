# Spide runtime drift remediation

## Root cause

Some existing Spide containers were created from a legacy bootstrap that referenced
`spide_linux_cli` and a DigitalOcean URL. The current R2 artifact extracts to
`spide_cli/spide`. The binary SHA was identical; the bootstrap command drift caused
the new catalog command to be serialized with broken nested `awk` quoting and enter
a Docker restart loop.

## Remediation

- Restored the server to `1.53.5` while isolating the bad rollout.
- Changed checksum extraction to a quote-safe `head -c 64 | tr a-f A-F` pipeline.
- Merged PR #414 and published release `v1.53.6`.
- Rolled out the server/UI and worker images with data and worker identity hashes preserved.
- Refreshed Spide slots on workers `118903` and `118904` without deleting volumes or device keys.

## Verification

- Both workers: `20` Spide runtime containers report `Status: OK`.
- Both workers: runtime executable SHA is `04F31522CBDB03B3D11E5293A3A18C6E910AED11B6D8B431B560BC7CB4ED08E5`.
- Current catalog uses only the R2 URL and `/data/spide/spide_cli/spide`.
- Spide collector remains dashboard-only; `collector_source` is empty.
- No collector process runs inside the node container.

## Remaining production gates

This fixes the Spide runtime drift only. Full production readiness still requires
the provider-wide network, lease/heartbeat, dashboard-vs-inventory, and lifecycle
evidence listed in the production execution plan.
