from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

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
        playback_state_path: Path | None = None,
        now_utc: Callable[[], str] | None = None,
    ) -> None:
        self.config = config
        self.collector = collector or PlexApiCollector(config)
        self.sessions: tuple[PlaybackSession, ...] = ()
        self.libraries: tuple[LibraryInfo, ...] = ()
        self.status = "starting" if config.enabled else "disabled"
        self._next_library_refresh = 0.0
        self._libraries_initialized = False
        self.last_error: str | None = None
        self.playback_state_path = playback_state_path
        self._now_utc = now_utc or (
            lambda: datetime.now(timezone.utc).isoformat()
        )
        self._session_started_at = self._load_session_starts()
        self.playback_started_at: str | None = None

    @property
    def failed(self) -> bool:
        return self.status == "error"

    def _load_session_starts(self) -> dict[str, str]:
        path = self.playback_state_path
        if path is None or not path.is_file():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        sessions = raw.get("sessions") if isinstance(raw, dict) else None
        if not isinstance(sessions, dict):
            return {}
        return {
            str(session_id): str(started_at)
            for session_id, started_at in sessions.items()
            if session_id and isinstance(started_at, str) and started_at
        }

    def _save_session_starts(self) -> None:
        path = self.playback_state_path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(
                json.dumps(
                    {"sessions": self._session_started_at},
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            tmp.chmod(0o600)
            tmp.replace(path)
        except OSError:
            return

    def _reconcile_session_starts(
        self,
        sessions: tuple[PlaybackSession, ...],
    ) -> None:
        observed_at = self._now_utc()
        active_ids = {session.session_id for session in sessions}
        reconciled = {
            session_id: started_at
            for session_id, started_at in self._session_started_at.items()
            if session_id in active_ids
        }
        for session in sessions:
            reconciled.setdefault(session.session_id, observed_at)

        if reconciled != self._session_started_at:
            self._session_started_at = reconciled
            self._save_session_starts()

        self.playback_started_at = (
            min(reconciled.values()) if reconciled else None
        )

    def payload(self) -> dict[str, object]:
        payload = build_plex_api_payload(
            self.sessions,
            self.libraries,
            self.status,
        )
        payload["playback_started_at"] = self.playback_started_at
        return payload

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
        self._reconcile_session_starts(sessions)
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
