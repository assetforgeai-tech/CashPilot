# EarnApp runtime gap audit (2026-09-05)

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

## Remaining before live canary

1. Verify the published private GHCR manifests and update deployment pins to
   their immutable digests without storing registry credentials in CashPilot.
2. Preload those digests on `vps-test-us` without changing existing nodes.
3. Canary one isolated node per OS with distinct eligible residential proxy
   leases, then verify online state, positive usage and restart persistence.
