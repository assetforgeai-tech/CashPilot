# EarnApp runtime gap audit (2026-09-05)

## 2026-09-06 fail-closed DNS correction

Live restart evidence on the six-node test-US canary showed that forcing DNS
wire traffic through an HTTP residential proxy with `CONNECT :53` caused
repeatable `queryA ECONNREFUSED` messages. The runtime eventually connected by
falling back to previously resolved service IPs, but that slow path is not a
reliable production resolver. The reference VPS resolves through the Azure host
resolver directly; that is faster, but leaks DNS outside the assigned proxy and
therefore cannot be adopted as the production contract.

The generated MacOS/iOS/Ubuntu images now include a small local DNS wire server:

- applications resolve through `127.0.0.1:53`;
- UDP and TCP DNS queries are redirected only to the local listener on `1053`;
- the listener sends RFC 8484 DNS messages to Cloudflare over HTTPS/443;
- that HTTPS socket is transparently routed through the node's existing
  redsocks path and exact leased proxy endpoint;
- direct UDP, direct DNS, IPv6 and non-proxy TCP remain fail-closed.

No account cookie, node UUID, identity profile, volume or proxy credential is
embedded in the resolver artifact. The resolver is included in each immutable
runtime manifest, so a DNS-policy change necessarily produces new per-platform
image tags. Source validation includes Node syntax checking and contract tests
for both UDP/TCP DNS redirection and the DoH-over-proxy path. Live adoption
remains limited to the six isolated canaries; protected providers are outside
this change.

## Source comparison

The external forensic bundle was compared with the current CashPilot runtime
generator and the three-platform baseline. The following items are now closed
in this branch:

| Gap | Evidence | Change |
| --- | --- | --- |
| Default Mac/iOS bundle path resolved inside `codex-scratch` | Builder resolved `codex-scratch/earnapp_new_update` | Resolve from the repository's external `earnapp_new_update` bundle and use `mac-1.660.577` explicitly |
| iOS route setup could leave duplicate redsocks/iptables state | iOS generated wrapper installed `CP_EARNAPP_IOS_REDSOCKS`, then the source entrypoint could install another route | Keep the validated generated route, clear proxy variables, and hand off to the source entrypoint without creating a second redsocks process |
| Ubuntu provenance was not pinned to the captured private image | Runtime contract used the old public digest and empty artifact hash map | Pin private GHCR digest and captured Ubuntu entrypoint hash |
| Mac source proxy route received an unresolved hostname | The source entrypoint embeds `PROXY_HOST` in an IPv4 iptables destination rule | Resolve once in the generated fail-closed wrapper and pass that pinned IPv4 into the source entrypoint |

## Retained source behavior

- Mac and iOS identity fields remain external encrypted per-node assets; no
  source profile, `BOUND_FP_*` value, cookie or proxy credential is copied.
- The source bundle's registration retry and `tunnel_init_decline` cooldown are
  preserved. The Mac source entrypoint currently clamps the decline wait to
  60-3600 seconds with a 600-second default.
- Ubuntu retains its structured proxy/registration watchdog and persistent
  UUID. The private image is only a content-addressed wrapper around that
  captured runtime.

## Known limits (not silently changed)

- `redsocks` provides TCP proxying. EarnApp runtime specs declare
  `egress_udp=none`; no generic UDP bypass is enabled.
- DNS UDP/53 is currently allowed by the fail-closed route for resolver
  operation. This is an explicit direct-DNS policy, not a zero-leak guarantee.
- Docker userspace spoofing cannot change the host kernel returned by
  `uname(2)`. `/.dockerenv` removal is only an application-visible marker
  change.
- The iOS and Mac captured VPS images are host-bound forensic images and are
  not promoted as generic images. Generic images must be built from the
  external runtime artifacts with new encrypted profiles and state volumes.

## Completed canary preparation

The private GHCR manifests were published and the corrected Ubuntu digest was
preloaded on `vps-test-us` without changing existing node volumes. Six isolated
canaries were deployed with distinct residential proxy leases, and restart
persistence was checked without changing UUIDs. Positive usage remains the only
open maturation gate; it is intentionally not treated as a reason to recreate
or rotate a node while its proxy is healthy.

