# CP-013 admin-key rotation - 2026-09-25

## Scope

Remediate diagnostic exposure of the canonical `CASHPILOT_ADMIN_API_KEY`.
Only the control-plane compose key and `cashpilot-ui` were changed. No worker,
provider, node, proxy, lease, wallet, account-pool, Azure resource, or
auto-deploy state was changed.

## Backup and rotation

- Host: `42.96.13.215:26266`.
- Backup: `/opt/cashpilot/backups/admin-key-rotate-20260925T063748Z`.
- Previous compose was copied before replacement; file mode remained `0600`.
- New key was generated on the control-plane host and transferred through a
  mode-`0600` temporary artifact only.
- New local key file `cashpilot_api_key.txt` was updated atomically; no key value
  or fingerprint is recorded here.
- Temporary remote key artifact was removed after transfer.

## Verification

- New key against `/api/fleet/summary`: HTTP `200`.
- Previous key against `/api/fleet/summary`: HTTP `401`.
- `cashpilot-ui`: healthy, immutable v1.68.3 digest unchanged.
- `cashpilot-worker`: image, start time, and health unchanged; health `healthy`.
- Worker `172243`: online, key confirmed, version `1.68.3`, fresh heartbeat.
- Public-IP slots: `20`; route-ready: `20`.
- Version skew: `false`.
- Auto-deploy: `false`.
- Fleet summary: `2` online workers, `7` registrations, `1` running service.

## Result

Admin-key remediation: **PASS**. Provider deployment remains disabled; the
next mutation still requires a separate staged provider/auto-deploy approval.
No secret is present in this evidence.
