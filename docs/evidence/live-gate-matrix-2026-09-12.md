# CashPilot live-gate matrix — 2026-09-12

Status vocabulary: `verified` requires direct evidence; `unverified` means no
authoritative proof yet; `blocked` means the required observation path is
unavailable. No status below authorizes production deployment by itself.

| Gate | Status | Evidence | Next proof |
|---|---|---|---|
| Azure subscription/topology | verified | Azure CLI subscription `0e4b9f20-f92f-4883-a598-3251b0016d65`; `cashpilot-live-ea`/`cashpilot-live-je` are `Standard_D8s_v4`, Ubuntu 24.04, 512 GB `Premium_LRS`, with 10 unique Standard IPv4 addresses each; idempotent dry-run passed | Recheck before each destructive scenario |
| East Asia bootstrap | verified | Worker enrollment and heartbeat evidence | Fresh bootstrap without recovery intervention |
| Japan East cloud-init | verified | Worker enrollment evidence | Fresh VM rebuild, then auto-deploy |
| Japan East reboot persistence | verified | Service active, worker healthy, 10 bridge networks, 10 slots after reboot | Route-rule and heartbeat log sample |
| Repository tests/lint/security | verified | Local Windows run: `2824 passed, 8 skipped`; PR #297 latest CI: Analyze, build (strict), Ruff, and test all successful; focused proxy/UI regressions pass; Ruff/build/pip-audit clean | Repeat after runtime fixes |
| Chrome profile 40 UI sweep | verified | Isolated CDP session for authenticated `Profile 40` at `127.0.0.1:9227`; ten navigation surfaces captured with full-page PNG/text evidence | Complete destructive-control, responsive, keyboard, and provider-input interaction pass |
| Provider credentials/input | unverified | Inventory report only; secret values redacted | Authenticated provider inspection |
| Proxy metadata/location/IP type | unverified | API/UI implementation present | Live recheck sample across providers |
| UDP/DNS/IPv4/IPv6/DoH leak matrix | unverified | Unit coverage only | Packet capture per runtime/provider |
| EarnApp token auto-import/expiry | unverified | Source contracts/tests | Live extension/profile test |
| Lease/release/sticky ownership/rotation | unverified | Policy tests and DB schema | Live mutation matrix |
| Collector/payment/PayPal | unverified | API/UI source and tests | Authenticated provider collector test |
| One-hour shutdown/recovery | unverified | Reboot persistence only | Stop worker/VPS >1h, verify recovery |
| GHCR private image publication | unverified | Candidate digests exist, but authenticated private pull with a rotated `read:packages` token is not evidenced | Rotate credential, verify pull, record digest |
| Global auto-deploy | intentionally disabled | `cashpilot_auto_deploy_enabled=false` | Enable only after scoped live matrix passes |
| Main branch protection | verified | Required PR review (1), strict Analyze/build/ruff/test checks, no force-push/delete, admin enforcement | Keep rules aligned with release policy |

## Decision

Infrastructure and repository gates pass. Production gate remains open until
the external-observation rows are directly verified. Legacy VPS cleanup is not
a prerequisite and remains out of scope.

## Read-only server snapshot (2026-09-12)

The CashPilot UI database was queried through the pinned server SSH helper,
without mutating state: 6 workers, 1,254 proxy endpoints (981 currently
`alive`), 4 EarnApp account rows, 85 EarnApp logical-node rows, and 20 active
provider proxy leases. These counts are reconciliation inputs, not proof that
all provider/runtime rows are healthy or that every lease is correctly routed.

## UI-only rollout (2026-09-12)

- Release `v1.33.0` deployed to `cashpilot-ui` only.
- UI is `healthy`; observed image digest: `sha256:23f17e1d2d472e72a6b8a4d940aabc8811109a3137e503ae6c441762a631aa7d`.
- Worker remained unchanged: healthy, restart count `0`.
- SQLite integrity: `ok`.
- `cashpilot_auto_deploy_enabled=false`; worker scope pinned to Azure workers
  `112494,112444`. No provider deployment was triggered.
- Pre-deploy database backup succeeded outside container `/tmp`.

## EarnApp runtime image publication (2026-09-12)

- Published private GHCR candidate tag `20260912-production-candidate` for
  MacOS, iOS, and Ubuntu runtime images.
- Digests: MacOS `sha256:45c62c73242a281f5e293a6249bae4706b3c2ff8f9ec23a01b3a01a7a879170d`; iOS `sha256:f7ca70ce9ef7bd72321bafa8be3f00047ceb056e67221ac93c10394592049930`; Ubuntu `sha256:70265ba720c27bb9398f97432fd9e151f841aedf679c1f82831080ac9d0109e3`.
- Build/push completed through the existing controlled script; temporary token
  and staging files were removed. Secret values are absent from the publish log.
