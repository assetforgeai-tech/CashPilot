from __future__ import annotations

import re
import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import uuid as uuid_module
from pathlib import Path
from pathlib import PurePosixPath
from typing import Callable, Mapping
from urllib.parse import urlparse
from urllib.request import urlopen

from apple_profile import (
    MLB_RE,
    PLACEHOLDER_MLBS,
    PLACEHOLDER_SERIALS,
    SERIAL_RE,
    identity_from_mapping,
    parse_macserial_output,
)
from identity import generate_identity, preview_identity, specialization_manifest
from production_profile import (
    build_instance_environment as build_hardware_environment,
    validate_hardware_profile,
    validate_production_profile,
)
from nvram_isolation import prepare_runtime_storage
from serial_pool import claim_smbios


INSTANCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
MAC_RE = re.compile(r"^(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
RAM_RE = re.compile(r"^[1-9][0-9]*(?:M|G)$")
IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]*$")
HOSTNAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SSH_ED25519_PUBLIC_KEY_RE = re.compile(
    r"^ssh-ed25519 [A-Za-z0-9+/]+={0,3}(?: [A-Za-z0-9._@-]+)?$"
)
SOURCE_FILENAME = os.getenv("MACOS_SOURCE_FILENAME", "monterey12-os-only-1792m-v1-20260716T153103Z.qcow2")


def validate_instance_id(instance_id: str) -> None:
    if not INSTANCE_ID_RE.fullmatch(instance_id):
        raise ValueError("instance id must contain only lowercase letters, digits, and hyphens")


def validate_instance_root(root: str) -> None:
    if (
        not root
        or any(character.isspace() or ord(character) < 32 for character in root)
        or "\\" in root
    ):
        raise ValueError("instance root must be a non-empty POSIX path without whitespace")
    path = PurePosixPath(root)
    windows_absolute = os.name == "nt" and bool(re.match(r"^[A-Za-z]:/", root))
    if (
        not (path.is_absolute() or windows_absolute)
        or any(part in {".", ".."} for part in path.parts)
    ):
        raise ValueError("instance root must be an absolute normalized POSIX path")


def instance_paths(root: str, instance_id: str) -> dict[str, str]:
    validate_instance_id(instance_id)
    validate_instance_root(root)
    instance_root = PurePosixPath(root) / instance_id
    return {
        "root": str(instance_root),
        "storage": str(instance_root / "storage"),
        "inventory": str(instance_root / "inventory"),
        "identity": str(instance_root / "identity"),
    }


def instance_runtime_coordinates(instance_id: str) -> tuple[str, int, int]:
    validate_instance_id(instance_id)
    suffix = instance_id.rsplit("-", 1)[-1]
    if not suffix.isdigit() or not 1 <= int(suffix) <= 999:
        raise ValueError("instance id must end with an ordinal from 001 to 999")
    ordinal = int(suffix)
    if len(instance_id) <= 57:
        container_name = f"macos-{instance_id}"
    else:
        digest = hashlib.sha256(instance_id.encode("ascii")).hexdigest()[:8]
        container_name = f"macos-{instance_id[:47].rstrip('-')}-{digest}"
    return container_name, 18000 + ordinal, 15900 + ordinal


