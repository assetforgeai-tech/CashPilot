# Consolidation Review Background

CashPilot is a FastAPI control plane and authenticated worker/Docker runtime for
provider bandwidth nodes. This review covers a divergent migration worktree
against `origin/main`; no migration code is accepted yet. Reviewers must preserve
provider/account ownership boundaries, database generation/CAS invariants, and
fail-closed proxy networking. EarnApp account-scoped sticky ownership and
serialized link operations remain separate from Pawns/IPRoyal provider-private
`ip_used` allocation; MYST/NKN are direct-only. Worker mutations require
authentication and exact current identity/assignment. Findings must have a
concrete reproducible attack or behavioral failure, not merely a missing
defense-in-depth control.
