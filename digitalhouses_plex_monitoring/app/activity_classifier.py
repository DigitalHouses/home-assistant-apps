from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .models import ActivityState, ProcessSample

MEDIA_EXTENSIONS = {
    ".mkv", ".mp4", ".m4v", ".avi", ".mov", ".ts", ".m2ts",
    ".mpeg", ".mpg", ".webm",
    ".mp3", ".flac", ".m4a", ".aac", ".wav", ".ogg",
}


def _fold(value: str) -> str:
    return value.casefold()


def extract_server_actions(cmdline: Sequence[str]) -> tuple[str, ...]:
    actions: list[str] = []
    for index, token in enumerate(cmdline):
        folded = _fold(token)
        value: str | None = None
        if folded == "--server-action" and index + 1 < len(cmdline):
            value = cmdline[index + 1]
        elif folded.startswith("--server-action="):
            value = token.split("=", 1)[1]
        if value is not None:
            for action in value.split(","):
                normalized = action.strip().casefold()
                if normalized and normalized not in actions:
                    actions.append(normalized)
    return tuple(actions)


def _argument_value(
    cmdline: Sequence[str],
    names: set[str],
) -> str | None:
    for index, token in enumerate(cmdline):
        if token.casefold() in names and index + 1 < len(cmdline):
            return cmdline[index + 1]
    return None


def extract_current_item(cmdline: Sequence[str]) -> str | None:
    # Strong explicit file/directory arguments first.
    explicit = _argument_value(
        cmdline,
        {"--file", "-f", "--directory", "-d"},
    )
    if explicit:
        candidate = Path(explicit).name
        if candidate and not candidate.casefold().startswith("plexcreditsdetection-"):
            return candidate

    # Then any recognizable media path in the command line.
    for token in reversed(tuple(cmdline)):
        path = Path(token)
        if path.suffix.casefold() in MEDIA_EXTENSIONS:
            return path.name

    item = _argument_value(cmdline, {"--item", "-o"})
    if item:
        return f"item {item}"

    section = _argument_value(cmdline, {"--section", "-c"})
    if section:
        return f"section {section}"

    return None


def _contains_token(cmdline: Sequence[str], target: str) -> bool:
    target = target.casefold()
    return any(token.casefold() == target for token in cmdline)


def _credits_signature(cmdline: Sequence[str], actions: tuple[str, ...]) -> bool:
    if "credits" in actions:
        return True
    folded = tuple(token.casefold() for token in cmdline)
    if "--creditstempdatapath" in folded:
        return True
    suffix = _argument_value(cmdline, {"--log-file-suffix"})
    return bool(suffix and "credits" in suffix.casefold())


def _intro_signature(actions: tuple[str, ...]) -> bool:
    return "intro" in actions or "intros" in actions


def _thumbnail_signature(
    cmdline: Sequence[str],
    actions: tuple[str, ...],
) -> bool:
    if "index" in actions:
        return True
    return any(
        _contains_token(cmdline, token)
        for token in ("--index", "-b", "--chapter-thumbs-only")
    )


def classify_activity(
    processes: Sequence[ProcessSample],
) -> ActivityState:
    server_running = False
    scanner_running = False
    credits = False
    intro = False
    thumbnails = False
    transcoder = False
    actions: list[str] = []
    current_item: str | None = None

    for process in processes:
        name = process.name.casefold()
        if "media server" in name and "scanner" not in name:
            server_running = True

        if "media scanner" in name:
            scanner_running = True
            process_actions = extract_server_actions(process.cmdline)
            for action in process_actions:
                if action not in actions:
                    actions.append(action)
            credits = credits or _credits_signature(
                process.cmdline, process_actions
            )
            intro = intro or _intro_signature(process_actions)
            thumbnails = thumbnails or _thumbnail_signature(
                process.cmdline, process_actions
            )
            if current_item is None:
                current_item = extract_current_item(process.cmdline)

        if "transcoder" in name:
            transcoder = True
            if current_item is None:
                current_item = extract_current_item(process.cmdline)

    specific = [credits, intro, thumbnails, transcoder]

    if not server_running and not scanner_running and not transcoder:
        activity = "plex_not_running"
    elif (scanner_running and transcoder) or sum(
        bool(value) for value in specific
    ) > 1:
        activity = "multiple"
    elif credits:
        activity = "credits_detection"
    elif intro:
        activity = "intro_detection"
    elif thumbnails:
        activity = "thumbnail_generation"
    elif transcoder:
        activity = "transcoding"
    elif scanner_running:
        activity = "scanner"
    else:
        activity = "idle"

    return ActivityState(
        plex_server_running=server_running,
        scanner_running=scanner_running,
        credits_detection=credits,
        intro_detection=intro,
        thumbnail_generation=thumbnails,
        transcoder_running=transcoder,
        activity=activity,
        scanner_actions=tuple(actions),
        current_item=current_item,
    )