- The server-side GHCR session was logged out and the staging token/script files
  were removed. GHCR package API visibility could not be queried from this
  workstation because its token lacks `read:packages`; package privacy remains
  `unverified` until an authenticated read-only query is run.

## Read-only credential/worker snapshot (2026-09-12)

- EarnApp accounts: 2 `ACTIVE`, 2 `DELETED`.
- Rows with persisted `token_expires_at`: `0`; rows marked
  `needs_token_refresh`: `0`. This is missing expiry evidence, not proof that
  upstream tokens cannot expire.
- Workers: 5 `online` of 6 total.

## Azure firewall snapshot (2026-09-12)

- Both Azure workers report `cashpilot-worker` healthy and `UFW active`.
- East Asia exposes the explicitly requested test ports, including TCP/UDP
  ranges for provider testing.
- Japan East currently has additional `1:65535/tcp` and `1:65535/udp` rules for
  IPv4 and IPv6. This is an accepted isolated-test exposure, not a production
  default; remove before production and retain only the minimum provider ports.
- Firewall state alone does not prove proxy no-leak behavior; packet capture is
  still required.

## Azure control-plane recheck (2026-09-12)

- Azure Instance View reports both `cashpilot-live-ea` and `cashpilot-live-je`
  `VM running`, provisioning succeeded, and VM agent `Ready`.
- Azure Run Command returned no response within the bounded observation window;
  this is treated as inconclusive and not as worker-health evidence. No VM
  restart was issued because of the timeout.
- A post-VMAccess `az vm run-command invoke` probe again returned no output
  within 60 seconds. SSH remains the authoritative guest-observation channel;
  no VM restart or extension repair was attempted.
- Read-only NIC inspection confirms 10 IP configurations on each VM and 20
  unique public IPv4 addresses overall. Both OS disks report `Premium_LRS` and
  the VM model reports 512 GB. Both East Asia and Japan East NSGs still allow
  `*` TCP and `*` UDP from Internet; this remains test-only exposure.
- Direct managed-disk inspection confirms `osdisk-cashpilot-live-ea` and
  `osdisk-cashpilot-live-je` are both `512 GB`, `Premium_LRS`, and `Attached`.
- Both NICs report accelerated networking and IP forwarding enabled; each has
  10 one-to-one public/private IPv4 mappings in its regional subnet.
- SSH diagnostic key was added through Azure VMAccess (no existing credential
  removed). Direct guest checks now confirm both workers and Docker are
  `active`, worker services are `enabled`, slot maps contain 10 entries, and
  `cashpilot-worker` has `LimitNOFILE=524288`. No provider containers are
  currently deployed on either clean live-test VM.
- Guest inspection confirms cloud-init status `done` with no errors on both
  VMs, `cashpilot-network-slots` active, and the sole `cashpilot-worker`
  container healthy. East Asia worker has been active since
  `2026-09-11 16:35:59 UTC`; Japan East since `2026-09-11 16:58:41 UTC`.
- External worker probes confirm TCP/8081 is reachable and `/api/health`
  returns HTTP 200 with the expected worker identity on each VM. The root route
  correctly rejects unauthenticated access with HTTP 401; TCP/8080 is closed.
- Leak-test prerequisites are present on both guests: `tcpdump`, `iptables`,
  `ip6tables`, and `nft`; Docker server version is `29.8.0`. No packet capture
  was started while no provider containers were deployed.
- Guest network baseline: UFW active on both VMs; IPv4 and IPv6 forwarding are
  enabled; Docker chains exist. UFW reports 16 rules in East Asia and 20 in
  Japan East, requiring provider-specific review before production tightening.
- Exact UFW exposure: East Asia allows `22`, `80`, `443`, `30088`, `30000:30005`,
  and `32768:65535` for TCP/UDP (IPv4/v6). Japan East additionally allows
  `1:65535` TCP/UDP (IPv4/v6). These broad ranges are temporary test exposure,
  not production policy.
- Worker runtime inspection shows both VMs currently run
  `assetforgeai/cashpilot-worker:dev` with restart policy `always`; mounts
  include persistent `/data`, `/network`, NKN agent, and Docker socket. This is
  live-test build evidence, not production-release evidence.
- Repository production compose pins `ghcr.io/assetforgeai-tech/cashpilot:1.32`
  and `ghcr.io/assetforgeai-tech/cashpilot-worker:1.32`; the Azure `:dev`
  image is isolated to live-test and must not be promoted without digest
  verification.
- Anonymous GHCR manifest check succeeds for public CashPilot worker `1.32` but
  fails for the three EarnApp candidate images (`20260912-production-candidate`)
  on all platforms. This is consistent with private package visibility; an
  authenticated pull still requires a rotated credential.
