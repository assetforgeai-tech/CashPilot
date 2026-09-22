# CP-012 private GHCR manifest authentication

Auto Release run `35737694409` on `41f4115fe08f5fdd2f7bc25d4b2e752ce314e408` built and verified both `v1.61.2` images successfully. `Tag and announce` then failed all six digest attempts for the UI image. The `verify-tags` job authenticated to GHCR and passed; the `publish` job neither requested `packages: read` nor logged in. Private GHCR consequently returned `not found`. Release `v1.61.2` exists with no assets.

The publish job now grants read-only package permission and uses the repository-pinned GHCR login action before immutable digest inspection. Existing retry and fail-closed behavior remains unchanged.

Verification: 29 focused release/action-pin tests passed; full Ruff, format, compileall, and diff checks passed. No tag, release, image, Azure, VPS, or provider resource was deleted or mutated.
