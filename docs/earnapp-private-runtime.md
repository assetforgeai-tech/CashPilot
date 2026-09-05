# EarnApp Private Runtime Images

EarnApp emulation binaries are operator-owned runtime assets and must not be
checked into Git or published in a public package. The supported delivery
contract is:

1. Build the MacOS, iOS and Ubuntu runtime images on a controlled runner.
2. Push them to private GHCR packages, for example
   `ghcr.io/assetforgeai-tech/cashpilot-earnapp-macos`.
3. On each worker, authenticate once with a short-lived read-only package token
   and preload the exact digest with `docker pull`.
4. Set the runtime spec to `image_delivery=operator_preload` and use the digest,
   not `latest` or a mutable tag.
5. Remove the token from shell history and the worker after the preload. The
   CashPilot UI and worker never receive the token and never pull an EarnApp
   image from a registry.

The existing worker validation intentionally rejects registry delivery for
EarnApp. This prevents a leaked dashboard credential from becoming a private
package pull credential and keeps binary provenance tied to the operator's
verified manifest. GHCR package visibility must be changed in GitHub package
settings; a token file on the workstation is not read by application code.

## Kernel identity limitation

Docker containers share the host kernel. Environment fields such as `uname_r`
and `os_version` can control the EarnApp identity payload, but they cannot
change the value returned by the Linux `uname(2)` syscall. Therefore an Azure
host release such as `6.17.0-1022-azure` cannot be hidden by adding more JSON
identity fields or by deleting `/.dockerenv`. Hiding the kernel fingerprint
requires a separate kernel/VM boundary; CashPilot does not enable that risky
mutation automatically.

## Orphan runtimes

The server may mark a node `RECOVERABLE` after its worker heartbeat disappears.
Container presence alone is not authority. Automatic deletion is intentionally
not enabled: cleanup requires an exact match for logical node, generation,
device identity, sidecar, volume and expected egress, followed by an explicit
owner action. This prevents a stale container from deleting a still-recoverable
identity or remote EarnApp device.

## Rotation

Publish a new immutable digest, preload it on a canary worker, verify the
manifest and runtime evidence, then update the server-side runtime asset
reference. Existing containers are not bulk-redeployed because their volumes
contain device identity and registration state.
