"""Validate the operations inventory and export Beads issues as a task board."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

import yaml

SECRET_KEYS = {"password", "token", "secret", "private_key", "ssh_key", "api_key"}


def _walk(value, key=""):
    if isinstance(value, dict):
        for name, child in value.items():
            yield from _walk(child, name.lower())
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child, key)
    else:
        yield key, value


def _is_secret_reference(value):
    return value is None or (isinstance(value, str) and value.startswith("file:"))


def _overlap(left, right):
    return left == right or left.startswith(right.rstrip("/") + "/") or right.startswith(left.rstrip("/") + "/")


def load_inventory(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    resources = data.get("resources")
    if not isinstance(resources, list):
        raise ValueError("resources must be a list")
    for key, value in _walk(data):
        if key in SECRET_KEYS and not _is_secret_reference(value):
            raise ValueError(f"secret field {key} must use a file: reference")
    for index, resource in enumerate(resources):
        for other in resources[index + 1 :]:
            if resource.get("read_only") and other.get("read_only"):
                continue
            if _overlap(resource.get("path_scope", ""), other.get("path_scope", "")):
                raise ValueError("overlapping path_scope")
            if resource.get("resource_lock") == other.get("resource_lock"):
                raise ValueError("overlapping resource_lock")
    return data


def export_board(inventory_path: Path, output_path: Path, bd_db: str | None = None) -> None:
    inventory = load_inventory(inventory_path)
    command = [
        shutil.which("bd.exe") or shutil.which("bd") or r"C:\Users\KALINH\AppData\Local\Microsoft\WinGet\Links\bd.exe",
        "export",
    ]
    if bd_db:
        command[1:1] = ["--db", bd_db]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    issues = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        issue = json.loads(line)
        metadata = issue.get("metadata") or {}
        issues.append(
            {
                "id": issue["id"],
                "owner": issue.get("assignee") or issue.get("owner"),
                "path_scope": metadata.get("path_scope"),
                "resource_lock": metadata.get("resource_lock"),
                "dependencies": [item["depends_on_id"] for item in issue.get("dependencies", [])],
                "acceptance": issue.get("acceptance_criteria", ""),
                "evidence_path": metadata.get("evidence_path"),
                "status": issue.get("status"),
            }
        )
    board = {"schema_version": 1, "inventory": inventory["inventory_id"], "tasks": issues}
    output_path.write_text(yaml.safe_dump(board, sort_keys=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, default=Path("docs/ops/resource-inventory.yaml"))
    parser.add_argument("--output", type=Path, default=Path("docs/ops/task-board.yaml"))
    parser.add_argument("--bd-db")
    args = parser.parse_args()
    export_board(args.inventory, args.output, args.bd_db)


if __name__ == "__main__":
    main()
