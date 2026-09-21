# Phase 7 Verification Evidence — 2026-09-21

## Local gate

- Initial full pytest: `3346 passed, 7 skipped`; final full pytest after evidence
  updates: `3348 passed, 7 skipped`.
- Ruff: `All checks passed!`.
- `python -m compileall -q app tests`: passed.
- `git diff --check`: passed.
- Deploy baseline: `40834f6 <= cf8229c3`; integration HEAD remains `cf8229c31e39d66e855b83ab671253b9429bdd71`.
- Windows host has no Docker CLI/Desktop, Podman or WSL distribution. A clean 1.6 MB source bundle (SHA-256 `4386b2e0ccf1ce6fdbe468cfe4b04de2839a52f3bd0361e6017d9bbd54738f49`) was uploaded temporarily to allowed worker `118904`; no secrets, DBs, runtime dumps, screenshots or `.git` were included.
- Isolated remote builds succeeded without changing the worker service: UI image ID `sha256:15c994b85b1a41921da8e3fcef5662c0dbcff1f8cf85bf040e1609b844973533`, worker image ID `sha256:941e1969c97f055ee0af8ce7029e8d279225ab380281e09c0ad6546d8927f574`. Entrypoints, commands and healthchecks were inspected; `app`, `app.main`, and `app.worker_api` import smoke checks passed; image environment secret scan passed. Temporary images and source were removed.
- Runtime fidelity verifier was run and correctly failed closed because clean integration has no staged macOS/iOS/Ubuntu runtime contexts or manifests. No runtime dump was imported.

## Secret/artifact scan

- Tracked-path scan output is in `consolidation-phase-7-secret-paths-20260921.txt`; values were not copied into evidence.
- No database, cookie, credential, token, runtime identity volume, or raw provider response was imported into the integration worktree.
- `git status` remains unstaged; no commit or push.

## Disposable live gates (worker 118904 only)

- Authority sweep before canary: worker `118904` online; no `rotation-*` or `proxy-011` residue.
- Disposable `earnapp-disposable-w118904-rotation-29` deployed through authenticated normal API. Initial and repeated verification returned `409 awaiting_metric_delta`; this is an earnings timing result, not a deployment failure.
- Node tuple was read from authoritative DB: account `470`, generation `1`, proxy `12833`, observed egress matched expected egress `14.243.101.24`.
- Fault injection through normal owner API recorded `3/3` unhealthy samples, `direct_fallback_blocked=true`, and `rotation_requested=true` (`HTTP 200`).
- Cleanup through normal Worker/API path returned `HTTP 200`, `main_present=false`, `sidecar_present=false`.
- Post-cleanup authority sweep after heartbeat convergence: worker `118904` online, container count restored to `183`, no disposable residue or active `proxy-011` lease.
- Worker `118903` is offline in the authoritative snapshot and was not touched.

## Network/reboot gates

- Prior disposable packet evidence in `docs/evidence/proxy-canary-gates-2026-09-20.md` covers DNS/DoH, IPv6 block, non-DNS UDP block, direct-fallback block, watchdog, reboot persistence, staged replacement and cleanup. Fresh attributable evidence is recorded below.
- This run restarted only the `cashpilot-worker` control-plane container. It did
  not restart/recreate any production provider runtime. No production earning
  node was touched.
- A second disposable (`earnapp-disposable-w118904-rotation-30`) exercised deploy/verification/cleanup; verification returned `awaiting_metric_delta`/`error` without being promoted, cleanup returned `HTTP 200`, and the post-heartbeat authority sweep returned to 183 containers with no disposable residue.

## Gate decision

Phase 7 gate is **PASS** for the controlled disposable scope. Local tests,
isolated build/smoke/secret inspection, fresh packet/network fail-closed,
watchdog, repeated-health, staged replacement, retry/rollback, worker restart
persistence, and cleanup convergence are proven. No production earning node was
mutated. No commit, push, or worktree retirement was performed.

## Fresh disposable network attribution — 2026-09-21

- Read-only probe of the pre-existing EarnFM sample returned `probe_ok=false`;
  sidecar logs showed `connect refused` to its assigned proxy endpoint. This was
  an unhealthy upstream proxy, not a probe-tool/runtime failure.
- Disposable `earnapp-disposable-w118904-phase7c` was deployed through the normal
  API. Worker egress probe returned `running=true`, `probe_ok=true`, observed
  egress `113.189.48.88` before fault injection.
- The disposable firewall allowed only its proxy endpoint (`113.189.51.115:23359`);
  IPv6 chain defaulted to DROP. DNS redirect counters advanced (`udp/53` to
  local DoH listener), while direct HTTPS to `1.1.1.1` failed closed.
- Packet capture of the disposable showed TCP traffic only between the container
  and its proxy endpoint; no direct destination, DNS, or non-DNS UDP egress was
  observed. Proxy-side TCP payload was present, proving the route was active.
- Fault injection through the normal owner API returned HTTP 200 with `3/3`
  unhealthy samples, `direct_fallback_blocked=true`, and `rotation_requested=true`.
  The staged replacement reached generation `2`, generated a new device ID, and
  a fresh egress probe returned `116.98.228.81`.
- Cleanup returned HTTP 200 (`main_present=false`, `sidecar_present=false`). The
  post-heartbeat authority sweep converged to 183 containers, no disposable
  residue, and no active `proxy-011` lease.

The fresh disposable network, repeated-health, staged replacement, and cleanup
gates now have direct evidence.

## Fresh worker restart persistence — 2026-09-21

- Worker `118904` restarted twice without a VM reboot or provider mutation.
- `cashpilot-worker` returned `running|healthy`, image remained
  `cashpilot-phase7-worker:20260921`, restart count remained `0`.
- Managed inventory stable hash remained
  `1a3127904fe86ffeb38d36401350aa477152e914e355e388de4566d87ba5821d`, count
  `285`; no provider restart/recreate occurred.
- Disposable `earnapp-disposable-w118904-phase7d` stayed running with restart
  count `0`; post-worker-restart egress probe remained `probe_ok=true` with
  observed egress `14.245.237.153`.
- Cleanup returned HTTP `200`; the final heartbeat authority sweep converged to
  `183` containers with no `rotation-*`, `proxy-011`, or active disposable lease.

Final local verification: `3348 passed, 7 skipped`; Ruff passed; compileall
passed; `git diff --check` passed.
