# Finding Details

## TLS verification disabled in EarnApp qualification probe (remediated)

- Attack path: a network attacker intercepts the WSS connection and returns a
  forged `CID_SET` frame; the old client accepted it because TLS certificate
  and hostname checks were disabled.
- Impact: the forged proxy could be persisted as EarnApp-qualified and become
  eligible for provider traffic.
- Fix: `app/proxy_probe_profiles/earnapp.py` now creates a default verified
  SSL context, sets `check_hostname=True`, and requires `ssl.CERT_REQUIRED`.
- Regression: `tests/test_earnapp_proxy_probe.py` asserts both controls.
