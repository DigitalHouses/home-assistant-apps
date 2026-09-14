from __future__ import annotations

from collections.abc import Mapping, Sequence

from .presentation_pve_base import PresentationSubsystem, Publication
from .presentation_pve_base import PvePresentationRouter as _BasePvePresentationRouter


class PvePresentationRouter(_BasePvePresentationRouter):
    """PVE presentation router with isolated host inventory and shutdown state."""

    @staticmethod
    def _guest_shutdown_config(state: PresentationSubsystem | None) -> dict[str, object]:
        raw = state.data if state is not None and isinstance(state.data, Mapping) else {}
        result: dict[str, object] = {"vms": {}, "lxcs": {}}
        for plural in ("vms", "lxcs"):
            records = raw.get(plural)
            if not isinstance(records, Mapping):
                continue
            compact: dict[str, object] = {}
            for guest_id, guest_raw in records.items():
                if not isinstance(guest_raw, Mapping):
                    continue
                compact[str(guest_id)] = {
                    "shutdown_timeout_seconds": guest_raw.get("shutdown_timeout_seconds"),
                    "shutdown_order": guest_raw.get("shutdown_order"),
                    "onboot": guest_raw.get("onboot", False),
                }
            result[plural] = compact
        return result

    def _route_change_subsystem(
        self,
        name: str,
        state: PresentationSubsystem,
        *,
        group_name: str,
        now: float,
        collected_at: str,
        last_refresh: str | None,
        force: bool,
        manual: bool,
    ) -> list[Publication]:
        if name != "host" or group_name != "host":
            return super()._route_change_subsystem(
                name,
                state,
                group_name=group_name,
                now=now,
                collected_at=collected_at,
                last_refresh=last_refresh,
                force=force,
                manual=manual,
            )

        raw = dict(state.data) if isinstance(state.data, Mapping) else {}
        raw.pop("shutdown_history", None)
        publication = self._change_only(
            group_name="host",
            subsystem_name="host",
            state=state,
            semantic=raw,
            data=raw,
            now=now,
            collected_at=collected_at,
            last_refresh=last_refresh,
            force=force,
            manual=manual,
        )
        return [] if publication is None else [publication]

    def _route_shutdown(
        self,
        subsystems: Mapping[str, PresentationSubsystem],
        *,
        selected: Sequence[str],
        now: float,
        collected_at: str,
        last_refresh: str | None,
        force: bool,
        manual: bool,
    ) -> Publication | None:
        if "host" not in selected and "guests" not in selected:
            return None

        host = subsystems.get("host")
        if host is None or not isinstance(host.data, Mapping):
            return None
        shutdown_history = host.data.get("shutdown_history")
        if shutdown_history is None:
            return None

        data = {
            "shutdown_history": shutdown_history,
            "guest_config": self._guest_shutdown_config(subsystems.get("guests")),
        }
        return self._change_only(
            group_name="shutdown",
            subsystem_name="host",
            state=host,
            semantic=data,
            data=data,
            now=now,
            collected_at=collected_at,
            last_refresh=last_refresh,
            force=force,
            manual=manual,
        )

    def route(
        self,
        subsystems: Mapping[str, PresentationSubsystem],
        *,
        selected: Sequence[str],
        now: float,
        collected_at: str,
        last_refresh: str | None,
        force: bool = False,
        manual: bool = False,
    ) -> tuple[Publication, ...]:
        result = list(
            super().route(
                subsystems,
                selected=selected,
                now=now,
                collected_at=collected_at,
                last_refresh=last_refresh,
                force=force,
                manual=manual,
            )
        )
        shutdown = self._route_shutdown(
            subsystems,
            selected=selected,
            now=now,
            collected_at=collected_at,
            last_refresh=last_refresh,
            force=force,
            manual=manual,
        )
        if shutdown is not None:
            result.append(shutdown)
        return tuple(result)
