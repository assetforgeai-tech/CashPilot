# Azure worker heartbeat latency remediation

## Defect

Both Azure workers ran 183 containers. The heartbeat path called
`orchestrator.get_status()`, which collects Docker stats and provider evidence for
every container before posting. Although the loop sleeps for 60 seconds, observed
posts were roughly four minutes apart. The server's 180-second stale threshold
therefore alternated otherwise healthy workers between online and offline.

## Change

Heartbeat inventory now uses `orchestrator.get_status_light()`. It retains fresh
container identity and running-state data without the expensive stats scan. The
existing heavy status path remains available to the background metrics/status
refresh and was not removed.

## Verification

- PR `#417` merged after test, CodeQL, documentation build, and Ruff checks passed.
- Release `v1.53.8` completed successfully and rebuilt both UI and worker images.
- Both Azure workers were upgraded while preserving `/data`, worker ID, worker
  key, and all provider container IDs.
- Worker logs recorded consecutive successful heartbeat POSTs after the rollout.
- Server authority reported workers `118903` and `118904` online, each with
  version and reference version `1.53.8`, and `183/183` running containers.

## Remaining gate

NKN assignment ACK timeout warnings remain on worker `118904`. This heartbeat fix
does not adopt, delete, recreate, or otherwise mutate NKN identity state.
