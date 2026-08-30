# EarnApp Identity and LXD Audit (2026-08-28)

> **Current source status (2026-08-29): Ubuntu-only `platform_restricted`.**
> The official Linux x64 package is enabled only through CashPilot's dedicated
> Ubuntu LXD lane. MacOS/iOS emulation and all generic/raw Docker deploy paths
> remain disabled. This is a source-policy change only; no release, deployment,
> VPS mutation or live closeout was performed.

## Scope

This is a read-only audit of the CashPilot EarnApp implementation and the
authorized material under `earnapp_new_update`. It does not rewrite profiles,
restart a live node, rotate a lease, or alter another provider.

## Live finding

The two existing test-sing Mac nodes are both registered, online, and sending
heartbeats. A fresh authenticated read reports `billing=qualified_uptime` for
both, with materially different current-day workload:

- The first node has positive current-day qualified usage (about `39,422,641 ms`)
  and positive earnings, although its proxy sidecar also records repeated HTTP
  `502` responses and `zfin_pending` timeouts.
- The second node has only about `18,142 ms` current-day usage and no earnings.
  It is online and present but near a workload plateau; its route is cleaner in
  the same sample, so transport alone is not a sufficient explanation.

The evidence therefore did not establish Docker as the cause: a clean route
could remain online without receiving workload. At the time, the unresolved
boundary was between EarnApp control-plane allocation/eligibility and runtime
workload. The current policy still closes all Apple-emulation tests and does not
authorize an LXD transport change or migration of an existing Mac node. It opens
only a fresh official Ubuntu x64/LXD node through the dedicated contract.

The existing verifier also had a local measurement bug: its default window is
ten polls at fifteen seconds, but it required a `3,600,000 ms` qualified-uptime
delta. A real positive delta inside the poll window could never satisfy that
gate. The corrected contract accepts any positive monotonic delta and can use
the last persisted pending sample as the next verification baseline. The
collector does not promote a historical usage bucket into `usage_current` when
the UTC-today bucket is absent.

## Reference profile shapes

The sanitized local forensic snapshot contains 303 encrypted profiles (183
Mac and 120 iOS); all profiles decrypted successfully in memory using the
runtime envelope. No plaintext profile or credential is written by this audit.

Reference Mac `new_state` keys:

```text
battery_percentage, full_screen, full_screen_ts, idle_state,
monitor_power, power_source, session_state, user_io
```

Reference iOS fields that the current generator omitted:

```text
codename, conf_user, confdir, cp_id, device_kind, device_marketing,
device_model, gw_ip, iface_type, is_swift, mobile_type, soc
```

Reference state/value differences relevant to newly generated profiles:

- `session_state` is `logged`.
- `idle_state` is an object containing CPU and memory usage fields.
- `usage.app_bytes` is a JSON string describing the network/battery state;
  `usage.total_bytes` is an empty string in the captured profiles.
- iOS user-agent values use `earnapp/1 CFNetwork/... Darwin/...` rather than
  embedding the runtime version after `earnapp/`.
- Mac and iOS metadata are selected from small correlated model/OS/build
  catalogs, while serials, UUID-shaped values, and local-unicast MAC values
  are independently unique.

## Current generator gap

`app/earnapp_identity.py` currently emits a minimal Mac state object and a
minimal iOS profile. It generates unique device IDs and encrypted profiles,
but new iOS profiles do not yet carry the complete audited metadata shape.
The validator intentionally keeps the older wire-minimum contract so existing
persisted profiles remain readable; newly generated profiles should be
expanded without rewriting existing values.

The two live Mac profiles intentionally remain unchanged. They contain the
older minimal state shape (`full_screen`, `monitor_power`, `power_source`) and
numeric usage placeholders. Rewriting them would change encrypted profile
bytes for already-linked devices and is outside this canary scope.

## Runtime and virtualization markers

The supplied Mac/iOS artifacts are Linux amd64 ELF binaries with userspace
metadata shims. They are not genuine macOS or iOS kernels/VMs. The runtime
entrypoints currently:

- remove `/.dockerenv` during image build;
- override `uname`, `sw_vers`, `/etc/os-release`, hostname, and machine-id;
- apply a persisted tracking identity and EarnApp UUID;
- redirect outbound traffic through a redsocks/sing-box proxy path.

Removing one Docker marker does not remove kernel, cgroup, namespace, or
container evidence. This audit does not add further Docker/VM/LXD concealment
and does not claim that LXD would make the userspace binary a real Apple
device. Runtime work remains limited to isolation, lifecycle and resource
limits; anti-abuse detection bypass is out of scope.

## Current LXD boundary

The existing restricted host helper supports official Ubuntu EarnApp in LXD.
It validates a fresh Ubuntu identity, residential proxy, generation/device CAS
tuple, and 1 CPU/1024 MiB defaults. There is no verified Mac/iOS LXD artifact
or helper contract in this repository. Consequently:

1. Ubuntu is the only enabled platform and must use the dedicated LXD route.
   Generic catalog and worker Docker routes fail closed even when caller input
   claims `platform=ubuntu` and `runtime_backend=lxd`.
2. MacOS/iOS remain disabled; no LXD conversion or experimental Apple-LXD
   deploy path is part of the approved design.
3. Existing Docker-backed Mac nodes, volumes, identities, sidecars, account
   bindings, and leases are immutable during this work.

## Canary readiness (historical; no current deployment authorization)

- `test-sing` has LXD `5.21.7`, the restricted EarnApp host helper, 8 CPUs,
  32 GiB RAM and about 13 GiB free disk. The protected NKN LXD guest remains
  untouched.
- The server has one active EarnApp account already serving the two Mac nodes.
  The owner confirmed that this account has no node-count ceiling, so the new
  canaries may use the same account while retaining independent logical-node
  identities and exclusive proxy leases.
- The proxy pool has at least 20 free VN residential EarnApp-eligible egresses
  and at least 20 free non-VN residential EarnApp-eligible egresses.
- The iOS artifact bundle passes its pinned manifest check and resolves to
  `cashpilot/earnapp-ios:asset-061a2a32d69d`, but that image is not yet confirmed
  preloaded on `test-sing`.
- Ubuntu remains the only implemented and authorized LXD runtime. Mac/iOS have
  no LXD implementation or artifact path.

## Runtime closeout gates

The technical gates remain authenticated device presence, online state,
positive workload/usage delta, restart persistence, and isolated proxy
rotation. Opening the source-policy gate does not claim those live gates have
passed for Ubuntu; release, deployment and canary closeout are separate work.
