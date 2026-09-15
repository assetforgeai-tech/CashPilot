# Spide production verification (2026-09-16)

- Authoritative artifact: `https://pub-bf426a5300a643d2884389c8985f5181.r2.dev/spide_linux_cli.zip`.
- Archive contains only `spide_cli/spide`.
- SHA-256: `04F31522CBDB03B3D11E5293A3A18C6E910AED11B6D8B431B560BC7CB4ED08E5`.
- `services/bandwidth/spide.yml` pins the same URL/checksum and executes only the CLI.
- `app/provider_runtime.py` declares Spide `dashboard_only` with an empty collector source.
- Device-key parsing and registration happen server-side; collector code is not run in the node.
- Focused Spide/catalog/automation tests: `4 passed`.
- Full suite: `1635 passed, 8 skipped`.

The dashboard/API does not expose a reliable client-version field. A different Linux version cannot be attributed to CashPilot without node logs or a provider response exposing it.
