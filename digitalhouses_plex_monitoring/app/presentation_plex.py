from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Mapping

from .models import MonitorSnapshot
from .presentation import AdaptiveGroup, ProfileWindows, PublicationProfile
from .presentation_policy import PlexProfileSelector


@dataclass(frozen=True)
class Publication:
    group: str
    payload: dict[str, object]
    reason: str
    profile: PublicationProfile


_PLAYBACK_SEMANTIC_KEYS = (
    "content_type",
    "media_type",
    "title",
    "year",
    "artist",
    "album",
    "album_year",
    "series",
    "season",
    "episode",
    "user",
    "player",
    "device",
    "platform",
    "state",
    "location",
    "mode",
    "video_decision",
    "audio_decision",
    "subtitle_decision",
    "video_codec",
    "audio_codec",
    "video_resolution",
    "hardware_transcode",
    "hw_decode",
    "hw_encode",
)


def _round(value: float) -> float:
    return round(float(value), 1)


def _activity_payload(snapshot: MonitorSnapshot) -> dict[str, object]:
    activity = snapshot.activity
    current_items = activity.current_items
    if not current_items and activity.current_item:
        current_items = (activity.current_item,)

    current_item = activity.current_item
    if current_item is None:
        if len(current_items) == 1:
            current_item = current_items[0]
        elif len(current_items) > 1:
            current_item = f"{len(current_items)} active items"

    return {
        "activity": activity.activity,
        "current_item": current_item or "none",
        "current_items": list(current_items),
        "current_item_count": len(current_items),
        "transcoder_count": activity.transcoder_count,
        "scanner_count": activity.scanner_count,
        "server_running": activity.plex_server_running,
        "scanner_running": activity.scanner_running,
        "credits_detection": activity.credits_detection,
        "intro_detection": activity.intro_detection,
        "thumbnail_generation": activity.thumbnail_generation,
        "transcoder_running": activity.transcoder_running,
        "scanner_actions": (
            ",".join(activity.scanner_actions)
            if activity.scanner_actions
            else "none"
        ),
    }


def _playback_payload(api: Mapping[str, object]) -> dict[str, object]:
    keys = (
        "playback_count",
        "playback_sessions_state",
        "playback_active",
        "video_playback_count",
        "audio_playback_count",
        "video_playback_active",
        "audio_playback_active",
        "hardware_transcode_active",
        "playback_sessions",
    )
    return {key: copy.deepcopy(api.get(key)) for key in keys}


def _playback_semantic(payload: Mapping[str, object]) -> dict[str, object]:
    sessions = payload.get("playback_sessions")
    compact: list[dict[str, object]] = []
    if isinstance(sessions, list):
        for raw in sessions:
            if not isinstance(raw, Mapping):
                continue
            compact.append(
                {
                    key: copy.deepcopy(raw.get(key))
                    for key in _PLAYBACK_SEMANTIC_KEYS
                    if raw.get(key) is not None
                }
            )
    compact.sort(key=lambda item: repr(sorted(item.items())))
    return {
        "playback_count": payload.get("playback_count"),
        "playback_active": payload.get("playback_active"),
        "video_playback_count": payload.get("video_playback_count"),
        "audio_playback_count": payload.get("audio_playback_count"),
        "video_playback_active": payload.get("video_playback_active"),
        "audio_playback_active": payload.get("audio_playback_active"),
        "hardware_transcode_active": payload.get("hardware_transcode_active"),
        "sessions": compact,
    }


def _libraries_payload(api: Mapping[str, object]) -> dict[str, object]:
    keys = ("library_count", "libraries", "libraries_by_id")
    return {key: copy.deepcopy(api.get(key)) for key in keys}


