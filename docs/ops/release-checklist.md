# CashPilot Release Candidate Checklist

Run from a clean checkout of `origin/main`. Production rollout remains disabled
until CP-013 receives separate explicit approval.

## Candidate inputs

- Record the release commit, proposed semantic version, and previous rollback version.
- Confirm all required CP-001 through CP-011 PRs are merged and evidence paths resolve.
- Confirm no credentials, cookies, private keys, runtime identity volumes, or raw provider responses are in the release.
- Confirm image references are immutable GHCR digests and GitHub assets have SHA-256 checksums.
- Confirm the manifest includes the pinned `ghcr.io/sagernet/sing-box` sidecar
  digest used by `app/orchestrator.py`; container-image entries are verified by
  reference digest, while file entries are verified by local SHA-256.

## Verification

```powershell
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
python -m compileall -q app tests
git diff --check
python tools/verify-runtime-manifest.py --manifest runtime-manifest.json --artifact-dir . --state .runtime-active.json
```

The manifest verifier must finish with exit code `0`. A failed verification must
leave the previous active pointer unchanged. A container-image artifact does not
require a same-named local file: its `reference` digest must equal `sha256`, and
`--pull` optionally preloads that exact immutable reference.

## Rollback

1. Stop the staged worker deployment.
2. Restore the previous immutable manifest and image digests.
3. Restart the worker and verify heartbeat, provider state, leases, egress, DNS,
   and collectors.
4. Preserve logs and evidence; do not delete the previous artifact until the
   rollback verification is recorded.

Rollback keeps provider identity volumes, credentials, and leases unchanged.
Never use a mutable tag or recreate identity-bearing nodes as a release rollback.

## Approval gate

This checklist prepares CP-012 only. Do not create a release tag, publish a
production deployment, or execute CP-013 without explicit approval.
