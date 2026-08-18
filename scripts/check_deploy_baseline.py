#!/usr/bin/env python3
"""Fail fast when a deploy is not based on the approved CashPilot baseline."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_FILE = ROOT / "DEPLOY_BASELINE.json"


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main() -> int:
    baseline = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))["baseline_sha"]
    head = git("rev-parse", "--short", "HEAD")
    full_head = git("rev-parse", "HEAD")
    based_on_baseline = (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", baseline, "HEAD"],
            cwd=ROOT,
            check=False,
        ).returncode
        == 0
    )
    if based_on_baseline:
        print(f"deploy baseline ok: {baseline} <= {head}")
        print(f"deploy head: {full_head}")
        return 0
    print(f"deploy baseline mismatch: HEAD {head} is not based on {baseline}", file=sys.stderr)
    print("checkout the approved baseline branch or rebase/cherry-pick onto it before deploy", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