class PlexPresentationRouter:
    """Convert collected Plex state into independent Recorder-facing groups."""

    def __init__(
        self,
        *,
        source_interval_seconds: float,
        high_cpu_threshold: float = 80.0,
        windows: ProfileWindows | None = None,
    ) -> None:
        self.source_interval_seconds = float(source_interval_seconds)
        self.windows = windows or ProfileWindows()
        self._cpu = AdaptiveGroup(
            windows=self.windows,
            source_interval_seconds=self.source_interval_seconds,
            round_digits=1,
        )
        self._gpu = AdaptiveGroup(
            windows=self.windows,
            source_interval_seconds=self.source_interval_seconds,
            round_digits=1,
        )
        self._selector = PlexProfileSelector(
            high_cpu_threshold=high_cpu_threshold,
        )
        self._last_semantic: dict[str, object] = {}

    def _change_only(
        self,
        group: str,
        payload: dict[str, object],
        *,
        semantic: object | None = None,
        profile: PublicationProfile,
        force: bool,
        manual: bool,
    ) -> Publication | None:
        current_semantic = copy.deepcopy(payload if semantic is None else semantic)
        previous = self._last_semantic.get(group)
        if previous is None:
            reason = "startup"
        elif manual:
            reason = "manual_refresh"
        elif force:
            reason = "force"
        elif previous != current_semantic:
            reason = "change"
        else:
            return None

        self._last_semantic[group] = current_semantic
        return Publication(group, payload, reason, profile)

    def route(
        self,
        snapshot: MonitorSnapshot,
        api_payload: Mapping[str, object],
        gpu_payload: Mapping[str, object] | None = None,
        *,
        now: float,
        force: bool = False,
        manual: bool = False,
    ) -> tuple[Publication, ...]:
        playback_active = bool(api_payload.get("playback_active"))
        choice = self._selector.observe(
            now=now,
            cpu_percent=snapshot.cpu.total.current,
            scanner_running=snapshot.activity.scanner_running,
            transcoder_running=snapshot.activity.transcoder_running,
            playback_active=playback_active,
        )

        result: list[Publication] = []

        activity_payload = _activity_payload(snapshot)
        activity = self._change_only(
            "activity",
            activity_payload,
            profile=choice.profile,
            force=force,
            manual=manual,
        )
        if activity is not None:
            result.append(activity)

        cpu_decision = self._cpu.observe(
            now=now,
            continuous={
                "cpu": snapshot.cpu.total.current,
                "scanner_cpu": snapshot.cpu.scanner.current,
                "transcoder_cpu": snapshot.cpu.transcoder.current,
            },
            requested_profile=choice.profile,
            force=force,
            manual=manual,
        )
        if cpu_decision.publish:
            values = cpu_decision.values
            cpu_payload: dict[str, object] = {
                "cpu": _round(float(values.get("cpu", snapshot.cpu.total.current))),
                "cpu_avg": _round(snapshot.cpu.total.average),
                "cpu_max": _round(snapshot.cpu.total.maximum),
                "scanner_cpu": _round(
                    float(values.get("scanner_cpu", snapshot.cpu.scanner.current))
                ),
                "scanner_cpu_avg": _round(snapshot.cpu.scanner.average),
                "scanner_cpu_max": _round(snapshot.cpu.scanner.maximum),
                "transcoder_cpu": _round(
                    float(values.get("transcoder_cpu", snapshot.cpu.transcoder.current))
                ),
                "transcoder_cpu_avg": _round(snapshot.cpu.transcoder.average),
                "transcoder_cpu_max": _round(snapshot.cpu.transcoder.maximum),
            }
            result.append(
                Publication(
                    "cpu",
                    cpu_payload,
                    cpu_decision.reason or "change",
                    cpu_decision.profile,
                )
            )

        playback_payload = _playback_payload(api_payload)
        playback = self._change_only(
            "playback",
            playback_payload,
            semantic=_playback_semantic(playback_payload),
            profile=choice.profile,
            force=force,
            manual=manual,
        )
        if playback is not None:
            result.append(playback)

        libraries = self._change_only(
            "libraries",
            _libraries_payload(api_payload),
            profile=choice.profile,
            force=force,
            manual=manual,
        )
        if libraries is not None:
            result.append(libraries)

        gpu_source = dict(gpu_payload or {})
        gpu_decision = self._gpu.observe(
            now=now,
            continuous={
                "video_busy_percent": gpu_source.get("video_busy_percent"),
                "render_busy_percent": gpu_source.get("render_busy_percent"),
                "video_enhance_busy_percent": gpu_source.get(
                    "video_enhance_busy_percent"
                ),
                "frequency_mhz": gpu_source.get("frequency_mhz"),
                "rc6_percent": gpu_source.get("rc6_percent"),
                "temperature_c": gpu_source.get("temperature_c"),
            },
            discrete={
                "supported": bool(gpu_source.get("supported", False)),
                "available": bool(gpu_source.get("available", False)),
                "status": str(gpu_source.get("status") or "unsupported"),
                "source": gpu_source.get("source"),
                "pci_address": gpu_source.get("pci_address"),
            },
            requested_profile=choice.profile,
            force=force,
            manual=manual,
        )
        if gpu_decision.publish:
            result.append(
                Publication(
                    "gpu",
                    gpu_decision.values,
                    gpu_decision.reason or "change",
                    gpu_decision.profile,
                )
            )

        return tuple(result)

    def profile_summary(self) -> dict[str, object]:
        return {
            "state": self._selector.profile.value,
            "reason": self._selector.reason,
            "resources": {"cpu": self._selector.profile.value},
        }
