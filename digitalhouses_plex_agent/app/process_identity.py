from __future__ import annotations

from pathlib import Path

from .models import ProcessSample


def _command_identity(cmdline: tuple[str, ...]) -> str:
    if not cmdline:
        return ""

    parts = [Path(cmdline[0]).name]
    for token in cmdline[1:3]:
        if token.startswith("-"):
            break
        parts.append(token)

    return " ".join(parts).casefold()


def process_role(process: ProcessSample) -> str | None:
    identity = " ".join((
        process.name.casefold(),
        _command_identity(process.cmdline),
    ))

    if "plex media scanner" in identity:
        return "scanner"
    if "plex transcoder" in identity:
        return "transcoder"
    if "plex media server" in identity:
        return "server"
    return None
