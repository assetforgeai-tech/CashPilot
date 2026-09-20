# EarnApp disposable rotation evidence — 2026-09-19

Scope: worker `118904` only. No production node was rotated.

## Policy gate

- Proxy pool: residential VN-only.
- Eligible EarnApp platforms: `macos`, `ios`.
- Ubuntu requires a non-VN residential endpoint and is rejected otherwise.
- Sticky egress ownership is enforced during both candidate lookup and
  reservation; an egress owned by another account is not reusable.

## Rotation-12

- Disposable node: `earnapp-disposable-w118904-rotation-12`.
- Account: `470`.
- Initial proxy: `12931`.
- Initial device: `sdk-mac-9a9a195c954ad054004c2b09be5dd35d`.
- Fault injection: exactly `3` unhealthy samples, `direct_fallback_blocked=true`.
- Worker promotion: generation `1`/proxy `12931` to generation `2`/proxy `12940`,
  fresh device `sdk-mac-80dbb832865cd34d9753a8aadc49df59`.
- Replacement transaction was consumed; runtime removal used the normal Worker
  API. Node returned to `PLANNED`; provider-instance row removed; no active
  replacement transaction remained.
- Authenticated workload verification was negative/unverified. This evidence
  proves orchestration, not provider dashboard online state or earnings.

## Safety

- UI source/image parity was checked after a stale source missing
  `app/earnapp_policy.py` caused one crash-loop; synchronized build became
  healthy with restart count `0`.
- Disposable `rotation-11` stale provider-instance state was removed through
  `remove_provider_instance`; no production runtime or lease was touched.
## Cleanup follow-up (2026-09-20)

- Worker `118904` restarted without touching provider containers; image health returned `healthy`, restart count `0`.
- Direct Worker API initially returned `404 EarnApp node state not found` for rotations 11/12 because promotion left disposable runtime state absent/staged.
- Added disposable-only CAS fallback for missing authority and staged-marker cleanup through the normal Worker API/orchestrator path.
- Rotation 12 cleanup: HTTP 200, `main_present=false`, `sidecar_present=false`.
- Rotation 11 had a canonical-name container retaining `cashpilot.earnapp.stage_slug`; staged cleanup removed it through `/api/earnapp/docker-nodes/{stage_slug}/stage`, HTTP 200.
- After the next authenticated heartbeat: worker `118904` online; both disposable slugs absent from reported inventory; DB rows `PLANNED`, no active worker/proxy binding.
- Production provider containers were not mutated.

## Read-only reconciliation follow-up (2026-09-20)

- UI container `cashpilot-ui` and worker `cashpilot-worker` both reported
  `healthy`; worker restart count was `0` at inspection.
- Authenticated `GET /api/admin/earnapp/reconciliation` returned
  `untracked_on_worker: []` and `missing_from_worker: []` for workers
  `118903` and `118904`.
- Worker `118904` reported `10/10` EarnApp instances online, all active, with
  healthy proxy state. The controlled target
  `earnapp-proxy-w118904-ipv4-003` retained proxy `12970`, matching observed
  and expected egress `116.98.181.156`.
- Disposable rotation slugs `earnapp-disposable-w118904-rotation-11` and
  `earnapp-disposable-w118904-rotation-12` were absent from both DB/worker
  reconciliation and worker inventory. No live production instance was
  restarted, rotated, recreated, or deleted by this read-only check.

## Rotation-13 controlled fault path (2026-09-20)

- Disposable macOS/VN node `earnapp-disposable-w118904-rotation-13` deployed
  on worker `118904` with account `2`, initial device
  `sdk-mac-c4625ed226ca554a2330d82b314ac06d`, proxy `12942`.
- Deterministic fault injection recorded exactly `3` unhealthy samples with
  `direct_fallback_blocked=true`. Normal authenticated workload verification
  correctly rejected the staged replacement and removed the stage through the
  Worker API; no production runtime changed.
- A second run used the explicitly scoped disposable-only
  `assume_account_side_effects` test flag. The real staged path then completed:
  stage deploy HTTP 200, old disposable runtime removal HTTP 200, promotion
  HTTP 200, replacement device `sdk-mac-c00bf9914819ce18c61b8973761e1dca`,
  generation `1 -> 2`, proxy `12942 -> 12949`.
- Cleanup through the normal UI/Worker API returned
  `main_present=false`, `sidecar_present=false`. The logical row is now
  `PLANNED`, unassigned, with no active proxy lease. Production nodes were not
  mutated.

## Orphan-cleanup worker patch (2026-09-20)

- Worker `118904` initially still had the promoted disposable container
  `cashpilot-earnapp-disposable-w118904-rotation-13` despite the previous
  cleanup acknowledgement. This reproduced the stage-marker cleanup bug.
- Published immutable worker image
  `ghcr.io/assetforgeai-tech/cashpilot-worker:earnapp-orphan-cleanup-20260922`
  at digest
  `sha256:0d8bb3892c3be054bc31644e92b25b9fbcf0de0686025a20882868a682442007`.
