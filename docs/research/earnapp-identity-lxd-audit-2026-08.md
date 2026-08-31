# EarnApp Identity and LXD Audit (2026-08-28)

> **Historical snapshot (2026-08-29): Ubuntu-only `platform_restricted`.**
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

## Ubuntu canary 5 transport investigation (2026-08-31)

The operator reported that an earlier EarnApp link failure was associated with
TLS, so TLS is now an explicit root-cause hypothesis for Ubuntu canary 5. The
scope remains one disposable node only:

- logical node `earnapp-ubuntu-canary-test-sing-5`;
- LXD guest `cashpilot-earnapp-earnapp-ubuntu-canary-test-sing-5`;
- device `sdk-node-2a7f6d1a0695feb31485a559fc6f0137`;
- account `2`, generation `1`, proxy `13746`, egress `64.52.28.108`.

Fresh read-only evidence shows that the node is `RUNNING`, both EarnApp and its
proxy service are active, the persisted UUID is unchanged, the proxy lease and
observed egress still match, and the authenticated account API contains the
exact device. It is nevertheless not closed out: the daily usage rows from
2026-08-24 through 2026-08-30 remain zero, and the status endpoint did not
return an online record for the exact UUID. Registration presence is therefore
not equivalent to online or earning state.

Chrome profile 40 independently confirms the same remote state: the dashboard
lists `sdk-node-fc6f0137`, but its country is blank and it remains at `0s`,
rate `$5`, amount `$0`. The other Ubuntu node `sdk-node-a4addc8f` is also at
`0s`, while the protected Mac/iOS rows show positive usage. This makes the
official dashboard, not local service health, the authoritative failing gate.

The generic TLS path currently succeeds through the node's assigned proxy:

- strict CA/SNI verification succeeds with TLS 1.3 for the relevant control
  endpoints;
- a strict WSS upgrade to `proxyjs.brdtnet.com` returns HTTP `101` with the
  correct `Sec-WebSocket-Accept` value;
- the current `proxyjs.brdtnet.com` SPKI is
  `LX0+nXiJHH9Ar7wi6bsnsSp+b9UwdEbZU/yIhTztnNE=`, and the current certificate
  pin document contains both that historical pin and the certificate's current
  pin;
- the guest CA bundle is installed, OpenSSL is current for the image, and the
  system clock is synchronized;
- the official Linux runtime is a native stripped ELF and has no
  `NODE_TLS_REJECT_UNAUTHORIZED` environment. That Node.js variable in the
  historical Mac/iOS Docker image is not evidence about the native Ubuntu
  binary.

This does **not** prove that every proprietary Bright SDK handshake succeeds.
The native runtime logs are binary/encrypted and no direct certificate error is
available, so an internal pinning or protocol-specific TLS failure remains a
residual uncertainty. It is not currently the leading demonstrated cause, and
TLS verification or pinning must not be disabled as a diagnostic shortcut.

Transport evidence remains incomplete and is at least as important as TLS:
proxy `13746` rejects SOCKS5 UDP ASSOCIATE with reply `7`; its persisted
`udp_ok` is unknown; the current guest firewall rejects non-DNS UDP; and the
catalog still declares `egress.udp: none`. Runtime marker names mentioning UDP
and TUN are signals to investigate, not proof that UDP is mandatory. No
eligible non-VN residential proxy in the current server-side snapshot has
verified `udp_ok=true`, so there is no evidence-backed candidate for a safe
lease rotation yet.

The sing-box reference confirms that a SOCKS outbound enables both TCP and UDP
by default and offers `udp_over_tcp`, while its Linux TUN documentation states
that the system stack translates both L3-to-L4 traffic and exposes UDP NAT
fields. CashPilot's current node-5 runtime differs from that generic capability:
it explicitly rejects non-DNS UDP and the assigned SOCKS endpoint rejects UDP
ASSOCIATE. This establishes a concrete transport mismatch to test, but still
does not establish that EarnApp requires UDP for online/usage state.

A bounded read-only UDP ASSOCIATE probe was then run against all seven known
non-VN residential candidates (`13746`, `13751`, `13754`, `13781`, `13752`,
`13768`, `13773`). Every endpoint returned SOCKS reply `7`; rotating among this
set would not test UDP capability and would add lease risk without changing the
hypothesized variable. sing-box's `udp_over_tcp` is a proprietary SagerNet
protocol that requires compatible server-side support; it cannot be assumed to
make an ordinary third-party SOCKS5 proxy carry UDP. A live UoT toggle is
therefore not an evidence-backed next step for this pool.

No release, proxy rotation, identity rewrite, LXD recreate, account change or
provider change was made during this investigation. Before any live A/B test,
the change must preserve canary 5's UUID/account/generation/volume, affect only
its proxy transport, and have a rollback to the two protected LXD snapshots.

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
2. At that snapshot MacOS/iOS remained disabled; no LXD conversion or experimental Apple-LXD
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
