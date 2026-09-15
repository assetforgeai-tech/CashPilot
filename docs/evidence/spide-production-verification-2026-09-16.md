# Spide production verification (2026-09-16)

## Artifact

- Source: `https://pub-bf426a5300a643d2884389c8985f5181.r2.dev/spide_linux_cli.zip`
- Archive contents: `spide_cli/spide`
- Archive SHA-256: `AE03E67109BA125F8B317DEDB3DD31A3DF745F75ED647ABD57E7DEEF6328250C`
- Executable SHA-256: `04F31522CBDB03B3D11E5293A3A18C6E910AED11B6D8B431B560BC7CB4ED08E5`
- Catalog pin: `services/bandwidth/spide.yml` uses the same URL and checksum.

## Runtime/collector boundary

- The container executes only `/data/spide/spide_cli/spide`.
- It persists machine identity under the `spide-data` volume.
- CashPilot extracts `Device key` from worker logs and performs registration server-side.
- `app/provider_runtime.py` declares `collector_kind=dashboard_only` and an empty collector source.
- No Spide earnings collector is enabled; dashboard review remains manual.

## Verification

Focused Spide/catalog/automation tests: `60 passed`.

Full test suite: `1637 passed, 8 skipped`.

The compose image pins were stale (`1.6`) and were aligned to the current released series (`1.53`) in both compose templates, including the commented fleet worker template.

## Version mismatch conclusion

The R2 artifact is checksum-verifiable and is the authoritative runtime source. The Spide API/catalog currently provides no reliable client-version field in the dashboard response. A different Linux version shown by the dashboard cannot be attributed to CashPilot until a node log or provider API response exposes that version. The container must not run collector code to resolve this uncertainty.
