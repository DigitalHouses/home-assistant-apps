"""Published stable GitHub release selection shared by CLI and MQTT."""
from __future__ import annotations

import json
import re
import urllib.request

RELEASES_URL = "https://api.github.com/repos/DigitalHouses/home-assistant-apps/releases"
TAG = re.compile(r"^digitalhouses_pbs_agent-v(\d+)\.(\d+)\.(\d+)$")


def stable_version(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value)
    if match is None:
        raise ValueError("invalid stable version")
    return tuple(map(int, match.groups()))


def latest_release(*, opener=urllib.request.urlopen) -> tuple[str, str]:
    best: tuple[tuple[int, int, int], str] | None = None
    for page in range(1, 11):
        request = urllib.request.Request(
            f"{RELEASES_URL}?per_page=100&page={page}",
            headers={"User-Agent": "DigitalHouses-PBS-Agent",
                     "Accept": "application/vnd.github+json"},
        )
        with opener(request, timeout=12) as response:
            releases = json.load(response)
        if not isinstance(releases, list):
            raise ValueError("invalid GitHub releases")
        for entry in releases:
            if (not isinstance(entry, dict) or entry.get("draft") or entry.get("prerelease")
                    or not entry.get("published_at")):
                continue
            tag = entry.get("tag_name")
            match = TAG.fullmatch(tag) if isinstance(tag, str) else None
            if match is not None:
                item = tuple(map(int, match.groups())), tag
                if best is None or item[0] > best[0]:
                    best = item
        if len(releases) < 100:
            if best is None:
                raise ValueError("no published stable PBS Agent release")
            return best[1], ".".join(map(str, best[0]))
    raise ValueError("release pagination limit reached")
