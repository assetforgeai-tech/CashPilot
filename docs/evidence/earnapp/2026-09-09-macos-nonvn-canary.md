# EarnApp macOS non-VN Canary — 2026-09-09

- Release deployed: `v1.23.5`.
- Fix: `country_scope=non-vn` is applied before proxy lease when macOS is enabled for both country classes.
- Worker: `92161` (`vps-test-us`).
- Existing macOS non-VN nodes `-01` and `-02` unchanged.
- Fresh node `-03`: device `sdk-mac-5a73bd21747433703f51a20a96d75230`, proxy egress `64.52.28.108`, US residential, container running.
- Fresh node `-04`: device `sdk-mac-ce6f3d6ba4c1905a73728069f3a9f1ff`, proxy egress `64.52.28.98`, US residential, container running.
- Runtime logs show EarnApp `1.660.577`, `platform=darwin`, `appid` alias, proxy tunnel connected, and no direct egress evidence.
- Dashboard collector has not yet published country/usage for the fresh nodes; canary remains pending positive usage evidence.
