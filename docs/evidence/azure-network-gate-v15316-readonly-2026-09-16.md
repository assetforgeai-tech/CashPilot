# Azure network gate read-only probe (v1.53.16)

Captured 2026-09-16 against workers `118903` and `118904`. The probe did not
change routes, firewall rules, containers, proxy leases, or provider state.

## Host baseline

- Both workers: `cashpilot-worker:1.53.16`, `running|healthy`.
- Both workers: `285/285` managed containers running.
- Host kernel: `6.17.0-1022-azure`.
- Host `OUTPUT` policy reports `ACCEPT`; this is host-level state and does not
  prove provider-container direct egress is available or safe.
- No IPv6 default route was reported on either host.

## Proxy namespace probes

Representative proxy namespaces on both workers returned blocked IPv4/IPv6
public-IP probes. DNS resolution succeeded for most sampled namespaces and was
absent for some. The route table exposed the container `eth0` route. Results
are consistent with a sidecar/proxy network boundary but are not sufficient to
prove absence of every direct fallback, DoH/DoT path, or UDP leak.

## Gate status

This remains an `inconclusive` security result. Packet capture and
provider-aware probes are still required before claiming a no-leak guarantee.
