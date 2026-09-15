# Spide runtime and collector separation

## Verified source of truth

- Runtime artifact: `https://pub-bf426a5300a643d2884389c8985f5181.r2.dev/spide_linux_cli.zip`
- ZIP contents: one executable at `spide_cli/spide`
- Executable SHA-256: `04F31522CBDB03B3D11E5293A3A18C6E910AED11B6D8B431B560BC7CB4ED08E5`
- Catalog command downloads the R2 artifact, verifies the hash, persists it at `/data/spide/spide_cli/spide`, then executes only that binary.

## Separation contract

- Node runtime: CLI startup only. It emits a Device key and provides Spide bandwidth service.
- Registration: CashPilot server-side automation calls `/api/v1/device/create` with the emitted Device key.
- Collector: `provider-runtime/provider_collector/spide.py` is dashboard/manual guidance only; `collector_source` is empty and no collector process is injected into the node.
- Credentials: dashboard token is used by server registration, never passed into the runtime container.

## Drift found and disposition

The historical tested script under `provider-runtime/audit_code/spide/00_TESTED_SOURCE_RUNTIME.py` referenced a retired DigitalOcean URL and combined host `systemd` setup with account login. The active CashPilot catalog no longer uses that URL. Existing containers were refreshed only after preserving their data volumes/device keys; no collector code was added to nodes.

## Verification

Focused catalog, registration, and deploy tests pass. The deployed Azure evidence records `20/20` Spide containers per worker with `Status: OK` and the pinned executable hash. Any node still reporting the old endpoint is runtime drift and must be refreshed, not registered through the collector.
