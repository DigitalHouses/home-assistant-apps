from __future__ import annotations

from dataclasses import dataclass

from .config import PlexApiConfig
from .plex_api import (
    LibraryInfo,
    PlexApiCollector,
    PlexApiError,
    PlaybackSession,
    build_plex_api_payload,
    library_fingerprint,
    playback_fingerprint,
)


@dataclass(frozen=True)
class ApiCollectResult:
    changed: bool
    libraries_changed: bool
    recovered: bool
    failed: bool
    failure_transition: bool


class PlexApiRuntime:
    def __init__(
        self,
        config: PlexApiConfig,
        *,
        collector: PlexApiCollector | None = None,
    ) -> None:
        self.config = config
        self.collector = collector or PlexApiCollector(config)
        self.sessions: tuple[PlaybackSession, ...] = ()
        self.libraries: tuple[LibraryInfo, ...] = ()
        self.status = "starting" if config.enabled else "disabled"
        self._next_library_refresh = 0.0
        self._libraries_initialized = False
        self.last_error: str | None = None

    @property
    def failed(self) -> bool:
        return self.status == "error"

    def payload(self) -> dict[str, object]:
        return build_plex_api_payload(
            self.sessions,
            self.libraries,
            self.status,
        )

    def collect(
        self,
        *,
        now: float,
        refresh: bool = False,
        scanner_finished: bool = False,
    ) -> ApiCollectResult:
        if not self.config.enabled:
            return ApiCollectResult(
                changed=False,
                libraries_changed=False,
                recovered=False,
                failed=False,
                failure_transition=False,
            )

        old_status = self.status
        old_playback = playback_fingerprint(self.sessions)
        old_libraries = library_fingerprint(self.libraries)
        libraries_due = (
            not self._libraries_initialized
            or refresh
            or scanner_finished
            or now >= self._next_library_refresh
        )

        try:
            sessions = self.collector.collect_playback()
            libraries = self.libraries
            if libraries_due:
                libraries = self.collector.collect_libraries()
        except PlexApiError as exc:
            self.status = "error"
            self.last_error = str(exc)
            return ApiCollectResult(
                changed=old_status != "error",
                libraries_changed=False,
                recovered=False,
                failed=True,
                failure_transition=old_status != "error",
            )

        self.sessions = sessions
        self.libraries = libraries
        self.status = "ok"
        self.last_error = None
        if libraries_due:
            self._libraries_initialized = True
            self._next_library_refresh = (
                float(now) + self.config.library_refresh_seconds
            )

        new_playback = playback_fingerprint(self.sessions)
        new_libraries = library_fingerprint(self.libraries)
        libraries_changed = new_libraries != old_libraries
        status_changed = old_status != "ok"
        recovered = old_status == "error"
        changed = (
            status_changed
            or new_playback != old_playback
            or libraries_changed
        )
        return ApiCollectResult(
            changed=changed,
            libraries_changed=libraries_changed,
            recovered=recovered,
            failed=False,
            failure_transition=False,
        )
