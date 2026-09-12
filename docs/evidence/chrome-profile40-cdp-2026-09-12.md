# Chrome profile 40 CDP remediation

- Verified Chrome Local State maps `Profile 40` to `AssetForge AI` (`assetforgeai@gmail.com`).
- Created an isolated copy under the local CashPilot runtime directory.
- Started Chrome with CDP bound to `127.0.0.1:9227`; `agent-browser connect 9227` and accessibility snapshot succeeded.
- Existing Chrome process and other profiles were not terminated or modified.
- The copied profile did not contain a usable CashPilot authenticated session. No credentials, cookies, or tokens were exported or persisted.
- Provider/UI sweep remains `unverified` until the profile is authenticated in the isolated CDP session or an approved authenticated state is supplied.
