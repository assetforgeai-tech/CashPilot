# NKN

> **Category:** Bandwidth Sharing | **Status:** Active (PROTECTED_DONE; direct-only)
> **Website:** [https://nkn.org](https://nkn.org)

## CashPilot contract

CashPilot runs the official `nknorg/nkn:latest` light node in direct mode. The
worker bootstrap discovers usable public IPv4 mappings and prepares one isolated
bridge/routing slot per address. The server then leases one exclusive NKN wallet
and creates one node for each ready slot, sequentially. New direct nodes run in
an NKN-only LXD instance; the official Docker node remains inside that instance
so the LXD boundary, rather than an application hint, enforces the resource
limit.

NKN does not use the Proxy Pool. A slot is not deployable until the bootstrap
state reports `route_ready: true`; the worker never discovers or changes host
routes during provider deployment.

## Settings

Enter one beneficiary address in **Settings -> NKN**. This address is used only
for the official balance collector. Per-node wallet JSON and passwords are
leased from the server-side NKN Wallet inventory and are never shown in the UI,
heartbeat or logs.

The same Settings group is authoritative for new LXD nodes: `nkn_lxd_cpu`
controls the integer CPU limit and `nkn_lxd_memory_mib` controls the hard memory
limit in MiB. The shipped defaults are `1` CPU and `1024` MiB.

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
- persistent NKN data mounted at `/nkn/data` (the adopted canary retained its
  original data volume and node identity);
- the tested `config.json` keys `BeneficiaryAddr`, `beneficiaryAddr`,
  `SyncMode: light` and `PasswordFile`;
- `restart: always` for the inner Docker node;
- hard LXD limits from **Settings -> NKN** (`nkn_lxd_cpu` and
  `nkn_lxd_memory_mib`, default `1 CPU / 1024 MiB`), with swap disabled;
- one public IPv4 slot, bridge network and wallet assignment.

Settings are authoritative for future NKN LXD creation/adoption payloads. Saving
new values does not resize an already-running instance; a deliberate recreate
is required to apply a changed limit. The server keeps ordinary deploy requests
at a 60-second worker timeout, while the guarded pre-provisioned canary adoption
uses a 900-second timeout so LXD image/bootstrap work can finish without being
misclassified as a failed lease.

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

## ChainDB snapshot acceleration

ChainDB snapshots are an optional acceleration path for **new NKN nodes**. The
publisher on the dedicated publisher VPS performs a clean stop/archive/start
cycle, uploads an immutable `ChainDB/`-only `tar.zst` object to a private R2
prefix, verifies its digest and size, and publishes `latest.json` last. The
worker receives only a short-lived presigned URL and validates the manifest,
age, archive paths and SHA-256 before restoring into staging.

The restore never replaces `config.json`, `wallet.json`, `wallet.pswd`,
`ChainDB.config`, the LXD instance identity or the wallet lease. It atomically
swaps only `ChainDB/` after the node is stopped and keeps a timestamped backup
for rollback. If R2, download, checksum, extraction or post-restore evidence
fails, the worker reports a redacted `fallback`/`failed` status and starts the
ordinary NKN ChainDB sync; snapshot failure must not block another provider or
the worker heartbeat. Existing nodes and the approved `test-sing` canary never
consume a snapshot restore path.

The publisher keeps only the configured number of immutable snapshots and
removes its temporary local archive after a successful publication. R2
credentials, SSH credentials, wallet material and presigned URLs are not put
in logs, manifests, worker state or documentation. Before enabling the
publisher, verify the private bucket/prefix, disk headroom, pinned SSH host-key
fingerprint and a dedicated publisher wallet reservation. An abandoned
reservation can be released only through the owner-only guarded action that
requires explicit `RELEASE` confirmation and acknowledgement that remote state
is unknown.

## Current canary evidence

The approved `test-sing` canary uses worker `43406`, slot `ipv4-001`, public IP
`4.193.231.232`, wallet assignment version `3`, and a dedicated volume and
bridge. It has survived a VPS reboot without changing its container or node
identity. The authenticated beneficiary check reports `17006.09284572 NKN`.
The unchanged node reached `PERSIST_FINISHED` at RPC height `9684184` and
continued accepting blocks. Fresh worker evidence reports `running=true` and
`online=true`; Fleet reports one total NKN node, one online and zero offline.
After the LXD adoption and the `v1.5.1` server patch, the same node still
reports Node ID `2c58f11ddb37bd4c8e1bf16804bf19bd719038340afee0ea8ab373eed13604c2`,
RPC `PERSIST_FINISHED`, LXD `1 CPU / 1 GiB` hard limits, and the pinned inner
image digest
`nknorg/nkn@sha256:9a96013030545d71bdacee29922bb412a01bb71325ce246c36fb13623dfed07a`.
The server UI runs release `v1.5.1` at digest
`sha256:08c69e606a9fdca18edb1479e9b229e04c8d2f6915d0d3779cb028c806cd4bf5`.
Wallet `1` remains exclusively leased to the same worker/slot at assignment
version `3`, with the inner container restart policy `always` and no OOM event.

The lease guard was exercised with the exact CAS tuple: the worker suspended the
LXD node without deleting its volume, a successful heartbeat ACK resumed it, and
the node returned to `PERSIST_FINISHED`. The wallet remained `LEASED` at version
`3`; the legacy Docker container was not started and remains stopped.

## Completion checklist

NKN is `PROTECTED_DONE` because the isolated canary on VPS `test-sing` proved:

1. a fresh slot receives a unique wallet lease and assignment version;
2. the exact bridge, public IP, ports, resource limits and restart policy are
   present;
3. official logs show a healthy node and `getnodestate` reaches
   `PERSIST_FINISHED`;
4. heartbeat and dashboard evidence show the node online; and
5. no protected provider was changed, and the canary's own container identity,
   volume and wallet lease stayed stable through reboot, first sync, guarded
   suspend/resume and the server-only `v1.5.1` upgrade.