def generate_smbios_with_runtime(
    runtime_image: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[str, str]:
    result = runner(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "/usr/local/bin/macserial",
            runtime_image,
            "--num",
            "1",
            "--model",
            "iMacPro1,1",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return parse_macserial_output(result.stdout, "iMacPro1,1")


def load_identity_claim(
    claim_path: Path,
    *,
    instance_id: str,
    enforce_permissions: bool | None = None,
) -> tuple[str, str]:
    validate_instance_id(instance_id)
    claim_path = Path(claim_path)
    if claim_path.is_symlink() or not claim_path.is_file():
        raise FileNotFoundError(f"identity claim file is missing or unsafe: {claim_path}")
    enforce = os.name != "nt" if enforce_permissions is None else enforce_permissions
    if enforce:
        stat = claim_path.stat()
        if stat.st_uid != 0:
            raise PermissionError("identity claim must be root-owned")
        if stat.st_mode & 0o077:
            raise PermissionError("identity claim permissions must be 0600 or stricter")
    try:
        claim = json.loads(claim_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("identity claim is unreadable or invalid JSON") from error
    if not isinstance(claim, dict):
        raise ValueError("identity claim must be a JSON object")
    serial = str(claim.get("serial") or "")
    mlb = str(claim.get("mlb") or "")
    if (
        claim.get("schema_version") != 1
        or claim.get("state") != "ALLOCATED"
        or claim.get("instance_id") != instance_id
        or claim.get("model") != "iMacPro1,1"
        or not isinstance(claim.get("claim_id"), str)
        or not claim["claim_id"]
        or not isinstance(claim.get("fleet_id"), str)
        or not claim["fleet_id"]
        or not isinstance(claim.get("host_id"), str)
        or not claim["host_id"]
        or claim.get("allocation_version") != 1
        or not SERIAL_RE.fullmatch(serial)
        or serial in PLACEHOLDER_SERIALS
        or not MLB_RE.fullmatch(mlb)
        or mlb in PLACEHOLDER_MLBS
    ):
        raise ValueError("identity claim does not match the allocated iMacPro1,1 schema")
    return serial, mlb


def select_smbios(
    runtime_image: str,
    *,
    instance_id: str,
    identity_claim_path: Path | None = None,
    serial_pool_path: Path | None = None,
    serial_claims_path: Path | None = None,
    enforce_claim_permissions: bool | None = None,
    enforce_pool_permissions: bool | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[str, str]:
    if identity_claim_path is not None and (
        serial_pool_path is not None or serial_claims_path is not None
    ):
        raise ValueError("identity claim cannot be combined with serial pool sources")
    if (serial_pool_path is None) != (serial_claims_path is None):
        raise ValueError("serial pool and claims paths must be configured together")
    if identity_claim_path is not None:
        return load_identity_claim(
            identity_claim_path,
            instance_id=instance_id,
            enforce_permissions=enforce_claim_permissions,
        )
    if serial_pool_path is not None and serial_claims_path is not None:
        return claim_smbios(
            serial_pool_path,
            serial_claims_path,
            instance_id=instance_id,
            enforce_permissions=enforce_pool_permissions,
        )
    return generate_smbios_with_runtime(runtime_image, runner=runner)


def build_instance_environment(
    *,
    image: str,
    ram: str,
    cpu: str,
    mac: str,
    uuid: str,
    hostname: str | None = None,
) -> dict[str, str]:
    if (
        not IMAGE_RE.fullmatch(image)
        or "\\" in image
        or any(part in {".", ".."} for part in image.split("/"))
    ):
        raise ValueError("image reference is not a safe Docker image reference")
    if not RAM_RE.fullmatch(ram):
        raise ValueError("RAM must be a positive integer followed by M or G")
    if not cpu.isdigit() or int(cpu) < 1:
        raise ValueError("CPU core count must be a positive integer")
    if not MAC_RE.fullmatch(mac):
        raise ValueError("MAC address must use six hexadecimal octets")
    first_octet = int(mac[:2], 16)
    if first_octet & 0x01 or not first_octet & 0x02:
        raise ValueError("MAC address must be locally administered and unicast")
    try:
        normalized_uuid = str(uuid_module.UUID(uuid))
    except (AttributeError, ValueError) as error:
        raise ValueError("UUID must be a canonical UUID") from error
    if uuid != normalized_uuid:
        raise ValueError("UUID must be lowercase canonical text")
    if hostname is not None and not HOSTNAME_RE.fullmatch(hostname):
        raise ValueError("hostname must use lowercase letters, digits, and hyphens")
    environment = {
        "IMAGE": image,
        "VERSION": os.getenv("MACOS_VERSION", "12"),
        "RAM_SIZE": ram,
        "CPU_CORES": cpu,
        "MAC": mac.lower(),
        "UUID": normalized_uuid,
        "DISK_SIZE": "64G",
        "DISK_FMT": "qcow2",
        "WIDTH": "1024",
        "HEIGHT": "768",
        "PICKER": "N",
    }
    if hostname is not None:
        environment["HOST"] = hostname
    return environment


def evaluate_preflight(
    *,
    cpu_flags: set[str],
    memory_mb: int,
    disk_free_gb: int,
    kvm_available: bool,
    docker_available: bool,
) -> list[str]:
    errors: list[str] = []
    if "avx2" not in cpu_flags:
        errors.append("missing_avx2")
    if not kvm_available:
        errors.append("missing_kvm")
    if not docker_available:
        errors.append("docker_unavailable")
    if memory_mb < 2048:
        errors.append("memory_below_2048mb")
    if disk_free_gb < 25:
        errors.append("disk_below_25gb")
    return errors


def render_compose(
    instance_root: str,
    environment: dict[str, str],
    *,
    container_name: str = "macos",
    web_port: int = 8006,
    vnc_port: int = 5900,
    base_image: str | None = None,
    backing_directory: str | None = None,
    recovery_image: str | None = None,
    custom_plist: str | None = None,
) -> str:
    validate_instance_root(instance_root)
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}", container_name):
        raise ValueError("container name is invalid")
    if not all(isinstance(port, int) and 1024 <= port <= 65535 for port in (web_port, vnc_port)):
        raise ValueError("management ports must be unprivileged TCP/UDP port numbers")
    for image_path in (base_image, recovery_image, backing_directory, custom_plist):
        if image_path is None:
            continue
        if (
            not PurePosixPath(image_path).is_absolute()
            or any(part in {".", ".."} for part in PurePosixPath(image_path).parts)
            or any(character.isspace() or ord(character) < 32 for character in image_path)
        ):
            raise ValueError("image paths must be absolute normalized POSIX paths")
    image = environment["IMAGE"]
    environment_lines = "\n".join(
        f'      {key}: "{value}"'
        for key, value in environment.items()
        if key != "IMAGE"
    )
    base_mount = f"\n      - {base_image}:/base/base.qcow2:ro" if base_image else ""
    recovery_mount = (
        f"\n      - {recovery_image}:/storage/12/base.dmg:ro"
        if recovery_image
        else ""
    )
    backing_mount = (
        f"\n      - {backing_directory}:/storage/export:ro"
        if backing_directory
        else ""
    )
    custom_plist_mount = (
        f"\n      - {custom_plist}:/custom.plist:ro" if custom_plist else ""
    )
    return f"""services:
  macos:
    image: {image}
    container_name: {container_name}
    environment:
{environment_lines}
    devices:
      - /dev/kvm
      - /dev/net/tun
    cap_add:
      - NET_ADMIN
    ports:
      - "127.0.0.1:{web_port}:8006"
      - "127.0.0.1:{vnc_port}:5900/tcp"
      - "127.0.0.1:{vnc_port}:5900/udp"
    volumes:
      - {instance_root}/storage:/storage{base_mount}{backing_mount}{recovery_mount}{custom_plist_mount}
    restart: always
    stop_grace_period: 2m
"""


def _validate_source(source_url: str, source_sha256: str) -> None:
    parsed = urlparse(source_url)
    if parsed.scheme not in {"https", "file"}:
        raise ValueError("source URL must use https or file")
    if parsed.scheme == "file" and not source_sha256:
        return
    if not SHA256_RE.fullmatch(source_sha256):
        raise ValueError("source SHA-256 must contain 64 lowercase hexadecimal characters")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_verified_image(
    source_url: str,
    destination: Path,
    source_sha256: str,
    *,
    opener: Callable[..., object] = urlopen,
) -> None:
    _validate_source(source_url, source_sha256)
    destination = Path(destination)
    if destination.exists():
        if not source_sha256 and urlparse(source_url).scheme == "file":
            return
        if _file_sha256(destination) == source_sha256:
            return
        raise FileExistsError(f"existing image has unexpected SHA-256: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    if temporary.exists():
        temporary.unlink()

    digest = hashlib.sha256()
    try:
        with opener(source_url) as response, temporary.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
            output.flush()
            os.fsync(output.fileno())
        if digest.hexdigest() != source_sha256:
            raise ValueError("downloaded image SHA-256 mismatch")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_guest_specialization_script(
    identity: Mapping[str, str], management_public_key: str
) -> str:
    instance_id = str(identity.get("instance_id", ""))
    hostname = str(identity.get("hostname", ""))
    instance_uuid = str(identity.get("uuid", ""))
    validate_instance_id(instance_id)
    if not HOSTNAME_RE.fullmatch(hostname):
        raise ValueError("identity hostname is invalid")
    try:
        if str(uuid_module.UUID(instance_uuid)) != instance_uuid:
            raise ValueError
    except (AttributeError, ValueError) as error:
        raise ValueError("identity UUID is invalid") from error
    if not SSH_ED25519_PUBLIC_KEY_RE.fullmatch(management_public_key):
        raise ValueError("management public key must be one SSH Ed25519 line")

    quoted_key = shlex.quote(management_public_key)
    quoted_hostname = shlex.quote(hostname)
    marker = json.dumps(
        {"instance_id": instance_id, "uuid": instance_uuid},
        sort_keys=True,
        separators=(",", ":"),
    )
    quoted_marker = shlex.quote(marker)
    return f"""#!/bin/bash
set -euo pipefail

test "$(id -u)" -eq 0
umask 077
install -d -m 700 -o admin -g staff /Users/admin/.ssh
printf '%s\\n' {quoted_key} > /Users/admin/.ssh/authorized_keys.new
chown admin:staff /Users/admin/.ssh/authorized_keys.new
chmod 600 /Users/admin/.ssh/authorized_keys.new
mv -f /Users/admin/.ssh/authorized_keys.new /Users/admin/.ssh/authorized_keys

scutil --set HostName {quoted_hostname}
scutil --set LocalHostName {quoted_hostname}
scutil --set ComputerName {quoted_hostname}

rm -f /etc/ssh/ssh_host_*
ssh-keygen -A
printf '%s\\n' {quoted_marker} > /var/db/macos-instance-specialized.json
chmod 600 /var/db/macos-instance-specialized.json

launchctl kickstart -k system/com.openssh.sshd >/dev/null 2>&1 || true
"""


def build_bootstrap_plan(
    *,
    root: str,
    instance_id: str,
    registry_path: Path,
    source_url: str,
    source_sha256: str,
    runtime_image: str,
    recovery_image: str | None = None,
    backing_directory: str | None = None,
    nvram_template: str | None = None,
    identity: Mapping[str, str],
) -> dict[str, object]:
    validate_instance_root(root)
    validate_instance_id(instance_id)
    _validate_source(source_url, source_sha256)
    if identity.get("instance_id") != instance_id:
        raise ValueError("identity instance id does not match the bootstrap instance")

    paths = instance_paths(root, instance_id)
    instance_root = Path(paths["root"])
    storage = instance_root / "storage"
    base = Path(backing_directory) / SOURCE_FILENAME if backing_directory else storage / "export" / SOURCE_FILENAME
    overlay = storage / "12" / "data.qcow2"
    nvram = storage / "12" / "macos_hd.vars"
    compose_path = instance_root / "compose.yml"
    manifest_path = Path(paths["inventory"]) / "specialization-manifest.json"
    management_private_key = Path(paths["identity"]) / "controller_ed25519"
    management_public_key = Path(str(management_private_key) + ".pub")
    specialization_script = Path(paths["identity"]) / "specialize-guest.sh"
    clean_identity = {
        field: str(identity[field])
        for field in (
            "instance_id",
            "model",
            "serial",
            "sn",
            "mlb",
            "uuid",
            "mac",
            "rom",
            "hostname",
            "coverage_status",
            "created_utc",
        )
        if identity.get(field)
    }
    opencore_identity = identity_from_mapping(clean_identity)
    environment = build_hardware_environment(
        identity=opencore_identity, image=runtime_image
    )
    validate_hardware_profile(environment)
    validate_production_profile(
        ram=environment["RAM_SIZE"],
        cpu=environment["CPU_CORES"],
        picker=environment["PICKER"],
    )
    container_name, web_port, vnc_port = instance_runtime_coordinates(instance_id)
    compose = render_compose(
        paths["root"],
        environment,
        container_name=container_name,
        web_port=web_port,
        vnc_port=vnc_port,
        recovery_image=recovery_image,
        backing_directory=backing_directory,
    )
    overlay_command = [
        "docker",
        "run",
        "--rm",
        "--entrypoint",
        "qemu-img",
        "-v",
        f"{storage}:/storage",
    ]
    if backing_directory:
        overlay_command.extend(["-v", f"{backing_directory}:/storage/export:ro"])
    overlay_command.extend([
        runtime_image,
        "create",
        "-f",
        "qcow2",
        "-F",
        "qcow2",
        "-b",
        f"/storage/export/{SOURCE_FILENAME}",
        "/storage/12/data.qcow2",
    ])
    return {
        "instance_id": instance_id,
        "registry_path": str(Path(registry_path)),
        "source_url": source_url,
        "source_sha256": source_sha256,
        "runtime_image": runtime_image,
        "nvram_template": nvram_template,
        "identity": clean_identity,
        "paths": {
            **paths,
            "base": str(base),
            "overlay": str(overlay),
            "nvram": str(nvram),
            "compose": str(compose_path),
            "manifest": str(manifest_path),
            "management_private_key": str(management_private_key),
            "management_public_key": str(management_public_key),
            "specialization_script": str(specialization_script),
        },
        "compose": compose,
        "overlay_command": overlay_command,
    }


def _write_atomic(path: Path, text: str) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    if temporary.exists():
        temporary.unlink()
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _copy_atomic(source: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    if temporary.exists():
        temporary.unlink()
    try:
        with source.open("rb") as input_file, temporary.open("xb") as output_file:
            shutil.copyfileobj(input_file, output_file)
            output_file.flush()
            os.fsync(output_file.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _generate_management_key(
    private_key: Path,
    instance_id: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    public_key = Path(str(private_key) + ".pub")
    if private_key.exists() or public_key.exists():
        raise FileExistsError(private_key)
    private_key.parent.mkdir(parents=True, exist_ok=True)
    runner(
        [
            "ssh-keygen",
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-C",
            f"{instance_id}-controller",
            "-f",
            str(private_key),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if not private_key.is_file() or not public_key.is_file():
        raise RuntimeError("ssh-keygen did not create the management key pair")


def apply_bootstrap_plan(
    plan: Mapping[str, object],
    *,
    dry_run: bool,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    paths = {key: Path(value) for key, value in dict(plan["paths"]).items()}
    manifest = specialization_manifest(dict(plan["identity"]))
    public_result = {
        "status": "dry_run" if dry_run else "prepared",
        "instance_id": plan["instance_id"],
        "paths": {key: str(value) for key, value in paths.items()},
        "identity": {
            "schema": 1,
            "instance_id": plan["instance_id"],
            "model": dict(plan["identity"]).get("model", "iMacPro1,1"),
            "hostname": dict(plan["identity"]).get("hostname", ""),
            "smbios": "allocated",
            "ssh_host_key_policy": "regenerate-in-guest",
        },
        "actions": [
            "download_and_verify_base",
            "create_writable_overlay",
            "generate_unique_management_client_key",
            "stage_first_boot_guest_specialization",
            "write_redacted_manifest",
            "write_localhost_only_compose",
        ],
    }
    if dry_run:
        return public_result

    if paths["compose"].exists():
        raise FileExistsError(paths["compose"])
    if paths["overlay"].exists():
        raise FileExistsError(paths["overlay"])
    for key in (
        "management_private_key",
        "management_public_key",
        "specialization_script",
    ):
        if paths[key].exists():
            raise FileExistsError(paths[key])
    paths["storage"].mkdir(parents=True, exist_ok=True)
    paths["inventory"].mkdir(parents=True, exist_ok=True)
    paths["identity"].mkdir(parents=True, exist_ok=True)
    for directory in (paths["root"], paths["storage"], paths["inventory"], paths["identity"]):
        directory.chmod(0o700)
    download_verified_image(
        str(plan["source_url"]),
        paths["base"],
        str(plan["source_sha256"]),
    )
    paths["overlay"].parent.mkdir(parents=True, exist_ok=True)
    runner(
        list(plan["overlay_command"]),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if not paths["overlay"].is_file():
        raise RuntimeError("qemu-img did not create the writable overlay")
    paths["overlay"].chmod(0o600)
    _generate_management_key(
        paths["management_private_key"], str(plan["instance_id"]), runner
    )
    management_public_key = paths["management_public_key"].read_text(
        encoding="utf-8"
    ).strip()
    specialization_script = build_guest_specialization_script(
        dict(plan["identity"]), management_public_key
    )
    if plan.get("nvram_template"):
        _copy_atomic(Path(str(plan["nvram_template"])), paths["nvram"])
        paths["nvram"].chmod(0o600)
    _write_atomic(paths["specialization_script"], specialization_script)
    paths["specialization_script"].chmod(0o700)
    _write_atomic(paths["manifest"], manifest)
    _write_atomic(paths["compose"], str(plan["compose"]))
    paths["manifest"].chmod(0o600)
    paths["compose"].chmod(0o600)
    paths["management_private_key"].chmod(0o600)
    paths["management_public_key"].chmod(0o600)
    return public_result


def host_preflight(path: str = "/") -> dict[str, object]:
    cpuinfo = Path("/proc/cpuinfo").read_text(errors="replace") if Path("/proc/cpuinfo").exists() else ""
    flags = set(re.findall(r"\b[a-z0-9_]+\b", cpuinfo.lower()))
    meminfo = Path("/proc/meminfo").read_text(errors="replace") if Path("/proc/meminfo").exists() else ""
    match = re.search(r"^MemTotal:\s+(\d+)\s+kB", meminfo, re.MULTILINE)
    memory_mb = int(match.group(1)) // 1024 if match else 0
    disk_free_gb = shutil.disk_usage(path).free // (1024**3)
    result = {
        "avx2": "avx2" in flags,
        "kvm": os.path.exists("/dev/kvm"),
        "docker": shutil.which("docker") is not None,
        "memory_mb": memory_mb,
        "disk_free_gb": disk_free_gb,
    }
    result["errors"] = evaluate_preflight(
        cpu_flags=flags,
        memory_mb=memory_mb,
        disk_free_gb=disk_free_gb,
        kvm_available=bool(result["kvm"]),
        docker_available=bool(result["docker"]),
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Preflight and render a Dockur macOS instance")
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--path", default="/")
    render = subparsers.add_parser("render")
    render.add_argument("--root", required=True)
    render.add_argument("--instance-id", required=True)
    render.add_argument("--image", required=True)
    render.add_argument("--ram", default="1792M")
    render.add_argument("--cpu", default="2")
    render.add_argument("--mac", required=True)
    render.add_argument("--uuid", required=True)
    render.add_argument("--hostname")
    render.add_argument("--output", required=True)
    bootstrap = subparsers.add_parser("bootstrap")
    bootstrap.add_argument("--root", required=True)
    bootstrap.add_argument("--instance-id", required=True)
    bootstrap.add_argument("--registry", required=True)
    bootstrap.add_argument("--source-url", required=True)
    bootstrap.add_argument("--source-sha256", required=True)
    bootstrap.add_argument("--runtime-image", default="dockurr/macos")
    bootstrap.add_argument("--recovery-image")
    bootstrap.add_argument("--backing-directory")
    bootstrap.add_argument("--nvram-template")
    bootstrap.add_argument("--preflight-path", default="/")
    bootstrap.add_argument("--serial-pool", type=Path)
    bootstrap.add_argument("--serial-claims", type=Path)
    bootstrap.add_argument("--identity-claim", type=Path)
    bootstrap.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.command == "preflight":
        result = host_preflight(args.path)
        print(json.dumps(result, sort_keys=True))
        return 0 if not result["errors"] else 1

    if args.command == "bootstrap":
        candidate = preview_identity(args.instance_id)
        if args.identity_claim is not None and (
            args.serial_pool is not None or args.serial_claims is not None
        ):
            parser.error("--identity-claim cannot be combined with --serial-pool/--serial-claims")
        if args.identity_claim is not None:
            claimed_serial, claimed_mlb = load_identity_claim(
                args.identity_claim,
                instance_id=args.instance_id,
            )
            candidate["serial"] = candidate["sn"] = claimed_serial
            candidate["mlb"] = claimed_mlb
        plan = build_bootstrap_plan(
            root=args.root,
            instance_id=args.instance_id,
            registry_path=Path(args.registry),
            source_url=args.source_url,
            source_sha256=args.source_sha256,
            runtime_image=args.runtime_image,
            recovery_image=args.recovery_image,
            backing_directory=args.backing_directory,
            nvram_template=args.nvram_template,
            identity=candidate,
        )
        preflight_result = host_preflight(args.preflight_path)
        if preflight_result["errors"]:
            print(
                json.dumps(
                    {
                        "status": "preflight_failed",
                        "preflight": preflight_result,
                        "plan": apply_bootstrap_plan(plan, dry_run=True),
                    },
                    sort_keys=True,
                )
            )
            return 1
        if not args.dry_run:
            smbios = select_smbios(
                args.runtime_image,
                instance_id=args.instance_id,
                identity_claim_path=args.identity_claim,
                serial_pool_path=args.serial_pool,
                serial_claims_path=args.serial_claims,
            )
            identity = generate_identity(
                args.instance_id,
                Path(args.registry),
                smbios,
                reuse_existing=True,
            )
            plan = build_bootstrap_plan(
                root=args.root,
                instance_id=args.instance_id,
                registry_path=Path(args.registry),
                source_url=args.source_url,
                source_sha256=args.source_sha256,
                runtime_image=args.runtime_image,
                recovery_image=args.recovery_image,
                backing_directory=args.backing_directory,
                nvram_template=args.nvram_template,
                identity=identity,
            )
        result = apply_bootstrap_plan(plan, dry_run=args.dry_run)
        result["preflight"] = preflight_result
        print(json.dumps(result, sort_keys=True))
        return 0

    validate_instance_id(args.instance_id)
    paths = instance_paths(args.root, args.instance_id)
    environment = build_instance_environment(
        image=args.image,
        ram=args.ram,
        cpu=args.cpu,
        mac=args.mac,
        uuid=args.uuid,
        hostname=args.hostname,
    )
    validate_production_profile(
        ram=environment["RAM_SIZE"],
        cpu=environment["CPU_CORES"],
        picker=environment["PICKER"],
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_compose(paths["root"], environment), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
