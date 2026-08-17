from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path


PERSISTENT_KEYS = ("qemu_uuid", "system_uuid", "io_platform_uuid", "mac", "rom")


def prepare_runtime_storage(root: Path, base_image: Path) -> dict[str, str]:
    root = Path(root)
    base_image = Path(base_image)
    if not base_image.is_file():
        raise FileNotFoundError(base_image)
    runtime_dir = root / "storage" / "12"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return {
        "root": str(root),
        "runtime_dir": str(runtime_dir),
        "base_image": str(base_image),
        "overlay": str(runtime_dir / "data.qcow2"),
        "vars": str(runtime_dir / "macos_hd.vars"),
        "rom": str(runtime_dir / "macos_hd.rom"),
        "identity_state": str(runtime_dir / "identity-state.json"),
    }


def identity_persistence_report(
    samples: Sequence[Mapping[str, str]],
) -> dict[str, object]:
    if not samples:
        return {
            "stable": False,
            "sample_count": 0,
            "changed_keys": list(PERSISTENT_KEYS),
            "hardware_uuid_required_to_match": False,
        }
    changed_keys = [
        key
        for key in PERSISTENT_KEYS
        if len({str(sample.get(key, "")) for sample in samples}) != 1
    ]
    return {
        "stable": not changed_keys,
        "sample_count": len(samples),
        "changed_keys": changed_keys,
        "hardware_uuid_required_to_match": False,
    }
