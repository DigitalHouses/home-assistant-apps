from __future__ import annotations

import re
import socket
from dataclasses import dataclass
from pathlib import Path

from .config import GeneralConfig

MACHINE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class IdentityError(ValueError):
    pass


@dataclass(frozen=True)
class HostIdentity:
    machine_id: str
    instance_id: str
    hostname: str
    node_name: str


def normalize_machine_id(raw: str) -> str:
    value = raw.strip().lower().replace("-", "")
    if not MACHINE_ID_RE.fullmatch(value):
        raise IdentityError(
            "machine_id must contain exactly 32 hexadecimal characters"
        )
    return value


def resolve_identity(
    general: GeneralConfig,
    *,
    machine_id_path: Path = Path("/etc/machine-id"),
    hostname: str | None = None,
) -> HostIdentity:
    try:
        machine_id_raw = machine_id_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise IdentityError(
            f"unable to read machine_id from {machine_id_path}"
        ) from exc

    machine_id = normalize_machine_id(machine_id_raw)
    effective_hostname = (hostname or socket.gethostname()).strip()
    if not effective_hostname:
        raise IdentityError("hostname must not be empty")

    return HostIdentity(
        machine_id=machine_id,
        instance_id=general.instance_id or machine_id,
        hostname=effective_hostname,
        node_name=general.node_name,
    )
