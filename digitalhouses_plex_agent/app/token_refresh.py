"""Narrow, systemd-mediated recovery for a rotated local Plex API token.

The unprivileged agent only writes a fixed request marker. A separate
root-owned one-shot unit validates the *local* Plex token before replacing
the protected copy used by the agent. No token bytes enter logs or MQTT.
"""
from __future__ import annotations

import grp
import logging
import os
from pathlib import Path
import tempfile
import time
import urllib.error
import urllib.request

SOURCE_TOKEN = Path(
    "/var/lib/plexmediaserver/Library/Application Support/"
    "Plex Media Server/.LocalAdminToken"
)
AGENT_TOKEN = Path("/etc/digitalhouses_plex_agent/plex_local_admin_token")
REQUEST_FILE = Path("/var/lib/digitalhouses_plex_agent/token-refresh-request")
SERVICE_GROUP = "digitalhouses_plex_agent"
LOCAL_PLEX_API = "http://127.0.0.1:32400/status/sessions"
REFRESH_COOLDOWN_SECONDS = 60.0

_next_request_at = 0.0
log = logging.getLogger("digitalhouses_plex_agent.token_refresh")


def request_token_refresh(
    request_file: Path = REQUEST_FILE,
    *,
    cooldown_seconds: float = REFRESH_COOLDOWN_SECONDS,
) -> bool:
    """Request narrow root-side token reconciliation, at most once per cooldown."""
    global _next_request_at
    now = time.monotonic()
    if now < _next_request_at:
        return False
    _next_request_at = now + cooldown_seconds
    try:
        # A real write/close is intentional: systemd PathModified sees it.
        request_file.write_text("refresh\n", encoding="ascii")
    except OSError as exc:
        log.warning("Plex token refresh request failed (%s)", type(exc).__name__)
        return False
    log.info("Plex API returned 401; requested local token reconciliation")
    return True


def validate_local_token(token: str) -> bool:
    """Never install a replacement token without testing Plex API authorization."""
    request = urllib.request.Request(
        LOCAL_PLEX_API,
        headers={"X-Plex-Token": token, "Accept": "application/xml"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def sync_token(
    source: Path = SOURCE_TOKEN,
    target: Path = AGENT_TOKEN,
    *,
    group_gid: int | None = None,
    validator=validate_local_token,
) -> str:
    """Root-only, validated atomic sync. Returns UPDATED or UNCHANGED."""
    if os.geteuid() != 0:
        raise PermissionError("Plex token reconciliation must run as root")

    # Bound the bytes read and never print, log, or include the token in errors.
    with source.open("rb") as handle:
        raw = handle.read(4097)
    if len(raw) > 4096:
        raise ValueError("Plex original token is oversized")
    try:
        token = raw.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise ValueError("Plex original token is not UTF-8") from exc
    if not token:
        raise ValueError("Plex original token is missing or empty")

    try:
        current = target.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        current = None
    if current == token:
        return "UNCHANGED"

    # Do not destroy an existing, potentially recoverable token if the
    # candidate is invalid or the Plex server is temporarily unavailable.
    if not validator(token):
        raise ValueError("Plex original token did not pass local API validation")

    if group_gid is None:
        group_gid = grp.getgrnam(SERVICE_GROUP).gr_gid

    fd, temp_path = tempfile.mkstemp(prefix=".plex-token-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o640)
            os.fchown(handle.fileno(), 0, group_gid)
            handle.write((token + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    return "UPDATED"


def main() -> int:
    try:
        result = sync_token()
    except (OSError, ValueError, PermissionError) as exc:
        log.error("Plex token reconciliation failed (%s)", type(exc).__name__)
        return 1
    print(f"PLEX_LOCAL_TOKEN={result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
