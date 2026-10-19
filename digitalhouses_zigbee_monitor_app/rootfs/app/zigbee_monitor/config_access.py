"""Read-only HA config mount diagnostics. Never read or log file contents.

Only fixed paths under the declared /homeassistant mount are inspected.
No Zigbee2MQTT YAML parser, secret discovery or Supervisor privileges.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

HA_CONFIG = Path("/homeassistant")
Z2M_RELATIVE = Path("zigbee2mqtt/configuration.yaml")
_ALLOWED_STATES = frozenset({
    "ready", "mount_missing", "directory_missing",
    "file_missing", "file_unreadable",
})


def probe_config_access(
    root: Path = HA_CONFIG,
    *,
    is_mount: Callable[[str], bool] = os.path.ismount,
) -> dict[str, str]:
    """Report only existence and openability, without reading a single byte.

    Treat a directory that merely exists but is not mounted as absent.
    os.open(O_RDONLY | O_NOFOLLOW) checks real read access and rejects
    symlinked configuration files that could escape the read-only mount.
    """
    result = {
        "state": "mount_missing",
        "mount": "missing",
        "z2m_directory": "not_checked",
        "z2m_config": "not_checked",
    }
    try:
        if not root.is_dir() or not is_mount(str(root)):
            return result
        result["mount"] = "ok"
        z2m_dir = root / "zigbee2mqtt"
        if not z2m_dir.is_dir():
            result["state"] = "directory_missing"
            result["z2m_directory"] = "missing"
            return result
        result["z2m_directory"] = "ok"
        target = root / Z2M_RELATIVE
        if not target.exists():
            result["state"] = "file_missing"
            result["z2m_config"] = "missing"
            return result
        if not target.is_file():
            result["state"] = "file_unreadable"
            result["z2m_config"] = "not_readable"
            return result
        # Do not read contents; checking openability alone proves readable.
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(target, flags)
        os.close(fd)
    except OSError:
        # Access denied, symlink, broken mount, unexpected FS error:
        # do not leak exception text, paths or file data into MQTT/logs.
        if result["mount"] != "ok":
            return result
        result["state"] = "file_unreadable"
        result["z2m_config"] = "not_readable"
        return result
    result["state"] = "ready"
    result["z2m_config"] = "readable"
    assert result["state"] in _ALLOWED_STATES
    return result
