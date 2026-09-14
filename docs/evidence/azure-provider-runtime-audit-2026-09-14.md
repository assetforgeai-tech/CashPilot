# Azure provider runtime audit

- Scope: only Azure workers `118903` and `118904`.
- Worker images: `v1.50.19`, healthy, restart policy `always`.
- East Asia has one Earn.fm direct runtime. It reports `running`, `restart=0`,
  network mode `cashpilot-direct-ipv4-001`, and `PidsLimit=512`; `docker stats`
  reported `508` PIDs and `21.6 MiB/128 MiB` memory. A read-only `docker exec`
  probe returned `procReady not received`, so this runtime is not production
  ready until the process/PID condition is diagnosed safely.
- Japan East PacketStream proxy plus egress sidecar reports healthy network
  reconciliation and remains unchanged.
- EarnApp Azure runtime is still absent. Dedicated deployment remains fail
  closed because the private runtime images are not pullable with the current
  GHCR credentials (`denied`).
- No test worker was used or mutated.
