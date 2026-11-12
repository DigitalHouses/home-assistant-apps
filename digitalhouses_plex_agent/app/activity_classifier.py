from __future__ import annotations

from pathlib import Path
import re
from typing import Sequence

from .models import ActivityState, BackgroundProcess, ProcessSample
from .process_identity import process_role

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
    # Plex Transcoder uses -i for the real input media.
    explicit = _argument_value(cmdline, {"-i"})
    if not explicit:
        explicit = _argument_value(
            cmdline,
            {"--file", "--directory"},
        )

    if explicit:
        candidate = Path(explicit).name
        if (
            candidate
            and not candidate.casefold().startswith(
                "plexcreditsdetection-"
            )
        ):
            return candidate

    # Fall back only to recognizable media paths.
    # Short ffmpeg options such as -f are deliberately ignored.
    for token in reversed(tuple(cmdline)):
        path = Path(token)
        if path.suffix.casefold() in MEDIA_EXTENSIONS:
            return path.name

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


def _has_loudnorm_filter(value: str) -> bool:
    # Split only real chain separators; quoted/escaped commas belong to values.
    entries: list[str] = []
    start = 0
    quote = None
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == ",":
            entries.append(value[start:index])
            start = index + 1
    entries.append(value[start:])
    return any(re.fullmatch(r"\s*loudnorm(?:\s*=.*)?\s*", entry) for entry in entries)


def _audio_analysis_signature(cmdline: Sequence[str]) -> bool:
    # Read option values, never search filenames or unrelated arguments.
    audio_filters: list[str] = []
    null_format_index = -1
    last_input_index = -1
    index = 1
    while index < len(cmdline):
        option, separator, inline = cmdline[index].partition("=")
        if option == "-i":
            last_input_index = index
        is_audio = bool(re.fullmatch(r"-(?:af|filter:a)(?::[0-9]+)?", option))
        is_format = option == "-f"
        if is_audio or is_format:
            value = inline if separator else (
                cmdline[index + 1] if index + 1 < len(cmdline) else ""
            )
            if is_audio:
                audio_filters.append(value)
            else:
                null_format_index = index if value == "null" else -1
            if not separator:
                index += 1
        index += 1
    # An input format before -i does not describe the output.
    return null_format_index > last_input_index and any(
        _has_loudnorm_filter(value) for value in audio_filters
    )


def classify_activity(
    processes: Sequence[ProcessSample],
) -> ActivityState:
    server_running = False
    scanner_count = 0
    credits = False
    intro = False
    thumbnails = False
    transcoder_count = 0
    audio_analysis_count = 0
    background: list[BackgroundProcess] = []
    actions: list[str] = []
    items: list[str] = []

    for process in processes:
        role = process_role(process)

        if role == "server":
            server_running = True

        if role == "scanner":
            scanner_count += 1
            process_actions = extract_server_actions(process.cmdline)

            for action in process_actions:
                if action not in actions:
                    actions.append(action)

            credits = credits or _credits_signature(
                process.cmdline,
                process_actions,
            )
            intro = intro or _intro_signature(process_actions)
            thumbnails = thumbnails or _thumbnail_signature(
                process.cmdline,
                process_actions,
            )

            item = extract_current_item(process.cmdline)
            if item and item not in items:
                items.append(item)
            if _credits_signature(process.cmdline, process_actions):
                kind, label = "credits_detection", "Credits Detection"
            elif _intro_signature(process_actions):
                kind, label = "intro_detection", "Intro Detection"
            elif _thumbnail_signature(process.cmdline, process_actions):
                kind, label = "thumbnail_generation", "Thumbnail Generation"
            else:
                kind, label = "scanner", "Media Scanner"
            background.append(BackgroundProcess(
                process.pid, kind, label, item,
            ))

        if role == "transcoder":
            transcoder_count += 1
            if _audio_analysis_signature(process.cmdline):
                audio_analysis_count += 1
                background.append(BackgroundProcess(
                    process.pid, "audio_analysis", "Audio Analysis",
                    extract_current_item(process.cmdline),
                ))

            item = extract_current_item(process.cmdline)
            if item and item not in items:
                items.append(item)

    scanner_running = scanner_count > 0
    transcoder = transcoder_count > 0

    if len(items) == 1:
        current_item = items[0]
    elif len(items) > 1:
        current_item = f"{len(items)} active items"
    else:
        current_item = None

    regular_transcoder = transcoder_count > audio_analysis_count
    audio_analysis = audio_analysis_count > 0
    specific = [credits, intro, thumbnails, regular_transcoder, audio_analysis]

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
    elif audio_analysis:
        activity = "audio_analysis"
    elif regular_transcoder:
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
        current_items=tuple(items),
        transcoder_count=transcoder_count,
        scanner_count=scanner_count,
        audio_analysis_running=audio_analysis,
        audio_analysis_count=audio_analysis_count,
        background_processes=tuple(sorted(background, key=lambda process: process.pid)[:24]),
    )
