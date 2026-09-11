# Security audit report

## Executive result

One MEDIUM finding was confirmed and remediated in the current worktree. The
EarnApp WSS qualification probe disabled TLS certificate and hostname
verification, allowing a malicious/compromised configured proxy to forge a
`CID_SET` response and influence lease eligibility. The fix requires the
default trust store and hostname validation. The application otherwise has
explicit role guards, worker-key authentication, encrypted credential storage,
bounded subprocess/SSH wrappers, Docker path validation, and escaped client
rendering. This is not proof of fleet network isolation or browser-profile
behavior; those require deployment/browser evidence.

## Findings

### MEDIUM — EarnApp probe accepted forged provider verdicts

- Base cause: `build_tls_context` in `app/proxy_probe_profiles/earnapp.py`
  disabled certificate and hostname validation while `_open_wss_tunnel`
  connected to the fixed provider host.
- Impact: a malicious/compromised configured proxy could forge WebSocket
  `cid_set` frames; the result was persisted by the proxy recheck route and
  accepted by the EarnApp eligibility SQL, causing an unqualified proxy to be
  leased for EarnApp traffic.
- Remediation applied: `CERT_REQUIRED` plus `check_hostname=True`, with a
  regression test. Do not reintroduce `CERT_NONE`; if interception is required,
  use a narrowly scoped explicit CA.

## Hardening notes

- The EarnApp/NKN Unix helper sockets are protected by filesystem mode `0660`
  and the Docker group. Docker-group membership is intentionally equivalent to
  host administrative authority; keep the socket directory private and do not
  grant that group to untrusted users.
- The pre-fix `CERT_NONE` probe setting was the confirmed finding above and is
  now fixed in the current worktree. The remaining runtime
  `NODE_TLS_REJECT_UNAUTHORIZED=0` setting is a separate provider
  compatibility risk requiring runtime canary evidence before changing.
- Full proxy/DNS/IPv6/UDP/WebRTC leak testing still needs packet capture and
  reboot evidence on every provider/runtime family.
- Chrome profile 40 and token auto-import require an authenticated CDP session;
  source/tests are not a substitute for that live gate.
- Bandit scan completed after installing the audit-only tool: `0` high-severity
  findings. Its medium/low results are known intentional patterns (allowlisted
  SQL identifier construction, fixed HTTPS URLs, bounded subprocess wrappers,
  Docker/Unix socket permissions, and provider runtime bindings) and require no
  confirmed exploit in this run. `pip-audit -r requirements.txt` returned `No
  known vulnerabilities found`; compile, Ruff, baseline, and full pytest checks
  passed.

## Positive controls

- Owner/writer/reader authorization is centralized in `app/deps.py`.
- Worker heartbeat and command paths use worker-key authentication.
- Credentials are encrypted at rest; public views mask payout/proxy secrets.
- EarnApp egress ownership is sticky until account deletion, with CAS leases.
- Destructive account deletion requires account-name plus phrase confirmation.
- Docker host paths and runtime capabilities are validated before worker use.
