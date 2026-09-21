# Source of Truth

`D:\1. WORK_true\CashPilot\repo` is the canonical Git directory. Git stores
the repository object database and worktree metadata there.

`D:\1. WORK_true\CashPilot\repo-spide-release-20260916` is a registered
Git worktree of that repository at branch
`fix/spide-production-closeout-20260916`; it is not an independent repository.
It remains frozen as a migration source until curated integration is accepted.

`D:\1. WORK_true\CashPilot\repo-consolidation-20260921` is the clean
integration worktree, created from `origin/main` at the start of Phase 2. No
source code from the migration worktree has been copied into it.

Source precedence during consolidation:

1. Clean integration worktree and its verified tests.
2. A reviewed, explicitly accepted migration artifact.
3. Historical worktrees/evidence.
4. Conversation history, which is context only.

No branch, worktree, folder, or remote is deleted by this document.
