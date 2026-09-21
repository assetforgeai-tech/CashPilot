import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("export_task_board", ROOT / "tools" / "export-task-board.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_inventory_rejects_plaintext_secret_values(tmp_path):
    path = tmp_path / "inventory.yaml"
    path.write_text("resources:\n  - id: worker-1\n    ssh_key: super-secret\n", encoding="utf-8")

    with pytest.raises(ValueError, match="secret"):
        MODULE.load_inventory(path)


def test_inventory_rejects_overlapping_mutable_scopes(tmp_path):
    path = tmp_path / "inventory.yaml"
    path.write_text(
        "resources:\n"
        "  - id: one\n    path_scope: app/runtime\n    resource_lock: worker-a\n"
        "  - id: two\n    path_scope: app/runtime/config\n    resource_lock: worker-b\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="path_scope"):
        MODULE.load_inventory(path)


def test_read_only_overlap_is_allowed(tmp_path):
    path = tmp_path / "inventory.yaml"
    path.write_text(
        "resources:\n"
        "  - id: one\n    path_scope: docs/ops\n    resource_lock: docs\n    read_only: true\n"
        "  - id: two\n    path_scope: docs/ops\n    resource_lock: docs\n    read_only: true\n",
        encoding="utf-8",
    )

    assert len(MODULE.load_inventory(path)["resources"]) == 2


def test_inventory_rejects_duplicate_mutable_locks(tmp_path):
    path = tmp_path / "inventory.yaml"
    path.write_text(
        "resources:\n"
        "  - id: one\n    path_scope: one\n    resource_lock: shared\n"
        "  - id: two\n    path_scope: two\n    resource_lock: shared\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="resource_lock"):
        MODULE.load_inventory(path)


def test_export_flattens_required_task_contract(tmp_path):
    inventory = tmp_path / "inventory.yaml"
    output = tmp_path / "board.yaml"
    inventory.write_text("inventory_id: test\nresources: []\n", encoding="utf-8")
    issue = {
        "id": "CP-001",
        "assignee": "operator",
        "status": "in_progress",
        "acceptance_criteria": "verified",
        "metadata": {"path_scope": "docs/ops", "resource_lock": "ops", "evidence_path": "evidence.md"},
        "dependencies": [{"depends_on_id": "CP-000"}],
    }
    completed = type("Result", (), {"stdout": json.dumps(issue)})()

    with patch.object(MODULE.subprocess, "run", return_value=completed):
        MODULE.export_board(inventory, output)

    task = MODULE.yaml.safe_load(output.read_text(encoding="utf-8"))["tasks"][0]
    assert task == {
        "id": "CP-001",
        "owner": "operator",
        "path_scope": "docs/ops",
        "resource_lock": "ops",
        "dependencies": ["CP-000"],
        "acceptance": "verified",
        "evidence_path": "evidence.md",
        "status": "in_progress",
    }