- GitHub Packages API confirms private-version metadata cannot be queried with
  the current GitHub token: endpoint returns HTTP 403 requiring `read:packages`.
  No GHCR credential was attempted or exposed.
- Runtime pin audit finds `app/earnapp_runtime.py` still selects the older
  reference digests for MacOS/iOS/Ubuntu, while the newer candidate images are
  published under `20260912-production-candidate`. Pin migration requires a
  controlled canary and digest verification; it is not applied automatically.
- Guest enrollment state confirms `.worker_id` and `.worker_key` are present on
  both workers, while the shared `.fleet_key` is absent. This is consistent with
  completed per-worker enrollment and avoids requiring the shared bootstrap key
  for ongoing heartbeats.
- Persistence contract: Docker and `cashpilot-network-slots` are enabled at
  boot; `cashpilot-worker.service` orders after `docker.service` and
  `network-online.target`. The systemd unit itself is `Restart=no`, while the
  managed worker container uses Docker `restart=always`; this distinction is
  intentional and must be covered by the reboot/failure matrix.
- Guest disk check confirms `/dev/root` exposes `495G` usable filesystem space
  on both VMs (512 GB disk after filesystem overhead), with about `490G` free;
  Docker root is `/opt/cashpilot-runtime/docker`.
- TCP/22 is reachable on the primary IP of both VMs. Azure Run Command still
  provides no bounded output, so service-level health remains unverified via
  that channel.
- Direct SSH with the locally stored test password was rejected on both VMs;
  no credential was printed or persisted. Azure VM Guest Agent remains
  `Ready`, so guest-service health requires the correct live credential or a
  working Run Command response.
- CashPilot server read-only DB query confirms worker IDs `112444` and `112494`
  are `online`, `key_confirmed=1`, with heartbeats at `2026-09-11 19:10:36` and
  `2026-09-11 19:10:45` UTC. This proves server-side enrollment, not guest
  service or provider health.

## Security/dependency recheck (2026-09-12)

- Bandit scan of `app`: 0 high-severity findings; existing medium/low findings
  remain classified for review rather than mass-suppressed.
- `pip-audit . --progress-spinner off`: no known vulnerabilities found.
- Bootstrap/CI contract subset: `41 passed, 3 skipped`.
- EarnApp/proxy focused suite: `1051 passed`.
- EarnApp MacOS/iOS runtime specs still set
  `NODE_TLS_REJECT_UNAUTHORIZED=0`; Ubuntu sets `1`. This preserves reference
  compatibility but disables upstream certificate authentication for MacOS/iOS.
  Production approval requires live proof with verification enabled or an
  explicit accepted-risk decision; proxy fail-closed rules do not mitigate MITM.

## Repository visibility recheck (2026-09-12)

- GitHub reports `assetforgeai-tech/CashPilot` as `PUBLIC`; the default branch
  is `main` and has no branch-protection policy. This is not production-ready
  for the user's requested private-repository posture; changing visibility is
  deferred until an explicit release cutover because it affects external
  access and CI behavior.
- GitHub repository authentication is available. No GHCR credential was read
  or reused during this check; the previously exposed credential remains
  invalid for further work until rotated.
- Repository Actions currently has zero configured secrets and zero variables;
  it cannot supply the missing CashPilot API key or GHCR pull credential.
- GitHub security metadata: secret scanning and push protection are enabled;
  Dependabot security updates and non-provider secret patterns are disabled;
  validity checks are disabled; `main` has no branch protection. Repository
  visibility remains `public`, so this is not the final production posture.
- GitHub currently reports 1 open CodeQL High alert (`py/clear-text-storage-sensitive-data`)
  on an old `main` commit and 1 open secret-scanning alert for a historical
  Google API key in `app/collectors/repocket.py`. Current source does not expose
  the values; production gate requires confirming revocation and resolving or
  documenting both alerts before private cutover.
- Workflow review found least-privilege `contents: read` on validation jobs;
  build/release jobs request `packages: write` and release metadata write as
  expected. `collector-live-check` references `CASHPILOT_LIVE_CREDENTIALS`,
  but repository Actions currently has no configured secret, so live collector
  validation cannot run.

## Bootstrap safety recheck (2026-09-12)

- The canonical client bootstrap was found with a hardcoded CashPilot API key
  and destructive unconditional removal of `$HOME/CashPilot`.
- The bootstrap now requires `CASHPILOT_API_KEY` from the process environment,
  refuses to overwrite a non-Git `$HOME/CashPilot`, and fast-forwards an
  existing checkout. The regression check passes.
- `bash -n` on the East Asia Ubuntu guest accepts the updated bootstrap with
  exit code 0; the script was streamed for syntax checking only and was not
  executed.
