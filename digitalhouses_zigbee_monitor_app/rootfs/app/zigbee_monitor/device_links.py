"""Read-only IEEE -> Home Assistant device ID projection.

Home Assistant owns .storage/core.device_registry. Never edit it, publish its
contents, or infer a match from mutable friendly names/entity IDs. Fail closed
when the read-only HA config mount is absent, inconsistent, or ambiguous.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Callable

HA_CONFIG = Path("/homeassistant")
MAX_BYTES = 8_000_000
IEEE = re.compile(r"^0x[0-9a-f]{16}$")
DEVICE_ID = re.compile(r"^[0-9a-f]{32}$")
PREFIX = "zigbee2mqtt_"


def load_ha_device_links(
    root: Path = HA_CONFIG,
    *,
    is_mount: Callable[[str], bool] = os.path.ismount,
) -> dict[str, str]:
    """Return only validated Zigbee2MQTT IEEE -> HA registry ID mappings.

    The private .storage format can change; failure means no navigation link,
    never an App startup failure. Identical IEEE in more than one HA device is
    ambiguous and deliberately produces no link.
    """
    try:
        if not root.is_dir() or not is_mount(str(root)):
            return {}
        directory = root / ".storage"
        if directory.is_symlink() or not directory.is_dir():
            return {}
        path = directory / "core.device_registry"
        if path.is_symlink() or not path.is_file():
            return {}
        fd = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        with os.fdopen(fd, "rb") as stream:
            blob = stream.read(MAX_BYTES + 1)
        if len(blob) > MAX_BYTES:
            return {}
        raw = json.loads(blob)
    except (OSError, ValueError, UnicodeDecodeError):
        return {}

    if not isinstance(raw, dict) or raw.get("key") != "core.device_registry":
        return {}
    data = raw.get("data")
    devices = data.get("devices") if isinstance(data, dict) else None
    if not isinstance(devices, list) or len(devices) > 10000:
        return {}

    matches: dict[str, str] = {}
    ambiguous: set[str] = set()
    for row in devices:
        if not isinstance(row, dict):
            continue
        device_id = row.get("id")
        identifiers = row.get("identifiers")
        if (not isinstance(device_id, str) or not DEVICE_ID.fullmatch(device_id)
                or not isinstance(identifiers, list)):
            continue
        for pair in identifiers[:64]:
            if (not isinstance(pair, (list, tuple)) or len(pair) != 2
                    or pair[0] != "mqtt" or not isinstance(pair[1], str)
                    or not pair[1].startswith(PREFIX)):
                continue
            ieee = pair[1][len(PREFIX):].lower()
            if not IEEE.fullmatch(ieee):
                continue
            previous = matches.get(ieee)
            if previous is not None and previous != device_id:
                ambiguous.add(ieee)
            else:
                matches[ieee] = device_id
    return {ieee: did for ieee, did in matches.items() if ieee not in ambiguous}
