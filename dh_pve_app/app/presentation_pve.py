from __future__ import annotations

from collections.abc import Mapping, Sequence

from .presentation import PublicationProfile
from .presentation_policy import disk_profile_selector
from .presentation_pve_base import PresentationSubsystem, Publication, _mapping, _number, _slug
from .presentation_pve_base import PvePresentationRouter as _BasePvePresentationRouter


class PvePresentationRouter(_BasePvePresentationRouter):
    """PVE presentation router with isolated inventory, SMART and telemetry domains."""

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

    def _route_smart(
        self,
        state: PresentationSubsystem,
        *,
        now: float,
        collected_at: str,
        last_refresh: str | None,
        force: bool,
        manual: bool,
    ) -> list[Publication]:
        """HEALTH SMART is change-only; temperature telemetry is SLOW-owned."""
        result: list[Publication] = []
        for disk_id, disk_raw in sorted(_mapping(state.data).items()):
            disk = _mapping(disk_raw)
            status_data = dict(disk)
            status_data.pop("temperature_c", None)
            publication = self._change_only(
                group_name=f"disk/{_slug(disk_id)}/status",
                subsystem_name="smart",
                state=state,
                semantic=status_data,
                data={str(disk_id): status_data},
                now=now,
                collected_at=collected_at,
                last_refresh=last_refresh,
                force=force,
                manual=manual,
            )
            if publication is not None:
                result.append(publication)
        return result

    def _route_disk_temperature(
        self,
        state: PresentationSubsystem,
        *,
        now: float,
        collected_at: str,
        last_refresh: str | None,
        force: bool,
        manual: bool,
    ) -> list[Publication]:
        """Publish SLOW temperature to the existing disk telemetry MQTT contract."""
        result: list[Publication] = []
        for disk_id, disk_raw in sorted(_mapping(state.data).items()):
            disk = _mapping(disk_raw)
            disk_type = str(disk.get("disk_type") or "")
            temperature = _number(disk.get("temperature_c"))
            selector = self._disk_selectors.setdefault(
                str(disk_id), disk_profile_selector(disk_type)
            )
            choice = selector.observe(now=now, metrics={"temperature": temperature})
            profile_key = f"disk:{disk_id}"
            self._profiles[profile_key] = choice.profile
            self._profile_reasons[profile_key] = choice.reason

            stable = {
                key: disk.get(key)
                for key in ("disk_id", "disk_type", "model", "serial", "device_path")
                if disk.get(key) is not None
            }
            decision = self._group(
                f"disk/{_slug(disk_id)}/telemetry",
                source_interval_seconds=60.0,
            ).observe(
                now=now,
                continuous={"temperature_c": temperature},
                discrete={"available": state.available, "error": state.error, **stable},
                requested_profile=choice.profile,
                force=force,
                manual=manual,
            )
            if not decision.publish:
                continue

            telemetry_data = {**stable}
            if "temperature_c" in decision.values:
                telemetry_data["temperature_c"] = decision.values["temperature_c"]
            publication = self._publication(
                f"disk/{_slug(disk_id)}/telemetry",
                decision,
                # Discovery already reads disk temperature from the smart
                # namespace. Preserve that MQTT schema while acquisition lives
                # in the separate disk_temperature collector.
                "smart",
                state,
                {str(disk_id): telemetry_data},
                collected_at=collected_at,
                last_refresh=last_refresh,
            )
            if publication is not None:
                result.append(publication)
        return result

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
        selected_tuple = tuple(selected)
        # disk_temperature has a dedicated route. Keep it out of the base
        # fallback, otherwise it would become subsystem/disk_temperature.
        base_selected = tuple(name for name in selected_tuple if name != "disk_temperature")
        result = list(
            super().route(
                subsystems,
                selected=base_selected,
                now=now,
                collected_at=collected_at,
                last_refresh=last_refresh,
                force=force,
                manual=manual,
            )
        )

        if "storage" in selected_tuple:
            self._profiles["storage"] = PublicationProfile.NORMAL
            self._profile_reasons["storage"] = None

        if "disk_temperature" in selected_tuple:
            state = subsystems.get("disk_temperature")
            if state is not None:
                collector = self._collector_publication(
                    "disk_temperature",
                    state,
                    now=now,
                    collected_at=collected_at,
                    last_refresh=last_refresh,
                    force=force,
                    manual=manual,
                )
                if collector is not None:
                    result.append(collector)
                result.extend(
                    self._route_disk_temperature(
                        state,
                        now=now,
                        collected_at=collected_at,
                        last_refresh=last_refresh,
                        force=force,
                        manual=manual,
                    )
                )

        shutdown = self._route_shutdown(
            subsystems,
            selected=selected_tuple,
            now=now,
            collected_at=collected_at,
            last_refresh=last_refresh,
            force=force,
            manual=manual,
        )
        if shutdown is not None:
            result.append(shutdown)
        return tuple(result)
