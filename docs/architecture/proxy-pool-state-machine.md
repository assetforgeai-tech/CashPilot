# Proxy Pool Probe State Machine

Status: CP-015A durable-state contract. This is a control-plane contract, not
a production migration instruction.

## States

Each proxy has one current state: `unknown`, `alive`, `suspect`, `dead`, or
`quarantined`. An active lease that reaches `dead` creates a separate
`rotation_pending` request; it is not a proxy health state.

## Defaults

- Probe route health every 30 seconds.
- Route-health TTL: 90 seconds. TTL is not lease ownership TTL.
- Transition to `dead` after three consecutive failed health cycles.
- Retries inside one probe cycle do not count as separate cycles.
- Page database reads at 500 rows.
- Bound the probe queue at 1,024 items; rotation has its own bounded queue.

## Transitions

| Current | Event | Next | Action |
|---|---|---|---|
| `unknown` | Successful probe | `alive` | Persist evidence and schedule next probe. |
| `alive` | First failed probe | `suspect` | Persist failure; do not rotate. |
| `suspect` | Successful probe | `alive` | Reset failure counter. |
| `suspect` | Threshold reached | `dead` | Persist transition; enqueue one request per active lease generation. |
| `dead` | Active lease exists | `rotation_pending` | Keep old lease reserved until CAS replacement succeeds. |
| `dead` | No safe replacement | `quarantined` | Keep unavailable; expose reason. |
| `dead` | Successful recovery before commit | `alive` | Cancel pending request if its generation is still current. |

`inconclusive` means the control plane, shared probe target, or DNS path could
not establish upstream health. It is not a failed health cycle and cannot mark
a proxy `dead`.

## Durable authority

`proxy_probe_results` remains append-only evidence. A compact current-state
record and a deduplicated rotation-request record are separate authorities:

- `proxy_probe_state`: state, consecutive failures/successes, probe timestamps,
  next due time, failure reason, and probe generation.
- `proxy_rotation_requests`: proxy ID, probe generation, provider/worker/
  instance ownership, state, attempts, availability time, lease token, and
  last error.

One short transaction owns each transition. Duplicate probe generations create
no duplicate request. A control-plane restart returns abandoned `running` work
to `pending`. No request may release or delete a proxy.

## Incremental rotation

The scheduler pages due rows into the bounded queue. A committed `dead`
transition immediately enqueues its deduplicated rotation request; it does not
wait for a full-pool sweep. Rotation claims use CAS, serialize per worker and
provider instance, and retry with bounded backoff. Apply ACK, observed egress,
ownership checks, and CAS commit are all required. Failure preserves the old
lease and binding.

Direct-only providers bypass this state machine's proxy-lease path. EarnApp and
Pawns/IPRoyal adapters retain their provider-specific account and allocator
policies.
