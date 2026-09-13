# Ubuntu EarnApp Image Provenance

Read-only reconciliation of the legacy archive and the current CashPilot
runtime contract. No worker or VPS was changed.

## Authoritative current build

The current builder is `scripts/build_earnapp_canary_image.py` with
`--platform ubuntu`. Its source directory is the operator bundle
`earnapp_update_05092026/runtime/ubuntu`; the only source artifact is
`entrypoint.sh`, SHA-256
`b03e12ed092f8386177910b9d9d89e6189c66730472a891d67192a958a4344bc`.

The builder also generates, from tracked source:

- `cashpilot-proxy-entrypoint` SHA-256
  `7c49c7f8096b6a2f4e7d041018ddac02ea15176410279aa194961701cea690dd`;
- `cashpilot-doh.js` SHA-256
  `4ef49a23166c64511f248c4fbfa71f9a8a393cb53ecc983dacb71a8f0547de5a`.

The canonical manifest includes those three artifacts plus base image
`ghcr.io/assetforgeai-tech/cashpilot-earnapp-ubuntu@sha256:3e63d79166d493c55879635071c85da298e0d7c13f186dedcb579f9512abdc41`.
Its canonical manifest hash is `72e54b17fb3a5a7f8630ae1d79dc10abc38a8f4d6af217c74513ac1413417a04`,
therefore the local contract tag is
`cashpilot/earnapp-ubuntu:asset-72e54b17fb3a`.

Build shape:

```text
FROM <pinned private GHCR base>
apt install nodejs ca-certificates
move upstream entrypoint to entrypoint-base.sh
copy operator entrypoint + generated fail-closed proxy/DNS wrappers
label runtime contract and manifest hash
ENTRYPOINT /usr/local/bin/entrypoint.sh
```

Worker delivery remains `image_delivery=operator_preload`; registry pulls are
rejected by design. A worker must preload the exact image and validate its
labels before deployment.

## Why `ubuntu-image.tar.gz` is different

`artifacts/ubuntu-image.tar.gz` SHA-256 is
`103ad18352f4ce313096300d8e148925ba38dce11573fb0f77b4d8bd068d8b95`.
It is an OCI archive of the original upstream image
`ghcr.io/s0ckd3/earnapp-2movn:latest`, image/config digest
`sha256:19b8d5831f0e83c0beb9a514bc9ed40c0be252ac101217fc01a6e2ac4714c559`.
The archive metadata identifies source revision
`8f4240237c1339d532a3a4e169190efe059c321e` and upstream entrypoint
`/usr/local/bin/entrypoint.sh`.

It is a forensic input/evidence bundle, not the current deployable image:

- it has no CashPilot labels or generated DNS/fail-closed wrapper;
- it uses the upstream `s0ckd3/earnapp-2movn` tag and mutable `latest` provenance;
- its image digest (`19b8...`) is not the pinned private base (`3e63...`) and
  cannot produce the current contract hash (`72e54...`) without rebuilding.

The current private image is consequently a derived wrapper around the pinned
private base, not a retag of the 103ad archive. The archive remains useful for
forensics and source comparison only.

## Safe promotion path

1. Re-run the builder from the operator bundle in an empty context.
2. Run `scripts/verify_earnapp_runtime_fidelity.py` and record manifest/hash.
3. Build with `docker build --pull=false`; inspect labels, entrypoint, digest.
4. Push an immutable private GHCR tag; record returned manifest digest.
5. Preload that exact digest on a canary worker.
6. Verify identity volume, account/device labels, proxy egress, fail-closed
   chains and localhost DNS before any migration.

No UUID, account, proxy credential, identity volume or host-bound fingerprint
belongs in the image provenance.