- Replaced only the worker container on `cashpilot-live-je` / worker `118904`;
  provider containers, identity volumes, and fleet data were preserved.
- Post-deploy worker is `healthy`, restart count `0`, and the orphan container
  is physically absent. Direct worker-side cleanup returned
  `main_present=false`, `sidecar_present=false`.

## Rotation-15 controlled fault path (2026-09-20)

- Disposable macOS/VN node deployed on worker `118904` with account `2`,
  device `sdk-mac-24cddcd3303607139539aadb95e1c3fb`, generation `1`, and proxy
  `12829`.
- Deterministic injection recorded exactly `3` unhealthy samples with
  `direct_fallback_blocked=true`; the real rotation path returned
  `rotation_requested=true`.
- Durable transaction completed through stage, assumed workload verification,
  old-runtime deletion, promotion, and CAS commit. Final state was generation
  `2`, device `sdk-mac-3864d21866f94ebdc88f18ad516b8602`, proxy `12942`, with no
  replacement transaction remaining.
- Promoted runtime was running with the current Mac asset
  `cashpilot/earnapp-mac-canary:asset-fd2fbbe2ff45`; old runtime was absent.
- Disposable node was removed through the normal server API
  `/api/remove/{slug}`. Database returned the row to `PLANNED`; no production
  node or account was touched.
- Local verification after the cleanup fix: focused EarnApp/proxy suites
  `357 passed`; full suite `3396 passed, 7 skipped`.

## Disposable transport/watchdog proof (2026-09-20)

- Disposable node `earnapp-disposable-w118904-rotation-16` used the same Mac/VN
  runtime contract. Egress was `116.98.238.126`, matching its leased proxy.
- Runtime processes included `redsocks`, local DoH forwarder, and EarnApp.
  `/etc/resolv.conf` pointed to `127.0.0.1`; DNS queries resolved through the
  local forwarder. IPv4 `curl` succeeded through proxy; IPv6 curl failed.
- Firewall evidence: `CP_EARNAPP_OUT` allowed loopback/established traffic and
  the pinned proxy endpoint, then terminal `DROP`; `CP_EARNAPP6_OUT` had a
  terminal `DROP`. Non-DNS UDP was not permitted by the route policy.
- Killing `redsocks` caused the supervisor to restart the container; after
  recovery `restart_count=1`, `redsocks`, DoH, EarnApp, and the firewall chain
  returned. The disposable node was then removed through the normal API.

## Disposable authenticated verification attempt (2026-09-20)

- `earnapp-disposable-w118904-rotation-17` used the VN-only policy correctly:
  macOS, account `2`, proxy `12829`, expected/observed egress
  `14.176.185.140`. The server row and provider instance were healthy before
  verification; no Ubuntu allocation was involved.
- Serialized account operation completed (`link_verify`, `DONE`, 3 attempts),
  and EarnApp API calls returned HTTP 200 for XSRF, user data, devices, link,
  status, and usage. The authenticated workload gate still returned HTTP 409
  `EarnApp canary authenticated workload is not verified` because the exact
  device had no observed online/usage evidence in the collector snapshot.
- This is an authenticated dashboard/workload evidence failure, not a proxy
  policy or route leak. No retry hammering or production mutation was done.
- Cleanup used the normal remove API and returned the logical node to
  `PLANNED`; provider instance and proxy reservation were removed. Worker
  `118904` remained online. Reconciliation briefly showed the worker reporting
  the removed slug while its DB inventory was already clean, then converged to
  `missing_from_worker=[]` and `untracked_on_worker=[]`; no active lease
  remained. This is cleanup evidence, not a successful authenticated rotation.

## Disposable rotation-19 authenticated transport gate (2026-09-20)

- Created macOS/VN disposable on worker `118904` under account-scoped queue. Initial device was online after link, but `usage=0` and `Earnings update in` remained non-zero; normal verification correctly stayed pending.
- Deterministic fault injection recorded `3/3` unhealthy samples with `direct_fallback_blocked=true`. The real staged rotation path promoted generation `1 -> 2`, device `sdk-mac-3d0b9fc77b2ce1918278518775f2ad76 -> sdk-mac-56c613774b33c73b26e717cb88a04a3f`, proxy `12829 -> 12942`, and egress `116.98.238.126` matched the new proxy.
- The disposable-only `assume_account_side_effects` flag was used; this is orchestration evidence, not authenticated EarnApp workload evidence. No production node was touched.
- Removed through the normal API after promotion; runtime and lease cleanup completed. Authenticated workload proof remains pending until a disposable reaches the Earnings update boundary with usage evidence.

## Regression and iOS workload gate (2026-09-20)

- Focused EarnApp suites: `321 passed`.
- Full regression suite: `3396 passed, 7 skipped`.
- Disposable iOS/VN canary `earnapp-disposable-w118904-rotation-20` deployed on worker `118904`; serialized link operation completed, device online, usage currently zero while the account Earnings update countdown is still active.
- Workload verification remains pending by design; polling is rate-limited to one collector snapshot per minute. No production node is touched.