- Static recheck confirms no hardcoded API key and no unconditional
  `$HOME/CashPilot` deletion; environment guard and non-Git overwrite refusal
  are present.
- Scoped workspace scan finds no hardcoded `CASHPILOT_API_KEY="..."`
  assignment in the repository, canonical bootstrap, or Azure provisioning
  script.
- Current process environment has neither `CASHPILOT_API_KEY` nor `GHCR_TOKEN`;
  no live bootstrap or GHCR pull was attempted without explicit secret-safe
  injection.
- GHCR credential file metadata is unchanged since `2026-06-20` (40 bytes);
  rotation cannot be inferred and its content remains unread.
- Git history contains older commits that changed `CASHPILOT_API_KEY` assignment
  text. Values were not printed during this audit; any historical credential
  must be considered exposed and rotated before production.
- The bootstrap was not executed in this turn; live execution remains gated on
  injecting the API key through a secret-safe channel.
## Verification update (2026-09-12)

- Azure CLI account is authenticated to subscription `0e4b9f20-f92f-4883-a598-3251b0016d65`.
- `azure_create_vps_cli.test.ps1` passes the provisioning idempotency regression check.
- EarnApp route/collector/canary contract suite: `275 passed`.
- Full repository suite rerun: `2824 passed, 8 skipped` in `228.22s`.
- Ruff: clean. `pip-audit`: no known vulnerabilities. Bandit: `0` high-severity
  findings.
- Python `compileall`: pass. Docker CLI is unavailable on this workstation, so
  local Compose rendering remains `unverified`; deployed-worker checks are the
  authoritative path for image/runtime validation.
- Docs/Compose pin suite initially exposed a stale local `refs/fork-tags` ref;
  after fetching `v1.33.0`, the same suite passed `300 tests`. This was test
  fixture drift, not a shipped compose mismatch.
- GitHub CodeQL: historical alerts are fixed except alert `#1`
  (`py/clear-text-storage-sensitive-data`), which remains open and requires
  remediation or an explicit security-owner disposition.
- Chrome profile 40 remains `blocked`: CUA reports `Codex auth token is
  unavailable`; no authenticated UI evidence is claimed.
- Azure NSGs currently expose `AllowAllTcp` and `AllowAllUdp` from `Internet`
  on both live-test VNets. This remains temporary test-only exposure and is a
  production blocker until narrowed to required ports.
- Runtime code still pins the prior EarnApp digests (`app/earnapp_runtime.py`);
  the newer candidate digests are published but intentionally not activated
  until an authenticated canary compares behavior and identity.
- Fresh guest observation from this workstation is currently unavailable: the
  local SSH keys are not accepted by the Azure VM and Azure Run Command did not
  return bounded output. Existing guest evidence remains historical; new
  Docker/Compose/runtime claims require restoration of an approved read-only
  observation channel.

## Guest observation update (2026-09-12)

- Read-only SSH access restored with the existing local Ed25519 key.
- East Asia and Japan East: Docker `active`; `cashpilot-worker` is healthy;
  `cashpilot-network-slots.service` is enabled and exited successfully;
  root filesystem has about `490G` free.
- Worker systemd unit reports `LimitNOFILE=524288`. An interactive SSH shell
  still reports the default `ulimit -n 1024`; this is not the worker limit and
  must not be used as runtime evidence.
- No provider deployment or destructive mutation was performed.
- Direct guest runtime snapshot: both workers use `assetforgeai/cashpilot-worker:dev`,
  Docker restart policy `always`, health `healthy`, and contain `10` public-IP
  slots. Default routes are `10.41.1.1` (East Asia) and `10.42.1.1` (Japan
  East); Docker reports `14` networks on each host. API-key presence was checked
  without reading or recording its value.
- PR #297 CI completed successfully for Analyze, build (strict), Ruff, and test;
  merge remains review-gated by the protected `main` branch.
- Current GitHub token lacks `read:packages`; authenticated GHCR package listing
  is still unverified and no credential was changed.
- The operator bootstrap file at `D:\\1. WORK_true\\CashPilot\\client command
  setup script.txt` is outside this Git repository. Its local private-clone
  enhancement is not part of the reviewed PR/release until copied into a
  tracked, reviewed deployment artifact.
- The API key is currently injected into the worker container environment (value
  not recorded). This is a separate hardening opportunity, not the source of
  CodeQL alert `#1`.
- CodeQL alert `#1` points to the transient `spec.proxy` argument passed from the
  authenticated worker endpoint into `orchestrator.apply_proxy_binding_batch`.
  The proxy password is encrypted at rest in SQLite, then necessarily decrypted
  in memory to render the runtime proxy configuration. No logging of the value
  was found. The alert needs a security-owner false-positive/accepted-runtime
  disposition unless a credential-agent design replaces plaintext runtime
  configuration.
