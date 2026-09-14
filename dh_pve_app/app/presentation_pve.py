from __future__ import annotations

from collections.abc import Mapping

from .presentation_pve_base import PresentationSubsystem, Publication
from .presentation_pve_base import PvePresentationRouter as _BasePvePresentationRouter


class PvePresentationRouter(_BasePvePresentationRouter):
    """PVE presentation router with isolated host inventory and shutdown state."""

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
        shutdown_history = raw.pop("shutdown_history", None)
        result: list[Publication] = []

        host_publication = self._change_only(
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
        if host_publication is not None:
            result.append(host_publication)

        if shutdown_history is not None:
            shutdown_publication = self._change_only(
                group_name="shutdown",
                subsystem_name="host",
                state=state,
                semantic=shutdown_history,
                data={"shutdown_history": shutdown_history},
                now=now,
                collected_at=collected_at,
                last_refresh=last_refresh,
                force=force,
                manual=manual,
            )
            if shutdown_publication is not None:
                result.append(shutdown_publication)

        return result
