# Dashboard Session Masking Impact Map

## Scope

This narrowly scoped follow-up closes the `dawn_dashboard_session` read-path
classification gap found during the v1.8.0 authenticated audit. It changes
only the database secret-key suffix set and adds a regression test.

## Affected paths

- `app/database.py`: classify keys ending in `dashboard_session` as secrets.
- `tests/test_settings_contract.py`: prove masked reads omit the value while
  the existing runtime read path remains backward-compatible.
- UI image only: `/api/config` is served by the CashPilot UI. The worker image
  does not copy `app/database.py` and is not part of this runtime change.

## Preserved contracts

- `database.get_config()` still decrypts and returns the value to the server's
  internal runtime code when that code explicitly needs it.
- `database.get_config_masked()` returns only `_secrets[key] = true` for the
  classified key.
- Existing rows written before the classifier was widened remain readable;
  `decrypt_value()` continues to accept the legacy unencrypted representation.
- No provider catalog, deploy spec, proxy pool row, lease, wallet, identity,
  worker, container, volume or scheduler state is changed.

## Verification and release boundary

- Regression test fails before the classifier change and passes afterward.
- Full source suite, Ruff, format, compileall and diff checks must pass.
- Release/deploy is UI-only; `cashpilot-worker` must remain unchanged.
- Post-release verification must call `GET /api/config` with an owner
  credential and confirm the key is absent from the ordinary map while its
  presence is reported under `_secrets`, without recording the value.
