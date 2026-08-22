# NKN

> **Category:** Bandwidth Sharing | **Status:** Active (PROTECTED_DONE; direct-only)
> **Website:** [https://nkn.org](https://nkn.org)

## CashPilot contract

CashPilot runs the official `nknorg/nkn:latest` light node in direct mode. The
worker bootstrap discovers usable public IPv4 mappings and prepares one isolated
bridge/routing slot per address. The server then leases one exclusive NKN wallet
and creates one node for each ready slot, sequentially.

NKN does not use the Proxy Pool. A slot is not deployable until the bootstrap
state reports `route_ready: true`; the worker never discovers or changes host
routes during provider deployment.

## Settings

Enter one beneficiary address in **Settings -> NKN**. This address is used only
for the official balance collector. Per-node wallet JSON and passwords are
leased from the server-side NKN Wallet inventory and are never shown in the UI,
heartbeat or logs.

## Worker bootstrap

Run the canonical worker bootstrap from `client command setup script.txt` on a
new VPS. The tracked bootstrap additionally prepares:

- Docker and UFW prerequisites;
- public IPv4 slot discovery (Azure IMDS first, a single-IP fallback only when
  unambiguous);
- one Docker bridge and policy-routed SNAT mapping per slot;
- NKN TCP/UDP ports `30000-30005`;
- persistent Docker/systemd `LimitNOFILE=1048576`.

The host keeps its canonical state at `/etc/cashpilot/public-ip-slots.json`.
The bootstrap mirrors that file into the worker's persistent `/data` volume and
the standard Compose files also provide a dedicated read-only `/network`
volume. `CASHPILOT_PUBLIC_IP_SLOTS_FILE` selects the latter when present. A VPS
that has not run the slot bootstrap simply reports zero slots; its worker and
all existing providers continue to start normally.

## Runtime and resources

Each node uses:

- image `nknorg/nkn:latest`;
- a private named volume mounted at `/nkn/data`;
- the tested `config.json` keys `BeneficiaryAddr`, `beneficiaryAddr`,
  `SyncMode: light` and `PasswordFile`;
- `restart: always`, at most one CPU and 1 GiB RAM;
- one public IPv4 slot, bridge network and wallet assignment.

CashPilot does not stop an NKN node as a routine action. Use deliberate remove
for one slot; the worker verifies the wallet assignment token before removing
the container/volume, and the server releases the wallet only after worker
removal succeeds. A failed deploy retains its lease for retry. A stale worker
is reclaimed only after at least 15 minutes without heartbeat. The worker
fails closed one heartbeat earlier: after 14 minutes without a server lease
ACK it disables the container restart policy and stops the node while keeping
its identity volume. A valid assignment ACK restores `restart: always` and
resumes the same node. If the server has reclaimed the wallet, it rejects the
old assignment token and the worker removes only that label-guarded NKN
container/volume.

## Evidence and collector

The worker reports redacted local evidence. A node is online only when its
container is running and `getnodestate` reports `PERSIST_FINISHED`. The server
dashboard shows NKN total/online/offline counts. The collector reads the
beneficiary balance from the official NKN wallet JSON-RPC endpoint and reports
the unit as `NKN`.

## Current canary evidence

The approved `test-sing` canary uses worker `43406`, slot `ipv4-001`, public IP
`4.193.231.232`, wallet assignment version `3`, and a dedicated volume and
bridge. It has survived a VPS reboot without changing its container or node
identity. The authenticated beneficiary check reports `17006.09284572 NKN`.
The unchanged node reached `PERSIST_FINISHED` at RPC height `9684184` and
continued accepting blocks. Fresh worker evidence reports `running=true` and
`online=true`; Fleet reports one total NKN node, one online and zero offline.
Wallet `1` remains exclusively leased to the same worker/slot at assignment
version `3`, with container restart count `0` and no OOM event.

## Completion checklist

NKN is `PROTECTED_DONE` because the isolated canary on VPS `test-sing` proved:

1. a fresh slot receives a unique wallet lease and assignment version;
2. the exact bridge, public IP, ports, resource limits and restart policy are
   present;
3. official logs show a healthy node and `getnodestate` reaches
   `PERSIST_FINISHED`;
4. heartbeat and dashboard evidence show the node online; and
5. no protected provider was changed, and the canary's own container identity,
   volume and wallet lease stayed stable through reboot and first sync.
