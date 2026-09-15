# NKN helper rollout and current state

- Release `v1.53.9` passed CI and published UI/worker images.
- Host helper `cashpilot-nkn-agent.py` was installed and restarted on Azure workers `20.187.79.110` and `20.210.93.220`.
- Service status: `active` on both hosts.
- No NKN wallet, identity volume, or lease was deleted or reassigned.

## Remaining issue

Worker `118904` still reports several NKN local states as `lease_guard_suspended` with missing `last_server_ack_at`. The helper accepts a direct CAS resume for `ipv4-002`, proving the socket and assignment metadata are valid, but heartbeat ACK reconciliation still encounters per-slot `RuntimeError`, `ConnectionRefusedError`, or `FileNotFoundError` for other slots. This remains an open production gate; do not mark NKN complete or perform bulk cleanup until each error is traced to its exact slot/helper operation.
