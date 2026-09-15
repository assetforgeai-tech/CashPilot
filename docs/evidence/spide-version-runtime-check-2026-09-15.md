# Spide version and runtime check

Captured 2026-09-15 from both Azure workers. Device keys are intentionally omitted.

## Runtime output

All sampled Spide containers reported the same provider build and client version:

- Build version: `2026-08-13_07:48:40-LINUX`
- Client version: `15`
- Config: `https://pub-bf426a5300a643d2884389c8985f5181.r2.dev/client_config_prod_v0.1.json`
- Server: `158.255.7.213:50001`

The result was identical on workers `118903` and `118904`. This is the version
actually emitted by the official CLI, not a version embedded in CashPilot's
Python setup or collector module.

## Artifact identity

- Download source: `https://pub-bf426a5300a643d2884389c8985f5181.r2.dev/spide_linux_cli.zip`
- ZIP SHA-256: `AE03E67109BA125F8B317DEDB3DD31A3DF745F75ED647ABD57E7DEEF6328250C`
- Executable SHA-256: `04F31522CBDB03B3D11E5293A3A18C6E910AED11B6D8B431B560BC7CB4ED08E5`

The historical DigitalOcean URL used by the raw reference currently returns
HTTP 404. It is not the active production source.

## Runtime/collector boundary

- Node containers execute only `/data/spide/spide_cli/spide`.
- CashPilot registers the emitted Device key server-side through
  `/api/v1/device/create`.
- `provider-runtime/provider_collector/spide.py` is manual/dashboard guidance
  only; `collector_source` is empty and no collector process is injected into
  a node.

## Conclusion

The dashboard/runtime version difference is not evidence that the collector is
running in the node. The current runtime is pinned and verifiable by artifact
hash. If a dashboard row shows another version, treat it as provider-side
display/cache or an old container and compare the container executable hash
before refreshing that specific node.