## iOS earnings-cycle and restart policy (2026-09-20)

- iOS/VN disposable node `earnapp-disposable-w118904-rotation-20` remained online with matching egress `14.176.185.115`, but usage, earnings, and uptime stayed zero through the Earnings counter reset.
- The agreed policy was exercised: one normal restart through `/api/services/{slug}/restart`, preserving generation `1`, device ID, account, and proxy. No recreate was used.
- After restart, the counter restarted at approximately one hour and metrics remained zero during the short observation window. This confirms restart routing and identity preservation, but does not prove workload.
- Disposable cleanup completed through normal API; no production node or lease was touched. Authenticated usage evidence remains an open gate.

## Rotation-21 and cleanup reconciliation (2026-09-20)

- Disposable macOS/VN node reached authenticated online state, but no usage before the Earnings cycle; its proxy probe became unhealthy and collector still showed online, demonstrating why one probe must not trigger rotation.
- Deterministic fault injection then supplied exactly `3/3` unhealthy samples. Staged rotation promoted generation `1 -> 2`, device `sdk-mac-52dbb604a38a8d3909b24db0b08cf63e -> sdk-mac-384af14aeb3298d0902aa2b6f2c724bc`, proxy `12829 -> 12942`, and egress target `116.98.238.126`.
- The disposable assumption flag was explicit; no authenticated earnings claim was made. Cleanup used normal API and worker `118904` reconciliation converged to zero missing/untracked instances.

## Production-vs-disposable collector comparison (2026-09-20)

- Read-only account comparison confirms the collector itself works: account `470` production devices return online, VN IPs, positive `uptime`/`earned_total`.
- Disposable macOS/iOS devices return online but empty IP/country and zero uptime/earnings. This isolates the remaining gate to disposable runtime-to-EarnApp workload propagation, not account authentication or collector parsing.
- No production route, proxy lease, or device was mutated during this comparison.

## Runtime artifact comparison (2026-09-20)

- Read-only DB/spec comparison found successful production worker `118904` nodes using `cashpilot/earnapp-ios:asset-28b1be5d6668` and `cashpilot/earnapp-mac-canary:asset-02dc8060a352`.
- Disposable canaries use the current verified contract `asset-fd2fbbe2ff45` (macOS) / current iOS manifest. Their dashboard rows are online but have empty IP/country and zero workload.
- This is an artifact/runtime-contract divergence requiring isolated canary validation. No production image, node, or lease was changed.

## Runtime authority cross-check (2026-09-20)

- Read-only Worker API authority for production usage nodes shows the runtime contract and DB egress can diverge from the dashboard-collected device IP (for example macOS node `earnapp-proxy-w118904-ipv4-008`: expected `14.243.215.202`, observed runtime `113.176.235.51`, while dashboard has positive earnings).
- Therefore dashboard workload success alone cannot certify CashPilot egress metadata; the canary gate correctly remains strict. Artifact A/B must compare image behavior and separately reconcile runtime egress before any rollout.
## Current proxy-pool platform policy (2026-09-20)

- CashPilot currently has VN residential proxies only; EarnApp enables only
  `macos` and `ios` for that country.
- Ubuntu is unscheduled until eligible non-VN residential inventory exists;
  its absence is expected, not a deployment failure.
- The planner consumes the persisted country/OS selection and rejects
  platform-country mismatches; it does not infer Ubuntu from IPv4 capacity.
- Focused policy/catalog regression: `188 passed`.

## Isolated production-artifact A/B guard (2026-09-20)

- Disposable Apple canaries may opt into only the historical production-proven
  macOS image `cashpilot/earnapp-mac-canary:asset-02dc8060a352` or iOS image
  `cashpilot/earnapp-ios:asset-28b1be5d6668`.
- The override is accepted only for a slug beginning `earnapp-disposable-`;
  production slugs and arbitrary image references are rejected at the API and
  runtime validation layers.
- No worker or provider node was mutated during this guard change.
- Validation: targeted canary tests passed; combined EarnApp/canary/network
  regression passed `299` tests.
- Live A/B remains pending until worker `118904` accepts the updated server
  route and the exact allowlisted image is confirmed preloaded.
- Worker-side image-label validation now receives the image and logical slug;
  stale labels are tolerated only for the same disposable allowlist, while
  production slugs remain strict. Focused validation: `265 passed`.
- Full local regression after the A/B guard: `3401 passed, 7 skipped`.
- Read-only CashPilot authority confirms worker `118904` currently runs
  `cashpilot/earnapp-mac-canary:asset-801686a44062`; prior evidence records
  positive workload, matching egress, packet isolation, and reboot persistence
  for that artifact. It is now the preferred disposable A/B image.
- Current server authority lists ten EarnApp instances on worker `118904`;
  the existing target remains running on `asset-801686a44062`. No disposable
  instance was created during this observation.
