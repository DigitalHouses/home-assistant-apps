"""Presentation timezone of this independent statistics server."""
from pathlib import Path
from zoneinfo import ZoneInfo

LOCALTIME = Path("/etc/localtime")
ZONEINFO = Path("/usr/share/zoneinfo")


def local_zone():
    try:
        name = LOCALTIME.resolve(strict=True).relative_to(ZONEINFO.resolve()).as_posix()
        return ZoneInfo(name).key
    except (OSError, ValueError, KeyError):
        return None


def zone_metadata():
    zone = local_zone()
    return {"timezone": zone or "UTC", "timezone_fallback": zone is None}
