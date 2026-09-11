# Release integrity check — 2026-09-11

## Verified

- PR #246 is open against `main`.
- GitHub checks currently pass: Tests, Lint/Ruff, Documentation build, and CodeQL.
- Compose YAML parses successfully with Python YAML parser.
- Python bytecode compilation passes for `app/` and `tests/`.
- `git diff --check` reports no whitespace errors.
- Compose examples pin both UI and worker to `ghcr.io/assetforgeai-tech/...:1.32`.
- Release workflow has `contents: write` and `packages: write`, builds both multi-arch images, and verifies published tags with `docker manifest inspect`.
- Release workflow gates publication on Python 3.14, frozen dependencies, Ruff, and the full test suite.

## Local limitations

- Docker CLI is not installed in this Windows audit environment; local `docker compose config` and manifest inspection cannot run here. CI remains the authoritative Docker/build evidence.
- Local audit changes are not committed or pushed.
- Registry digest verification for the current deployed environment remains pending.
- Local GHCR manifest query returns `401`; the configured `gh` token lacks `read:packages`, so registry digest cannot be independently verified from this session.

## Security note

The EarnApp runtime spec contains `NODE_TLS_REJECT_UNAUTHORIZED=0` for the existing upstream emulation contract. This is intentionally preserved during the audit, but it remains a production risk requiring upstream certificate/pinning evidence before claiming a fully hardened transport.

## Status

`PARTIAL`: CI/release configuration is structurally verified; local Docker and deployed digest evidence remain pending.
