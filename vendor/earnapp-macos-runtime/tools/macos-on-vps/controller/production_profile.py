from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from apple_profile import OpenCoreIdentity, validate_opencore_identity


PRODUCTION_RAM = "1792M"
PRODUCTION_CPU = "2"
PRODUCTION_PICKER = "N"
EXPERIMENTAL_CPU_MODEL = "Skylake-Server-v3"
ROLLBACK_CPU_MODEL = "Skylake-Client-v4"
SERVER_DISABLED_FEATURES = (
    "avx512f",
    "avx512dq",
    "avx512cd",
    "avx512bw",
    "avx512vl",
    "clwb",
    "pku",
    "pdpe1gb",
    "xsavec",
    "xgetbv1",
    "xsaves",
)


@dataclass(frozen=True)
class CpuProfileResult:
    model: str
    disabled_features: tuple[str, ...]
    warnings: tuple[str, ...]
    qualified: bool


def validate_production_profile(*, ram: str, cpu: str, picker: str) -> None:
    expected = (PRODUCTION_RAM, PRODUCTION_CPU, PRODUCTION_PICKER)
    if (ram, cpu, picker) != expected:
        raise ValueError(
            "production profile must use RAM_SIZE=1792M, CPU_CORES=2, PICKER=N"
        )


def qualify_cpu_profile(
    model: str, disabled_features: Sequence[str]
) -> CpuProfileResult:
    disabled = tuple(sorted({str(feature).lower() for feature in disabled_features}))
    if model == ROLLBACK_CPU_MODEL:
        return CpuProfileResult(model, disabled, (), True)
    if model != EXPERIMENTAL_CPU_MODEL:
        return CpuProfileResult(model, disabled, ("unsupported_cpu_model",), False)
    missing = sorted(set(SERVER_DISABLED_FEATURES) - set(disabled))
    warnings = tuple(f"unsupported_feature:{feature}" for feature in missing)
    return CpuProfileResult(model, disabled, warnings, not warnings)


def build_instance_environment(
    *,
    identity: OpenCoreIdentity,
    image: str,
    cpu_model: str = EXPERIMENTAL_CPU_MODEL,
) -> dict[str, str]:
    validate_opencore_identity(identity)
    result = qualify_cpu_profile(cpu_model, SERVER_DISABLED_FEATURES)
    if not result.qualified:
        raise ValueError(", ".join(result.warnings))
    environment = {
        "IMAGE": image,
        "VERSION": "12",
        "MODEL": identity.model,
        "SN": identity.serial,
        "MLB": identity.mlb,
        "UUID": identity.uuid,
        "MAC": identity.mac.lower(),
        "HOST": identity.hostname,
        "CPU_MODEL": cpu_model,
        "CPU_FLAGS": ",".join(f"-{feature}" for feature in SERVER_DISABLED_FEATURES),
        "RAM_SIZE": PRODUCTION_RAM,
        "CPU_CORES": PRODUCTION_CPU,
        "VGA": "vmware",
        "AUDIO": "N",
        "ADAPTER": "virtio-net-pci",
        "DISK_TYPE": "blk",
        "DISK_SIZE": "64G",
        "DISK_FMT": "qcow2",
        "WIDTH": "1024",
        "HEIGHT": "768",
        "PICKER": PRODUCTION_PICKER,
    }
    validate_hardware_profile(environment)
    return environment


def validate_hardware_profile(environment: Mapping[str, str]) -> None:
    expected = {
        "VERSION": "12",
        "MODEL": "iMacPro1,1",
        "CPU_MODEL": EXPERIMENTAL_CPU_MODEL,
        "VGA": "vmware",
        "AUDIO": "N",
        "ADAPTER": "virtio-net-pci",
        "DISK_TYPE": "blk",
        "RAM_SIZE": PRODUCTION_RAM,
        "CPU_CORES": PRODUCTION_CPU,
        "WIDTH": "1024",
        "HEIGHT": "768",
        "PICKER": PRODUCTION_PICKER,
    }
    missing = [key for key in ("SN", "MLB", "UUID", "MAC", "HOST") if not environment.get(key)]
    if missing:
        raise ValueError(f"hardware profile is missing: {', '.join(missing)}")
    drift = [key for key, value in expected.items() if environment.get(key) != value]
    if drift:
        raise ValueError(f"hardware profile drift: {', '.join(drift)}")
    flags = {
        flag.removeprefix("-")
        for flag in str(environment.get("CPU_FLAGS", "")).split(",")
        if flag.startswith("-")
    }
    result = qualify_cpu_profile(str(environment.get("CPU_MODEL", "")), flags)
    if not result.qualified:
        raise ValueError(", ".join(result.warnings))
