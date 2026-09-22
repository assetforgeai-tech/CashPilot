# CP-012 release candidate and rollback package

Date: 2026-09-22

## Scope

Prepared the operator-facing release and rollback checklist from merged
`origin/main` after CP-011. No production resource, provider account, VPS, or
Azure worker was mutated.

## Inputs verified

- CP-011 canary PR #461 merged at commit `a618832f4edc92490f91ce32241fff7765308424`.
- CP-011 machine-readable evidence records watchdog rotation, reboot persistence,
  reconciliation, and cleanup.
- Runtime manifest schema and verifier are present and require immutable GHCR
  digest references plus SHA-256 artifact checks.
- Release workflow generates `runtime-manifest.json` and attaches it to the
  GitHub Release; tag creation remains an explicit release action.

## Deliverables

- `docs/ops/release-checklist.md`
- Existing `release/runtime-manifest.schema.json`
- Existing `tools/verify-runtime-manifest.py`

## Known limitations

- No release tag was created; CP-012 does not authorize publishing.
- Production rollout is intentionally disabled and remains CP-013 scope.
- Runtime manifest signing is optional unless a worker supplies
  `CASHPILOT_RUNTIME_MANIFEST_KEY`; unsigned manifests are accepted only when no
  verification key is configured.

## Verification

The focused manifest tests and full repository gates must run before merge. The
release candidate is acceptable only when CI is green and the verifier preserves
the previous active pointer on checksum failure.

## Rollback reference

Use `docs/ops/release-checklist.md` section `Rollback`. It preserves identity
volumes, credentials, and leases, and restores only immutable prior artifacts.
