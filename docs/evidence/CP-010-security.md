# CP-010 Security and Operations Audit

Date: 2026-09-21
Baseline: `origin/main` at `1c4db8bfcb850987c0b8517a31dccdbf4a69f399`
Mode: source-only, read-only audit. No production, Azure, worker, provider, registry, or credential access was used.

## Result

`FAIL` for production-readiness. Three source-backed operations findings need separately owned fixes. Live Azure NSG, GHCR package policy, repository environment protection, and deployed mount/capability state remain `INCONCLUSIVE` because CP-010 had no approved live-resource lock or credentials.

## Findings

### HIGH - Worker bootstrap opens broad inbound TCP and UDP ranges

- Evidence: `scripts/bootstrap-worker.sh:125` through `scripts/bootstrap-worker.sh:132` allow SSH, HTTP, HTTPS, TCP 30088, TCP/UDP 30000-30005, and TCP/UDP 32768-65535 without a source restriction.
- Concrete exposure: on a public Azure VM whose NSG also permits these destinations, any internet host can reach every listening process in the allowed ranges. The high ephemeral range substantially increases the blast radius of an accidentally bound service.
- Boundary: the repository proves the host firewall rule, not the active Azure NSG. Whether the exposure is reachable from the internet requires CP-007/CP-011 resource evidence.
- Fix task: make bootstrap consume the provider capability matrix, default-deny inbound, scope management ports to approved private/VPN CIDRs, and require explicit evidence for every public rule.
- Rollback: restore the previous UFW rule set from a captured pre-change export; never change a live worker without its resource lock and canary approval.

### MEDIUM - Bootstrap accepts mutable, unverified runtime inputs

- Evidence: `azure_create/worker-startup.sh:8` selects an arbitrary checkout path; line 28 executes `scripts/bootstrap-worker.sh` from that checkout as root. Lines 9 and 45 accept an image reference that defaults to a mutable release tag. No commit SHA, image digest, signature, or checksum is verified before execution/deploy.
- Concrete failure: a changed checkout or retagged image can execute with host-level bootstrap privileges or replace the worker runtime while still presenting the expected version string. Rollback cannot prove it restores the same bytes.
- Fix task: CP-006/CP-007 must bind the bootstrap script to a release SHA/checksum and the worker image to a verified digest, then record the previous digest for rollback.
- Rollback: retain and redeploy the last verified digest and checksum; do not use `latest` or a mutable tag as rollback authority.

### MEDIUM - Release CI combines write permissions with a mutable action ref

- Evidence: `.github/workflows/release.yml:19` through `.github/workflows/release.yml:21` grant `contents: write` and `packages: write` at workflow scope. `.github/workflows/release.yml:28` uses `actions/checkout@v7` rather than an immutable commit SHA. The publish job also has write permissions at `.github/workflows/release.yml:242` through `.github/workflows/release.yml:244`.
- Concrete failure: compromise or unexpected movement of the referenced action tag would run attacker-controlled action code with repository/package write authority on a main-branch release run.
- Fix task: pin every action to a full commit SHA and move permissions to the minimum job/step that requires them; protect release environments separately.
- Rollback: revert action pins to the last reviewed SHA and revoke/rotate any affected release credentials or packages after a suspected workflow compromise.

## Verified Controls

- Session keys reject known defaults and persist with mode `0600`: `app/auth.py:33` through `app/auth.py:72`.
- Bearer keys use constant-time comparison and resolve ambiguous key reuse toward the lower privilege: `app/auth.py:159` through `app/auth.py:177`.
- Worker enrollment cuts over from the shared key to per-worker keys and expires incomplete enrollment: `app/main.py:8464` through `app/main.py:8525`.
- Credential reads are masked: `app/main.py:7785` through `app/main.py:7790`.
- Worker API proxying pins validated hostnames to resolved IPs and suppresses raw worker error bodies: `app/main.py:5436` through `app/main.py:5563`.
- Default compose bindings are loopback-only; UI credential storage and Docker-socket worker storage are separate: `docker-compose.yml:28` through `docker-compose.yml:37`, `docker-compose.yml:105` through `docker-compose.yml:123`.
- Browser hardening includes nonce CSP, frame denial, MIME sniffing denial, and conditional HSTS: `app/main.py:2829` through `app/main.py:2878`.
- Destructive critical-volume override requires owner role: `app/main.py:5358` through `app/main.py:5397`.

## Commands and Evidence

```text
git fetch origin main --prune
git rev-parse origin/main
rg -n <security and operations patterns> app azure_create .github scripts docker-compose*.yml
targeted Get-Content line-number reviews for auth, routes, compose, bootstrap, worker API, and release workflow
```

Secret scan output was reviewed only as source locations; no credential values were copied into this evidence.

## Quality Gates

```text
uv run pytest
3356 passed, 7 skipped in 236.27s

uv run ruff check .
All checks passed!

uv run ruff format --check .
485 files already formatted

python -m compileall -q app tests
exit 0

git diff --check
exit 0
```

## Remaining Risks

- Azure NSG exposure: `INCONCLUSIVE` without approved read-only Azure access.
- Deployed Docker capabilities and mount parity: `INCONCLUSIVE` without approved `docker inspect` access.
- GitHub branch/environment rules and GHCR package visibility: `INCONCLUSIVE` without repository administration access.
- Provider behavior: not inferred; no provider endpoint or credential was exercised.
