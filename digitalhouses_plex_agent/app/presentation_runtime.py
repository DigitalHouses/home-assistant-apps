from __future__ import annotations

import time
from datetime import datetime
from collections.abc import Callable, Mapping
from typing import Protocol

from .build_info import BuildInfoError, validate_version
from .models import BuildInfo, MonitorSnapshot
from .presentation_plex import PlexPresentationRouter, Publication


class ContractDataError(ValueError):
    pass


def _required_semver(value: object) -> str:
    try:
        return validate_version(value)
    except BuildInfoError as exc:
        raise ContractDataError("invalid required field: agent_version") from exc


def _required_timestamp(name: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ContractDataError(f"missing required field: {name}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractDataError(f"invalid required field: {name}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractDataError(
            f"invalid required field: {name} must be timezone-aware"
        )
    return value


def _required_api_status(payload: Mapping[str, object]) -> str:
    if "plex_api_status" not in payload:
        raise ContractDataError("missing required field: plex_api_status")
    value = payload["plex_api_status"]
    if value not in {"starting", "disabled", "ok", "error"}:
        raise ContractDataError("invalid required field: plex_api_status")
    return str(value)


class GroupBridge(Protocol):
    def publish_state_group(self, group: str, payload: dict[str, object]) -> bool: ...


class PlexPublicationRuntime:
    """Linux-agent publication runtime: cache, retry, grouped state and diagnostics."""

    def __init__(
        self,
        *,
        bridge: GroupBridge,
        build: BuildInfo,
        source_interval_seconds: float,
        high_cpu_threshold: float = 80.0,
        now_monotonic: Callable[[], float] = time.monotonic,
        server_boot_time: str | None = None,
        agent_started_at: str | None = None,
    ) -> None:
        self.bridge = bridge
        _required_semver(build.version)
        self.build = build
        self.source_interval_seconds = float(source_interval_seconds)
        self.now_monotonic = now_monotonic
        self.started_at = float(now_monotonic())
        self.server_boot_time = server_boot_time
        self.agent_started_at = _required_timestamp(
            "agent_started_at",
            agent_started_at,
        )
        self.router = PlexPresentationRouter(
            source_interval_seconds=self.source_interval_seconds,
            high_cpu_threshold=high_cpu_threshold,
        )
        self._published_groups: dict[str, dict[str, object]] = {}
        self._pending_groups: dict[str, dict[str, object]] = {}
        self._collector_status = "starting"
        self._plex_api_status = "starting"
        self._process_count = 0
        self._last_refresh: str | None = None
        self._last_collected_at: str | None = None
        self._last_publication: dict[str, object] = {
            "timestamp": None,
            "group": None,
            "reason": None,
            "profile": "normal",
            "group_count": 0,
        }

    @property
    def pending_groups(self) -> dict[str, dict[str, object]]:
        return dict(self._pending_groups)

    @property
    def has_cache(self) -> bool:
        return bool(self._published_groups)

    def _diagnostics_payload(self, now: float) -> dict[str, object]:
        return {
            "agent_version": self.build.version,
            "agent_uptime_seconds": max(0, int(float(now) - self.started_at)),
            "agent_started_at": self.agent_started_at,
            "server_boot_time": self.server_boot_time,
            "collector_status": self._collector_status,
            "plex_api_status": self._plex_api_status,
            "process_count": self._process_count,
            "last_refresh": self._last_refresh,
            "publication_profile": self.router.profile_summary(),
            "last_publication": dict(self._last_publication),
        }

    def _publish_diagnostics(self, *, now: float) -> bool:
        payload = self._diagnostics_payload(now)
        if self.bridge.publish_state_group("diagnostics", payload):
            self._published_groups["diagnostics"] = payload
            self._pending_groups.pop("diagnostics", None)
            return True
        self._pending_groups["diagnostics"] = payload
        return False

    def _record_publication(
        self,
        publications: list[Publication],
        *,
        reason: str | None = None,
        group_count: int | None = None,
    ) -> None:
        if not publications and reason is None:
            return
        last = publications[-1] if publications else None
        self._last_publication = {
            "timestamp": self._last_collected_at,
            "group": last.group if last is not None else "diagnostics",
            "reason": reason or (last.reason if last is not None else None),
            "profile": (
                last.profile.value
                if last is not None
                else self.router.profile_summary()["state"]
            ),
            "group_count": (
                int(group_count)
                if group_count is not None
                else len(publications)
            ),
        }

    def publish_snapshot(
        self,
        snapshot: MonitorSnapshot,
        api_payload: Mapping[str, object],
        *,
        gpu_payload: Mapping[str, object] | None = None,
        force: bool = False,
        manual_refresh: bool = False,
    ) -> bool:
        now = float(self.now_monotonic())
        old_status = (self._collector_status, self._plex_api_status)
        self._collector_status = snapshot.collector_status
        self._plex_api_status = _required_api_status(api_payload)
        self._process_count = int(snapshot.process_count)
        self._last_refresh = snapshot.last_refresh
        self._last_collected_at = snapshot.collected_at
        status_changed = old_status != (
            self._collector_status,
            self._plex_api_status,
        )

        pending_ok, retried = self._retry_pending_data()
        publications = list(
            self.router.route(
                snapshot,
                api_payload,
                gpu_payload,
                now=now,
                force=force,
                manual=manual_refresh,
            )
        )

        successful: list[Publication] = []
        failed = False
        for publication in publications:
            if self.bridge.publish_state_group(publication.group, publication.payload):
                self._published_groups[publication.group] = publication.payload
                self._pending_groups.pop(publication.group, None)
                successful.append(publication)
            else:
                self._pending_groups[publication.group] = publication.payload
                failed = True

        if failed or not pending_ok:
            return False

        if successful:
            reason = "manual_refresh" if manual_refresh else None
            self._record_publication(
                successful,
                reason=reason,
                group_count=len(retried) + len(successful),
            )
            return self._publish_diagnostics(now=now)

        if retried:
            self._last_publication = {
                "timestamp": self._last_collected_at,
                "group": retried[-1],
                "reason": "retry",
                "profile": self.router.profile_summary()["state"],
                "group_count": len(retried),
            }
            return self._publish_diagnostics(now=now)

        if status_changed:
            self._last_publication = {
                "timestamp": self._last_collected_at,
                "group": "diagnostics",
                "reason": "status_change",
                "profile": self.router.profile_summary()["state"],
                "group_count": 1,
            }
            return self._publish_diagnostics(now=now)

        return False

    def _retry_pending_data(self) -> tuple[bool, list[str]]:
        if not self._pending_groups:
            return True, []
        failed: dict[str, dict[str, object]] = {}
        retried: list[str] = []
        for group, payload in tuple(self._pending_groups.items()):
            if group == "diagnostics":
                continue
            if self.bridge.publish_state_group(group, payload):
                self._published_groups[group] = payload
                retried.append(group)
            else:
                failed[group] = payload
        if "diagnostics" in self._pending_groups:
            failed["diagnostics"] = self._pending_groups["diagnostics"]
        self._pending_groups = failed
        return not any(group != "diagnostics" for group in failed), retried

    def retry_pending(self) -> bool:
        now = float(self.now_monotonic())
        ok, retried = self._retry_pending_data()
        if not ok:
            return False
        if retried:
            self._last_publication = {
                "timestamp": self._last_collected_at,
                "group": retried[-1],
                "reason": "retry",
                "profile": self.router.profile_summary()["state"],
                "group_count": len(retried),
            }
        return self._publish_diagnostics(now=now)

    def republish_cached(self) -> bool:
        if not self._published_groups:
            return False
        now = float(self.now_monotonic())
        ok = True
        for group, payload in tuple(self._published_groups.items()):
            if group == "diagnostics":
                continue
            if not self.bridge.publish_state_group(group, payload):
                self._pending_groups[group] = payload
                ok = False
            else:
                self._pending_groups.pop(group, None)
        diagnostics_ok = self._publish_diagnostics(now=now)
        return ok and diagnostics_ok

    def publish_uptime_heartbeat(self) -> bool:
        return self._publish_diagnostics(now=float(self.now_monotonic()))
