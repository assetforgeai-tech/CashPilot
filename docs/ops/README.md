# Operations contracts

`resource-inventory.yaml` names owners, mutable scopes, locks, evidence paths, and secret-file references. It contains no credentials.

`task-board.yaml` is generated from Beads. Refresh it from the CP-001 worktree:

```powershell
uv run python tools/export-task-board.py --bd-db .beads/embeddeddolt
```

Only CP-001 owns these files. Production, VPS, Azure, and SSH mutation remain outside this task.
