# EarnApp Kernel and Identity Inventory

Date: 2026-09-09

## Profile-controlled fields

The macOS and iOS identity profiles provide `uname_r`, `os_version`,
hostname, machine identity, serial, architecture, model, interface metadata,
and user-agent values. The Ubuntu profile provides machine-id, hostname,
serial, architecture, model, interface metadata, and the Ubuntu release
fields. These values are generated per node and persisted in the node state
volume; no reference node identity is copied.

## Kernel boundary

The worker and all Docker containers observe the host kernel. On
`vps-test-us`, the worker reports `Linux 6.17.0-1022-azure`. Docker userspace
profiles and deleting `/.dockerenv` do not change the value returned by the
kernel `uname(2)` syscall. The EarnApp wire payload uses the profile-controlled
fields where the binary accepts them, but the host-kernel field remains an
explicit residual. The runtime must not claim complete kernel spoofing.

## Verification rule

Runtime fidelity checks fail closed if a required profile field is missing.
Evidence from container metadata must record the residual host kernel instead
of replacing it with a fabricated value. Network egress remains validated
against the leased proxy independently of kernel metadata.
