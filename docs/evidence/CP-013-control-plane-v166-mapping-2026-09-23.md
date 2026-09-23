# CP-013 control-plane deployment and proxy mapping evidence - 2026-09-23

## Scope

- Control-plane CashPilot only for the UI deployment.
- No worker, provider, proxy, lease, wallet, account-pool, or Azure resource was deleted or recreated.
- Worker `cashpilot-live-ea` and `cashpilot-live-je` were not restarted by this step.

## Deployment

- Pre-deploy UI image: `cashpilot-ui:proxies-sx-collector-20260921`.
- Target release: `v1.66.0`, UI digest `sha256:2bcc9766d41cc8345547277b8f8e07a721e43760749d634691c66d4654536575`.
- Only `cashpilot-ui` was recreated.
- Worker container ID remained unchanged.
- UI status: `running`, Docker health `healthy`, restart count `0`.
- Worker status: `running`, Docker health `healthy`, restart count `0`.
- A pre-deploy compose backup was created on the control-plane host; secret values are not recorded here.

## Authoritative mapping

- The deployed read-path fix now searches scoped provider instance IDs.
- Search for `earnfm-proxy-w118904-proxy-009` returns proxy row `12832`, scoped to `earnfm`, worker `118904`, instance `earnfm-proxy-w118904-proxy-009`.
- Proxy row `12832` is generic `alive` but EarnApp `BLACKLIST`/`blocked`; no rotation or rebind was performed.
- Proxy row `12833` (`zl47148.ipv4dancu.com:24356`, egress `14.243.101.24`) is generic `alive`, EarnApp `CID_SET`/`eligible`, and has no current scoped assignment in the Proxy Pool response.
- Read-only database inspection found the historical lease for `earnfm-proxy-w118904-proxy-010` on proxy `12833` with `released_at=2026-09-20 08:32:43`; no active lease exists for that instance.

## Decision

- The worker-side timeout is consistent with a stale released assignment, not proof that proxy `12833` is dead.
- Reconciliation of the runtime/container and any new lease requires a separate explicit approval. No destructive or rebinding action was taken.
