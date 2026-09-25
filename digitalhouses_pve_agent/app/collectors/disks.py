from __future__ import annotations
import hashlib
import re


def _normalize(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return re.sub(r"_+", "_", value)


def stable_disk_id(*, wwn: str | None, serial: str | None, path: str, model: str | None, size_bytes: int | None) -> str:
    if wwn and wwn.strip():
        return "wwn_" + _normalize(wwn)
    if serial and serial.strip():
        return "serial_" + _normalize(serial)
    seed = f"{model or ''}|{size_bytes or ''}|{path}"
    return "fallback_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
