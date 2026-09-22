# CP-012 partial-release recovery

Run `35741496361` failed in `Verify CI passes` because the previous run had already created release/tag `v1.62.0` and failed before the compose-pin step. The repository still pinned `1.61`, while the released-tag sweep correctly expected `1.62`; a blind rerun would calculate a new release instead of repairing the existing one.

This change pins the compose examples to `1.62` and adds an explicit `workflow_dispatch` recovery input (`recover_version`). Recovery skips normal version/build/tag publication, authenticates to GHCR, resolves the existing immutable image digests with bounded retry, and uploads only the missing runtime manifest to the existing release. It never deletes or recreates tags, releases, or images.

Local focused tests: 29 passed. Full CI is required before merge.
