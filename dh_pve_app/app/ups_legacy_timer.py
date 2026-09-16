from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path


MANAGED_TIMER = "dh-pve-ups-shutdown"
_MANAGED_START_RE = re.compile(
    rf"^\s*AT\s+ONBATT\s+\*\s+START-TIMER\s+{re.escape(MANAGED_TIMER)}\s+\d+\s*(?:#.*)?$",
    re.IGNORECASE,
)
_MANAGED_CANCEL_RE = re.compile(
    rf"^\s*AT\s+ONLINE\s+\*\s+CANCEL-TIMER\s+{re.escape(MANAGED_TIMER)}\s*(?:#.*)?$",
    re.IGNORECASE,
)
_AT_RE = re.compile(r"^\s*AT\s+", re.IGNORECASE)
_NOTIFYCMD_UPSSCHED_RE = re.compile(
    r"^\s*NOTIFYCMD\s+/usr/sbin/upssched\s*(?:#.*)?$",
    re.IGNORECASE,
)
_MANAGED_NOTIFYFLAG_RE = re.compile(
    r"^(?P<indent>\s*)NOTIFYFLAG\s+(?P<event>ONBATT|ONLINE)\s+SYSLOG\+EXEC\s*(?P<comment>#.*)?$",
    re.IGNORECASE,
)


def legacy_timer_present(upssched_text: str) -> bool:
    return any(
        _MANAGED_START_RE.match(line) or _MANAGED_CANCEL_RE.match(line)
        for line in upssched_text.splitlines()
    )


def _remove_managed_timer_lines(upssched_text: str) -> str:
    lines = [
        line
        for line in upssched_text.splitlines()
        if not (_MANAGED_START_RE.match(line) or _MANAGED_CANCEL_RE.match(line))
    ]
    suffix = "\n" if upssched_text.endswith("\n") else ""
    return "\n".join(lines) + suffix


def _has_active_at_rules(upssched_text: str) -> bool:
    for raw in upssched_text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        if _AT_RE.match(raw):
            return True
    return False


def _detach_managed_upssched_dispatch(upsmon_text: str) -> str:
    output: list[str] = []
    for raw in upsmon_text.splitlines():
        if _NOTIFYCMD_UPSSCHED_RE.match(raw):
            continue
        match = _MANAGED_NOTIFYFLAG_RE.match(raw)
        if match is not None:
            comment = match.group("comment") or ""
            spacing = " " if comment else ""
            output.append(
                f"{match.group('indent')}NOTIFYFLAG {match.group('event').upper()} SYSLOG{spacing}{comment}"
            )
            continue
        output.append(raw)
    suffix = "\n" if upsmon_text.endswith("\n") else ""
    return "\n".join(output) + suffix


def retire_legacy_timer_text(upsmon_text: str, upssched_text: str) -> tuple[str, str]:
    if not legacy_timer_present(upssched_text):
        return upsmon_text, upssched_text

    new_upssched = _remove_managed_timer_lines(upssched_text)
    if _has_active_at_rules(new_upssched):
        return upsmon_text, new_upssched
    return _detach_managed_upssched_dispatch(upsmon_text), new_upssched


def _atomic_replace(path: Path, text: str) -> None:
    info = path.stat()
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, info.st_mode & 0o7777)
        try:
            os.chown(tmp, info.st_uid, info.st_gid)
        except PermissionError:
            pass
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def retire_legacy_timer_files(
    *,
    upsmon_path: Path = Path("/etc/nut/upsmon.conf"),
    upssched_path: Path = Path("/etc/nut/upssched.conf"),
) -> bool:
    if not upsmon_path.exists() or not upssched_path.exists():
        return False

    upsmon_text = upsmon_path.read_text(encoding="utf-8")
    upssched_text = upssched_path.read_text(encoding="utf-8")
    new_upsmon, new_upssched = retire_legacy_timer_text(upsmon_text, upssched_text)
    if new_upsmon == upsmon_text and new_upssched == upssched_text:
        return False

    for path in (upsmon_path, upssched_path):
        backup = path.with_name(path.name + ".dh-pve-v1.bak")
        if not backup.exists():
            shutil.copy2(path, backup)

    if new_upsmon != upsmon_text:
        _atomic_replace(upsmon_path, new_upsmon)
    if new_upssched != upssched_text:
        _atomic_replace(upssched_path, new_upssched)
    return True
