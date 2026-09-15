# Azure network matrix snapshot

Read-only snapshot captured 2026-09-15 on workers `118903` and `118904`.

## Confirmed

- Both workers: worker image `1.52.4`, running and healthy.
- Both workers: no IPv6 default route; sampled containers could not reach IPv6-only `api64.ipify.org`.
- Proxy lanes use Docker container network namespaces attached to an egress sidecar (`container:<id>`), not host networking.
- Sampled Spide and Proxies.sx proxy lanes had IPv4 egress responses and DNS resolution through the runtime path.
- No direct IPv6 fallback observed in sampled containers.

## Gaps

- Host `iptables` and `ip6tables` `OUTPUT` policy remains `ACCEPT`; host-level fail-closed is not proven.
- Some provider images do not contain `/bin/sh`, so the generic probe cannot be used for them; provider-native probes are required.
- Direct/proxy, UDP, DoH/DoT, and fallback behavior still need provider-specific probes. A single `curl` result is insufficient to claim zero leak.
