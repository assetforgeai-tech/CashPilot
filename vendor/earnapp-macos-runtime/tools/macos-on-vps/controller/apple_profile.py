from __future__ import annotations

import re
import uuid as uuid_module
from dataclasses import dataclass
from typing import Mapping


SERIAL_RE = re.compile(r"^[A-Z0-9]{11,12}$")
MLB_RE = re.compile(r"^[A-Z0-9]{13,17}$")
MAC_RE = re.compile(r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$")
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
PLACEHOLDER_SERIALS = {"W00000000001", "M00000000001"}
PLACEHOLDER_MLBS = {"M0000000000000001"}


@dataclass(frozen=True)
class OpenCoreIdentity:
    instance_id: str
    model: str
    serial: str
    mlb: str
    uuid: str
    mac: str
    rom: str
    hostname: str
    coverage_status: str = "not_queried"


def parse_macserial_output(text: str, model: str) -> tuple[str, str]:
    if model != "iMacPro1,1":
        raise ValueError("unsupported Monterey SMBIOS model")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if "|" not in line:
            continue
        serial, mlb = (part.strip().upper() for part in line.split("|", 1))
        if serial in PLACEHOLDER_SERIALS or mlb in PLACEHOLDER_MLBS:
            raise ValueError("macserial returned a placeholder identity")
        if SERIAL_RE.fullmatch(serial) and MLB_RE.fullmatch(mlb):
            return serial, mlb
        raise ValueError("macserial returned invalid serial or MLB format")
    raise ValueError("macserial output did not contain a serial and MLB pair")


def validate_opencore_identity(identity: OpenCoreIdentity) -> None:
    if identity.model != "iMacPro1,1":
        raise ValueError("unsupported Monterey SMBIOS model")
    if not SERIAL_RE.fullmatch(identity.serial) or identity.serial in PLACEHOLDER_SERIALS:
        raise ValueError("serial has invalid or placeholder format")
    if not MLB_RE.fullmatch(identity.mlb) or identity.mlb in PLACEHOLDER_MLBS:
        raise ValueError("MLB has invalid or placeholder format")
    if not UUID_RE.fullmatch(identity.uuid):
        raise ValueError("UUID must be lowercase canonical text")
    try:
        if str(uuid_module.UUID(identity.uuid)) != identity.uuid:
            raise ValueError
    except (AttributeError, ValueError) as error:
        raise ValueError("UUID must be lowercase canonical text") from error
    if not MAC_RE.fullmatch(identity.mac.lower()):
        raise ValueError("MAC must use six lowercase hexadecimal octets")
    if not re.fullmatch(r"[0-9a-f]{12}", identity.rom.lower()):
        raise ValueError("ROM must contain six octets")
    if identity.rom.lower() != identity.mac.replace(":", "").lower():
        raise ValueError("ROM must equal MAC without separators")
    if not identity.hostname or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", identity.hostname):
        raise ValueError("hostname is invalid")
    if identity.coverage_status != "not_queried":
        raise ValueError("Apple Coverage must remain unqueried")


def identity_from_mapping(values: Mapping[str, object]) -> OpenCoreIdentity:
    identity = OpenCoreIdentity(
        instance_id=str(values.get("instance_id", "")),
        model=str(values.get("model", "iMacPro1,1")),
        serial=str(values.get("serial", values.get("sn", ""))),
        mlb=str(values.get("mlb", "")),
        uuid=str(values.get("uuid", "")),
        mac=str(values.get("mac", "")).lower(),
        rom=str(values.get("rom", "")).lower(),
        hostname=str(values.get("hostname", "")),
        coverage_status=str(values.get("coverage_status", "not_queried")),
    )
    validate_opencore_identity(identity)
    return identity
