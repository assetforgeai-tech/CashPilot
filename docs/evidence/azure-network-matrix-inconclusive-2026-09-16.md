# Azure network matrix attempt (2026-09-16)

Read-only probe against workers `118903` and `118904` attempted to inspect
representative proxy namespaces for IPv4, IPv6, DNS, and default route.

Observed output for the first worker showed IPv4 and IPv6 HTTP probes blocked,
while `getent hosts example.com` resolved in most namespaces. The remote shell
payload then terminated on a CRLF parsing error before the second worker was
checked.

This result is inconclusive. It does not prove proxy leakage, proxy failure, or
DNS safety. No firewall, route, container, or provider state was changed. A
normalized LF-only probe plus packet capture is required for the production
network gate.
