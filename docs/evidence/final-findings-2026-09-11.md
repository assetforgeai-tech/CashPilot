# Final production-readiness findings — 2026-09-11

| Area | Status | Evidence / remaining action |
|---|---|---|
| Source tests and lint | fixed | Full suite `2807 passed, 8 skipped`; Ruff, compileall, diff check pass. |
| Dependency/security scan | verified | `pip-audit`: `No known vulnerabilities found`; Bandit reports `0 HIGH`; EarnApp TLS verification remediation merged. |
| PayPal Pool UI/API | verified | Release `v1.32.16`; live input/action present; API protected (`401` unauthenticated); one masked assigned destination. |
| Server control plane | verified | UI and worker healthy; DB `integrity=ok`, foreign keys `0`; worker restart count `0`. |
| EarnApp reconciliation worker `92161` | verified | Inventory confirmed; DB/runtime sets match; 3 nodes online; network reconciliation `pass`. |
| Wipter managed sidecar | verified | Main/sidecar namespace match; required capabilities; restart count `0`; traffic/PONG evidence. |
| EarnApp test-sing worker `43406` | blocked | Worker heartbeat is alive but inventory is `unverified`; version skew (`1.17.13` vs UI `1.32.16`), 18 reported instances with `7` online/`10` offline/`1` unclassified, NKN Docker exited. Host root disk was `100%`, causing `runc` failures. Requires controlled disk recovery and worker upgrade/reconciliation. |
| Chrome profile 40 sweep | blocked | Codex CUA and `agent-browser --auto-connect` cannot access the running Chrome CDP session. Requires exposing CDP safely or running the sweep manually. |
| Fleet packet/reboot leak proof | unverified | EarnApp/Wipter samples exist; complete provider matrix, UDP/WebRTC capture, IPv6/DNS/DoH, and reboot checks remain. |
| EarnApp token auto-import/refresh | unverified | Source contracts exist; authenticated Chrome extension/live expiry-refresh flow lacks evidence. |
| Non-EarnApp lifecycle/account adapters | unverified | Provider-specific adapters exist; fleet-wide live mutation/reconciliation evidence is incomplete. |
| Wipter canary migration | verified | Guarded migration completed with rollback path, preserved volume, proxy traffic, and healthy managed sidecar. |

## Release decision

Production readiness is **not closed**. The server control plane and verified
runtime paths are healthy, but blocked/unverified external-observation gates
remain. Unknown telemetry is not promoted to pass.

## Safe next actions

1. Approve bounded journal cleanup on `vps-test-sing`, then recheck Docker health.
2. Upgrade/reconcile the test-sing worker only after storage recovery, without
   deleting protected NKN data.
3. Expose Chrome profile 40 through an approved CDP session for the UI/token
   sweep.
4. Run provider-by-provider packet capture and reboot evidence before closeout.
