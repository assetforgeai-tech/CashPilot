# Security audit report

## Executive result

No exploitable vulnerability was confirmed in this source-first run. The
application has explicit role guards, worker-key authentication, encrypted
credential storage, bounded subprocess/SSH wrappers, Docker path validation,
and escaped client rendering. This is not proof of fleet network isolation or
browser-profile behavior; those require deployment/browser evidence.

## Findings

None confirmed.

## Hardening notes

- The EarnApp/NKN Unix helper sockets are protected by filesystem mode `0660`
  and the Docker group. Docker-group membership is intentionally equivalent to
  host administrative authority; keep the socket directory private and do not
  grant that group to untrusted users.
- `app/proxy_probe_profiles/earnapp.py` intentionally uses `ssl.CERT_NONE` for
  the provider probe contract. This is a provider-compatibility risk, not a
  confirmed CashPilot privilege or data-exfiltration vulnerability in this run.
- Full proxy/DNS/IPv6/UDP/WebRTC leak testing still needs packet capture and
  reboot evidence on every provider/runtime family.
- Chrome profile 40 and token auto-import require an authenticated CDP session;
  source/tests are not a substitute for that live gate.
- Bandit was unavailable in the audit environment. `pip-audit -r
  requirements.txt` returned `No known vulnerabilities found`; compile, Ruff,
  baseline, and full pytest checks passed.

## Positive controls

- Owner/writer/reader authorization is centralized in `app/deps.py`.
- Worker heartbeat and command paths use worker-key authentication.
- Credentials are encrypted at rest; public views mask payout/proxy secrets.
- EarnApp egress ownership is sticky until account deletion, with CAS leases.
- Destructive account deletion requires account-name plus phrase confirmation.
- Docker host paths and runtime capabilities are validated before worker use.