## 2026-09-06 Ubuntu wrapper correction

The isolated six-node canary exposed a source-build defect in the Ubuntu lane:
the generated outer wrapper had been paired with a previously wrapped image and
therefore waited for `EARNAPP_DEVICE_ID`, while the authoritative Linux runtime
must generate and persist its UUID on first boot. The fix keeps the official
Ubuntu entrypoint as `entrypoint-original.sh`, removes only application-level
proxy environment variables, and lets the reference runtime own installation,
UUID generation, registration, and upgrade behavior.

Verification completed before publication:

- Focused EarnApp suite: `224 passed, 1 skipped`.
- Full suite: `2577 passed, 9 skipped`; the two initial compose-pin failures
  disappeared after fetching the fork tag refspec (`refs/fork-tags/*`), with no
  source change to compose files.
- Ruff check and format check passed after formatting the three changed files.
- Context manifests were generated for MacOS, iOS, and Ubuntu without secrets.
- Published immutable private GHCR tag: `20260906-ubuntu-fix`.
- Ubuntu image digest: `sha256:817e16db2fb80de2c1b5a05cc1aea29173c53fdf917689a451097bd32fbe19d0`.
- Ubuntu runtime manifest: `0bf2a0b415389164d22566350e10928a9fa42d7d49582be2ab81a1f35f303e78`.
- The corrected Ubuntu image was preloaded on `vps-test-us` under the worker
  contract tag `cashpilot/earnapp-ubuntu:asset-0bf2a0b41538`; no canary identity
  was recreated during preload.

The six canaries remain isolated. At the first snapshot their proxies were
healthy and identities were unchanged. Ubuntu devices were present, online and
not banned but still awaiting a usage delta; MacOS devices were present but
pending/offline in the account snapshot; iOS verification had not yet been
persisted. These are maturation observations, not a basis for proxy rotation.

## iOS canary timing finding

The iOS lane is slower for a different reason than initial proxy or TLS
registration. On both iOS canaries, `proxy_en0` WSS connected in about one
second and all three agent WSS sockets connected within about three seconds.
The delayed signal appears later as `agent WS ... zfin_pending: ... wait timeout`,
while the container remains running and proxy egress remains healthy. This
places the delay in post-connect agent finalization/workload admission, not in
`install_device`, DNS, or the fail-closed TCP route.

The current iOS artifact is the captured `1.617.813` runtime, whereas the MacOS
canary uses verified `1.660.577` and Ubuntu uses `1.665.73`. Both iOS identity
profiles satisfy the contract (`appid=com.brd.earnapp`, `tv_platform=ios`,
`arch=arm64`, iPhone model, iOS 18.2.1, unique serial/device UUID). The safe
policy is therefore to treat iOS as a longer maturation lane and require a
positive usage delta before changing proxy or identity; `zfin_pending` alone is
not evidence of a proxy failure.

## 2026-09-06 lifecycle root cause

The first six-node live restart exposed an operational mismatch: the server
lifecycle scheduler ran every five minutes and treated a ten-minute usage
flatline as a recreate, then escalated to proxy rotation after two same-proxy
recreates. EarnApp's reference VPS reaches country/usage after roughly
30--60 minutes, so the CashPilot policy could reset a healthy admission session
before the account backend had finished assigning workload. Scheduler logs also
showed repeated `proxy/apply`/`proxy/finalize` `409` responses while DB state was
advanced, leaving runtime, lease and server records temporarily inconsistent.

The policy is now changed in this branch:

- admission/flatline grace is 60 minutes;
- healthy-proxy flatline, offline or banned node uses an in-place main-container
  restart, preserving UUID, volume, account and lease;
- recreate is not selected by usage flatline, and proxy rotation is reserved
  for explicit unhealthy/egress-mismatch evidence;
- restart has a generation/device CAS-scoped worker endpoint;
- the existing proxy-apply/finalize reconciliation remains a separate open gate
  and must be fixed before production closeout.
