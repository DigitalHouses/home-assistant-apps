#!/usr/bin/env bash
# Small, versionless bootstrap. The actual installer is always fetched from
# the canonical tag of a published stable Plex Agent GitHub Release.
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run the Plex Agent installer as root (or sudo)." >&2
    exit 1
fi
for required in python3 curl; do
    if ! command -v "${required}" >/dev/null 2>&1; then
        echo "Missing required bootstrap command: ${required}" >&2
        exit 1
    fi
done

RELEASE_TAG="$(python3 - <<'PY'
import json
import re
import urllib.request

RELEASES_URL = "https://api.github.com/repos/DigitalHouses/home-assistant-apps/releases"
STABLE_TAG = re.compile(r"^digitalhouses_plex_agent-v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def latest_release(opener=urllib.request.urlopen):
    selected_tag = None
    highest = None
    for page in range(1, 11):
        request = urllib.request.Request(
            f"{RELEASES_URL}?per_page=100&page={page}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "DigitalHouses-Plex-Installer",
            },
        )
        with opener(request, timeout=12) as response:
            releases = json.load(response)
        if not isinstance(releases, list):
            raise ValueError("Unexpected GitHub Releases response")
        for release in releases:
            if not isinstance(release, dict):
                continue
            if release.get("draft") or release.get("prerelease") or not release.get("published_at"):
                continue
            tag = release.get("tag_name")
            match = STABLE_TAG.fullmatch(tag) if isinstance(tag, str) else None
            if match is None:
                continue
            version = tuple(map(int, match.groups()))
            if highest is None or version > highest:
                highest, selected_tag = version, tag
        if len(releases) < 100:
            if selected_tag is None:
                raise ValueError("No published stable Plex Agent release found")
            return selected_tag
    raise ValueError("GitHub Releases pagination exceeded 1000 entries")


if __name__ == "__main__":
    try:
        print(latest_release())
    except Exception as exc:
        raise SystemExit(f"Unable to determine latest stable Plex Agent release: {exc}")
PY
)"

if [[ ! "${RELEASE_TAG}" =~ ^digitalhouses_plex_agent-v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Invalid canonical Plex Agent release tag returned by GitHub." >&2
    exit 1
fi

installer="$(mktemp)"
trap 'rm -f "${installer}"' EXIT
url="https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/${RELEASE_TAG}/digitalhouses_plex_agent/install.sh"
echo "Latest stable Plex Agent release: ${RELEASE_TAG}"
curl -fsSL --retry 2 --connect-timeout 10 --max-time 90 "${url}" -o "${installer}"
if [[ "$(head -n 1 "${installer}")" != '#!/usr/bin/env bash' ]]; then
    echo "Downloaded release installer has an unexpected format." >&2
    exit 1
fi
DIGITALHOUSES_SOURCE_REF="${RELEASE_TAG}" bash "${installer}"
