# Spide runtime/collector audit (2026-09-16)

## Result

Spide runtime and earnings collection are separate concerns. The node must run
only the official Linux CLI; login/device registration and any dashboard
collection remain server-side.

## Runtime evidence

- R2 archive: `https://pub-bf426a5300a643d2884389c8985f5181.r2.dev/spide_linux_cli.zip`
- Archive SHA-256: `AE03E67109BA125F8B317DEDB3DD31A3DF745F75ED647ABD57E7DEEF6328250C`
- Binary SHA-256: `04F31522CBDB03B3D11E5293A3A18C6E910AED11B6D8B431B560BC7CB4ED08E5`
- Archive contains only `spide_cli/spide`.
- Azure workers `118903` and `118904` run worker image `1.53.14`; Spide
  direct/proxy containers were present in the read-only runtime snapshot.
- Container logs show recurring `Status: OK`; no collector process is present
  in the Spide container.

## Source comparison

The legacy reference used a DigitalOcean Spaces URL that now returns `404`, so
its binary version cannot be compared. The R2 artifact is the only current,
checksum-pinned runtime source. The provider dashboard does not expose a
reliable client-version field through the verified API response.

The legacy script performs three actions: account login, CLI `Device key`
extraction, and `POST /api/v1/device/create`. CashPilot keeps these actions
outside the container: it extracts the key from worker logs and registers it
server-side. The registration request uses the raw flow's
`application/x-www-form-urlencoded` framing and `X-Requested-With` header.

## Conclusion

No evidence shows that a collector embedded in the node caused the reported
HTTP 500. Copying the whole legacy script into a node would violate the
runtime boundary and is rejected. A concrete 500 response body/request trace
is still required before diagnosing a provider-side error.
