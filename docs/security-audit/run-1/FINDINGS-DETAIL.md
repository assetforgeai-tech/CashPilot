# Finding details

## MEDIUM — Forged EarnApp qualification verdict

The base probe created a TLS context with `check_hostname=False` and
`ssl.CERT_NONE` in `app/proxy_probe_profiles/earnapp.py:28-33`, then applied it
to the WSS connection at `:227-269`. Proxy credentials authenticate only the
configured proxy; they do not authenticate the upstream provider. A
proxy-side MITM could therefore fabricate a valid WebSocket handshake and
`ipc_post/cid_set` frame. `probe_earnapp_proxy` accepted that frame at
`:327-335`; `app/routers/proxies.py:1033-1055` persisted it; and
`app/database.py:4597-4617` treated the latest matching result as EarnApp
eligible when the exit IP matched. Residential/country/duplicate checks did
not authenticate the provider verdict.

The current worktree fixes the root cause with `CERT_REQUIRED` and hostname
verification, and the regression test asserts both settings. The finding is
remediated in source but requires release and live qualification recheck.
