# Contract-Test Index

Ngày lập: 2026-08-21; rà soát lại 2026-08-22. Đây là chỉ mục từ source/tests trong repo, không phải live verification.

| Subsystem | Contract/invariant | Evidence tests | Trạng thái |
|---|---|---|---|
| MYST Wallet | Exclusive lease, assignment version, stale reconciliation | `tests/test_myst_wallets_module.py`, `tests/test_worker_myst_sync.py` | Source/test evidence |
| MYST Runtime | State archive, identity persistence, direct wallet apply, registration sync | `tests/test_myst_runtime.py`, `tests/test_worker_myst_sync.py` | Source/test evidence |
| MYST Mode | Supported modes are exactly `{direct}`; proxy deploy is rejected | `tests/test_provider_modes.py`, `tests/test_deploy_modes_api.py` | Chốt direct-only |
| NKN Wallet | Exclusive per-slot wallet lease, assignment CAS/reclaim, redacted runtime evidence | `tests/test_nkn_wallet_leases.py`, `tests/test_worker_nkn_sync.py` | Source/test evidence; live canary pending |
| Proxy Pool | Proxy route/API, assignment, egress probe and lease behavior | `tests/test_proxy_routes.py`, `tests/test_proxy_egress.py`, `tests/test_proxy_sidecar_runtime.py` | Source/test evidence |
| Settings | Secret precedence, write-only credentials, deploy vs collector distinction | `tests/test_settings_contract.py`, `tests/test_configuration_reference.py`, `tests/test_deploy_credentials.py`, `tests/test_no_committed_credentials.py` | Source/test evidence |
| Fleet | Enrollment key, per-worker auth, heartbeat and stale behavior | `tests/test_fleet_key.py`, `tests/test_worker_keys.py`, `tests/test_auth.py`, `tests/test_auth_extended.py`, `scripts/fleet_staleness_check.mjs` | Source/test evidence |
| Catalog | Provider credential schema and runtime contract | `tests/test_catalog.py`, `tests/test_catalog_loader.py`, `tests/test_collector_contracts.py` | Source/test evidence |

## Gaps

- Không có test index riêng cho live MYST traffic/dashboard completion.
- Chưa có live NKN canary trên `test-sing`; cần snapshot read-only và evidence deploy riêng một slot trước khi chốt provider.
- Proxy lease-to-worker-to-exit-IP mapping cần read-only runtime snapshot.
- Fleet current worker/version/heartbeat state cần snapshot read-only.

Không dùng các khoảng trống này để tự sửa code hoặc hạ `PROTECTED_DONE` baseline.
