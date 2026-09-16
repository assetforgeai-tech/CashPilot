# Spide live runtime recheck (2026-09-16)

Read-only recheck after the `v1.53.16` rollout. No provider, proxy, device,
or credential state was changed.

## Runtime

- Azure workers checked: `118903` and `118904`.
- Sampled proxy containers on both workers emitted recurring `Status: OK`.
- Sampled executable SHA-256 on both workers:
  `04f31522cbdb03b3d11e5293a3a18c6e910aed11b6d8b431b560bc7cb4ed08e5`.
- Persistent machine-id files differed between sampled containers, confirming
  the runtime volume is not sharing one machine identity.

## Provider API

- Server-side Spide login returned HTTP `200`.
- Authenticated device-list request returned HTTP `200` with a JSON payload.
- A fresh local log probe did not find a `Device key` in the retained tail;
  this is expected for already-running containers because the CLI emits the
  key during startup and then emits status lines. It is not evidence of a
  failed registration.

## Boundary result

The node still executes only the official CLI. Registration and any dashboard
collection remain server-side. The historical fresh-registration evidence
proves the key-registration path; this recheck proves current runtime liveness
and artifact parity. A provider HTTP `500` request/response body remains
unobserved and therefore remains an open diagnostic gate.
