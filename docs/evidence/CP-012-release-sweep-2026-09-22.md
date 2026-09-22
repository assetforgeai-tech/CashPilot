# CP-012 release/CI failure sweep

## Reproduction

GitHub Actions run `35727691199` on `3a2af8b328157e4ab02e6be1a3a2ce8e56ec7d1f` failed only at `Tag and announce / Attach immutable runtime manifest` for `v1.61.0`. CI, versioning, build, and tag verification passed. The tag and GitHub Release already existed; no existing release/tag/GHCR object was deleted.

The publish job did not fetch `refs/fork-tags/*`. Under `set -euo pipefail`, the `grep -v ... | head` pipeline returned status 1 when no prior tag was visible, so the fallback was never reached. The manifest asset was therefore not uploaded.

## Changes

- Added `scripts/create_release_runtime_manifest.py` with strict semver, digest, and rollback-tag validation.
- Publish job now fetches fork tags before manifest generation and passes all tags to the helper.
- Missing rollback tag or invalid image digest fails closed before upload.
- Serialized main release publication with a non-canceling concurrency group to prevent duplicate version calculations.
- Updated compose example pins to released series `1.60` and aligned the regression assertion with the helper.

## Verification

- Focused release/runtime/compose tests: `34 passed`.
- `uv run ruff check .`: pass.
- `uv run ruff format --check .`: pass.
- `python -m compileall -q app tests scripts`: pass.
- `git diff --check`: pass.

## Scope

No Azure, VPS, provider, production, GitHub Release, tag, or GHCR deletion/mutation was performed. The branch is ready for review/CI; coordinator must merge only after CI passes.
