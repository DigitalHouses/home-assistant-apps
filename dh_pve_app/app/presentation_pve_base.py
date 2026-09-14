from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Real

from .presentation import AdaptiveGroup, GroupDecision, ProfileWindows, PublicationProfile
from .presentation_policy import (
    ResourceProfileSelector,
    cpu_profile_selector,
    disk_profile_selector,
    gpu_profile_selector,
    memory_profile_selector,
)


@dataclass(frozen=True)
class PresentationSubsystem:
    available: bool
    data: object | None
    last_success: str | None
    error: str | None


@dataclass(frozen=True)
class Publication:
    group: str
    payload: dict[str, object]
    reason: str
    profile: PublicationProfile


_SEGMENT = re.compile(r"[^a-z0-9_.-]+")
_PROFILE_RANK = {
    PublicationProfile.QUIET: 0,
    PublicationProfile.NORMAL: 1,
    PublicationProfile.HIGH: 2,
    PublicationProfile.CRITICAL: 3,
}


def _slug(value: object) -> str:
    text = _SEGMENT.sub("_", str(value).casefold()).strip("_.-")
    return text or "unknown"


def _mapping(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def _number(value: object) -> float | None:
    if isinstance(value, Real) and not isinstance(value, bool):
        return float(value)
    return None


class PvePresentationRouter:
    """Convert raw PVE subsystem state into independent Recorder-facing groups."""

    def __init__(self, *, windows: ProfileWindows | None = None) -> None:
        self.windows = windows or ProfileWindows()
        self._groups: dict[str, AdaptiveGroup] = {}
        self._cpu_selector = cpu_profile_selector()
        self._memory_selector = memory_profile_selector()
        self._disk_selectors: dict[str, ResourceProfileSelector] = {}
        self._gpu_selectors: dict[str, ResourceProfileSelector] = {}
        self._profiles: dict[str, PublicationProfile] = {}
        self._profile_reasons: dict[str, str | None] = {}

    def _group(
        self,
        key: str,
        *,
        initial_profile: PublicationProfile = PublicationProfile.NORMAL,
        source_interval_seconds: float = 0.0,
        round_digits: int = 2,
    ) -> AdaptiveGroup:
        group = self._groups.get(key)
        if group is None:
            group = AdaptiveGroup(
                windows=self.windows,
                initial_profile=initial_profile,
                source_interval_seconds=source_interval_seconds,
                round_digits=round_digits,
            )
            self._groups[key] = group
        return group

    @staticmethod
    def _payload(
        subsystem_name: str,
        state: PresentationSubsystem,
        data: object,
        *,
        collected_at: str,
        last_refresh: str | None,
    ) -> dict[str, object]:
        return {
            "collected_at": collected_at,
            "last_refresh": last_refresh,
            "subsystems": {
                subsystem_name: {
                    "available": state.available,
                    "data": data,
                    "last_success": state.last_success,
                    "error": state.error,
                }
            },
        }

    def _publication(
        self,
        group_name: str,
        decision: GroupDecision,
        subsystem_name: str,
        state: PresentationSubsystem,
        data: object,
        *,
        collected_at: str,
        last_refresh: str | None,
    ) -> Publication | None:
        if not decision.publish or decision.reason is None:
            return None
        return Publication(
            group=group_name,
            payload=self._payload(
                subsystem_name,
                state,
                data,
                collected_at=collected_at,
                last_refresh=last_refresh,
            ),
            reason=decision.reason,
            profile=decision.profile,
        )

    def _change_only(
        self,
        *,
        group_name: str,
        subsystem_name: str,
        state: PresentationSubsystem,
        semantic: object,
        data: object,
        now: float,
        collected_at: str,
        last_refresh: str | None,
        force: bool,
        manual: bool,
    ) -> Publication | None:
        decision = self._group(group_name).observe(
            now=now,
            continuous={},
            discrete={"semantic": semantic},
            force=force,
            manual=manual,
        )
        return self._publication(
            group_name,
            decision,
            subsystem_name,
            state,
            data,
            collected_at=collected_at,
            last_refresh=last_refresh,
        )

    def _collector_publication(
        self,
        name: str,
        state: PresentationSubsystem,
        *,
        now: float,
        collected_at: str,
        last_refresh: str | None,
        force: bool,
        manual: bool,
    ) -> Publication | None:
        group_name = f"collector/{_slug(name)}"
        semantic = {"available": state.available, "error": state.error}
        data = {"collector": name, **semantic}
        return self._change_only(
            group_name=group_name,
            subsystem_name=name,
            state=state,
            semantic=semantic,
            data=data,
            now=now,
            collected_at=collected_at,
            last_refresh=last_refresh,
            force=force,
            manual=manual,
        )

    def _route_cpu(
        self,
        state: PresentationSubsystem,
        *,
        now: float,
        collected_at: str,
        last_refresh: str | None,
        force: bool,
        manual: bool,
    ) -> Publication | None:
        raw = _mapping(state.data)
        frequency = _mapping(raw.get("frequency"))
        usage = _number(raw.get("usage_percent"))
        temperature = _number(raw.get("temperature_c"))
        frequency_mhz = _number(frequency.get("average_mhz"))
        throttling = raw.get("throttling_active") is True
        choice = self._cpu_selector.observe(
            now=now,
            metrics={"usage": usage, "temperature": temperature},
            flags={"throttling": throttling},
        )
        self._profiles["cpu"] = choice.profile
        self._profile_reasons["cpu"] = choice.reason

        decision = self._group("cpu", source_interval_seconds=10.0).observe(
            now=now,
            continuous={
                "usage_percent": usage,
                "temperature_c": temperature,
                "frequency_mhz": frequency_mhz,
            },
            discrete={
                "available": state.available,
                "error": state.error,
                "throttling_active": throttling,
            },
            requested_profile=choice.profile,
            force=force,
            manual=manual,
        )
        if not decision.publish:
            return None
        values = decision.values
        data: dict[str, object] = {
            "usage_percent": values.get("usage_percent"),
            "temperature_c": values.get("temperature_c"),
            "throttling_active": values.get("throttling_active", throttling),
        }
        if "frequency_mhz" in values:
            data["frequency"] = {"average_mhz": values["frequency_mhz"]}
        return self._publication(
            "cpu", decision, "cpu", state, data,
            collected_at=collected_at, last_refresh=last_refresh,
        )

    def _route_memory(
        self,
        state: PresentationSubsystem,
        *,
        now: float,
        collected_at: str,
        last_refresh: str | None,
        force: bool,
        manual: bool,
    ) -> Publication | None:
        raw = _mapping(state.data)
        usage = _number(raw.get("usage_percent"))
        swap = _number(raw.get("swap_usage_percent"))
        choice = self._memory_selector.observe(now=now, metrics={"usage": usage})
        self._profiles["memory"] = choice.profile
        self._profile_reasons["memory"] = choice.reason
        stable = {
            "total_gib": raw.get("total_gib"),
            "swap_total_gib": raw.get("swap_total_gib"),
        }
        decision = self._group("memory", source_interval_seconds=10.0).observe(
            now=now,
            continuous={"usage_percent": usage, "swap_usage_percent": swap},
            discrete={"available": state.available, "error": state.error, **stable},
            requested_profile=choice.profile,
            force=force,
            manual=manual,
        )
        if not decision.publish:
            return None
        data = {
            "usage_percent": decision.values.get("usage_percent"),
            "swap_usage_percent": decision.values.get("swap_usage_percent"),
            **stable,
        }
        return self._publication(
            "memory", decision, "memory", state, data,
            collected_at=collected_at, last_refresh=last_refresh,
        )

    def _route_storage(
        self,
        state: PresentationSubsystem,
        *,
        now: float,
        collected_at: str,
        last_refresh: str | None,
        force: bool,
        manual: bool,
    ) -> list[Publication]:
        result: list[Publication] = []
        for storage_id, item_raw in sorted(_mapping(state.data).items()):
            item = _mapping(item_raw)
            group_name = f"storage/{_slug(storage_id)}"
            usage = _number(item.get("usage_percent"))
            stable = {
                key: item.get(key)
                for key in ("name", "type", "storage_type", "total_gib")
                if item.get(key) is not None
            }
            decision = self._group(
                group_name,
                initial_profile=PublicationProfile.QUIET,
                source_interval_seconds=60.0,
            ).observe(
                now=now,
                continuous={"usage_percent": usage},
                discrete={"available": state.available, "error": state.error, **stable},
                force=force,
                manual=manual,
            )
            if decision.publish:
                data = {"usage_percent": decision.values.get("usage_percent"), **stable}
                publication = self._publication(
                    group_name, decision, "storage", state, {str(storage_id): data},
                    collected_at=collected_at, last_refresh=last_refresh,
                )
                if publication is not None:
                    result.append(publication)
        return result

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
        result: list[Publication] = []
        for disk_id, disk_raw in sorted(_mapping(state.data).items()):
            disk = _mapping(disk_raw)
            segment = _slug(disk_id)
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
            telemetry_group = f"disk/{segment}/telemetry"
            telemetry_decision = self._group(
                telemetry_group, source_interval_seconds=60.0
            ).observe(
                now=now,
                continuous={"temperature_c": temperature},
                discrete={"available": state.available, "error": state.error, **stable},
                requested_profile=choice.profile,
                force=force,
                manual=manual,
            )
            if telemetry_decision.publish:
                telemetry_data = {**stable}
                if "temperature_c" in telemetry_decision.values:
                    telemetry_data["temperature_c"] = telemetry_decision.values["temperature_c"]
                publication = self._publication(
                    telemetry_group,
                    telemetry_decision,
                    "smart",
                    state,
                    {str(disk_id): telemetry_data},
                    collected_at=collected_at,
                    last_refresh=last_refresh,
                )
                if publication is not None:
                    result.append(publication)

            status_data = dict(disk)
            status_data.pop("temperature_c", None)
            status_group = f"disk/{segment}/status"
            status_publication = self._change_only(
                group_name=status_group,
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
            if status_publication is not None:
                result.append(status_publication)
        return result

    def _route_gpu(
        self,
        state: PresentationSubsystem,
        *,
        now: float,
        collected_at: str,
        last_refresh: str | None,
        force: bool,
        manual: bool,
    ) -> list[Publication]:
        result: list[Publication] = []
        for gpu_id, gpu_raw in sorted(_mapping(state.data).items()):
            gpu = _mapping(gpu_raw)
            segment = _slug(gpu_id)
            temperature = _number(gpu.get("temperature_c"))
            load = _number(gpu.get("transcoding_load_percent"))
            selector = self._gpu_selectors.setdefault(str(gpu_id), gpu_profile_selector())
            choice = selector.observe(
                now=now, metrics={"temperature": temperature, "load": load}
            )
            profile_key = f"gpu:{gpu_id}"
            self._profiles[profile_key] = choice.profile
            self._profile_reasons[profile_key] = choice.reason

            stable = {
                key: gpu.get(key)
                for key in ("gpu_id", "pci_address", "vendor", "model")
                if gpu.get(key) is not None
            }
            telemetry_group = f"gpu/{segment}/telemetry"
            telemetry_decision = self._group(
                telemetry_group, source_interval_seconds=30.0
            ).observe(
                now=now,
                continuous={
                    "temperature_c": temperature,
                    "transcoding_load_percent": load,
                },
                discrete={"available": state.available, "error": state.error, **stable},
                requested_profile=choice.profile,
                force=force,
                manual=manual,
            )
            if telemetry_decision.publish:
                telemetry_data = {**stable}
                for key in ("temperature_c", "transcoding_load_percent"):
                    if key in telemetry_decision.values:
                        telemetry_data[key] = telemetry_decision.values[key]
                publication = self._publication(
                    telemetry_group,
                    telemetry_decision,
                    "gpu",
                    state,
                    {str(gpu_id): telemetry_data},
                    collected_at=collected_at,
                    last_refresh=last_refresh,
                )
                if publication is not None:
                    result.append(publication)

            status_data = {
                key: value
                for key, value in gpu.items()
                if key not in {"temperature_c", "transcoding_load_percent"}
            }
            status_publication = self._change_only(
                group_name=f"gpu/{segment}/status",
                subsystem_name="gpu",
                state=state,
                semantic=status_data,
                data={str(gpu_id): status_data},
                now=now,
                collected_at=collected_at,
                last_refresh=last_refresh,
                force=force,
                manual=manual,
            )
            if status_publication is not None:
                result.append(status_publication)
        return result

    def _route_fans(
        self,
        state: PresentationSubsystem,
        *,
        now: float,
        collected_at: str,
        last_refresh: str | None,
        force: bool,
        manual: bool,
    ) -> list[Publication]:
        raw = _mapping(state.data)
        result: list[Publication] = []

        summary = {
            key: raw.get(key)
            for key in ("detected", "count", "status")
            if key in raw
        }
        summary_publication = self._change_only(
            group_name="fans",
            subsystem_name="fans",
            state=state,
            semantic=summary,
            data=summary,
            now=now,
            collected_at=collected_at,
            last_refresh=last_refresh,
            force=force,
            manual=manual,
        )
        if summary_publication is not None:
            result.append(summary_publication)

        for fan_id, fan_raw in sorted(raw.items()):
            if fan_id in {"detected", "count", "status"}:
                continue
            if not isinstance(fan_raw, Mapping):
                continue
            fan = _mapping(fan_raw)
            rpm = _number(fan.get("rpm"))
            stable = {
                key: fan.get(key)
                for key in ("fan_id", "name", "label", "source")
                if fan.get(key) is not None
            }
            group_name = f"fan/{_slug(fan_id)}"
            decision = self._group(
                group_name, source_interval_seconds=10.0, round_digits=0
            ).observe(
                now=now,
                continuous={"rpm": rpm},
                discrete={"available": state.available, "error": state.error, **stable},
                force=force,
                manual=manual,
            )
            if decision.publish:
                data = {**stable}
                if "rpm" in decision.values:
                    data["rpm"] = decision.values["rpm"]
                publication = self._publication(
                    group_name, decision, "fans", state, {str(fan_id): data},
                    collected_at=collected_at, last_refresh=last_refresh,
                )
                if publication is not None:
                    result.append(publication)
        return result

    def _route_guests(
        self,
        state: PresentationSubsystem,
        *,
        now: float,
        collected_at: str,
        last_refresh: str | None,
        force: bool,
        manual: bool,
    ) -> list[Publication]:
        raw = _mapping(state.data)
        result: list[Publication] = []
        for plural, singular in (("vms", "vm"), ("lxcs", "lxc")):
            for guest_id, guest_raw in sorted(_mapping(raw.get(plural)).items()):
                guest = _mapping(guest_raw)
                publication = self._change_only(
                    group_name=f"guest/{singular}/{_slug(guest_id)}",
                    subsystem_name="guests",
                    state=state,
                    semantic=guest,
                    data={plural: {str(guest_id): guest}},
                    now=now,
                    collected_at=collected_at,
                    last_refresh=last_refresh,
                    force=force,
                    manual=manual,
                )
                if publication is not None:
                    result.append(publication)
        summary = _mapping(raw.get("summary"))
        publication = self._change_only(
            group_name="guest/summary",
            subsystem_name="guests",
            state=state,
            semantic=summary,
            data={"summary": summary},
            now=now,
            collected_at=collected_at,
            last_refresh=last_refresh,
            force=force,
            manual=manual,
        )
        if publication is not None:
            result.append(publication)
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
        publication = self._change_only(
            group_name=group_name,
            subsystem_name=name,
            state=state,
            semantic=state.data,
            data=state.data,
            now=now,
            collected_at=collected_at,
            last_refresh=last_refresh,
            force=force,
            manual=manual,
        )
        return [] if publication is None else [publication]

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
        result: list[Publication] = []
        for name in selected:
            state = subsystems.get(name)
            if state is None:
                continue

            collector = self._collector_publication(
                name,
                state,
                now=now,
                collected_at=collected_at,
                last_refresh=last_refresh,
                force=force,
                manual=manual,
            )
            if collector is not None:
                result.append(collector)

            if name == "cpu":
                publication = self._route_cpu(
                    state, now=now, collected_at=collected_at,
                    last_refresh=last_refresh, force=force, manual=manual,
                )
                if publication is not None:
                    result.append(publication)
            elif name == "memory":
                publication = self._route_memory(
                    state, now=now, collected_at=collected_at,
                    last_refresh=last_refresh, force=force, manual=manual,
                )
                if publication is not None:
                    result.append(publication)
            elif name == "storage":
                result.extend(self._route_storage(
                    state, now=now, collected_at=collected_at,
                    last_refresh=last_refresh, force=force, manual=manual,
                ))
            elif name == "smart":
                result.extend(self._route_smart(
                    state, now=now, collected_at=collected_at,
                    last_refresh=last_refresh, force=force, manual=manual,
                ))
            elif name == "gpu":
                result.extend(self._route_gpu(
                    state, now=now, collected_at=collected_at,
                    last_refresh=last_refresh, force=force, manual=manual,
                ))
            elif name == "fans":
                result.extend(self._route_fans(
                    state, now=now, collected_at=collected_at,
                    last_refresh=last_refresh, force=force, manual=manual,
                ))
            elif name == "guests":
                result.extend(self._route_guests(
                    state, now=now, collected_at=collected_at,
                    last_refresh=last_refresh, force=force, manual=manual,
                ))
            elif name == "host":
                result.extend(self._route_change_subsystem(
                    name, state, group_name="host", now=now,
                    collected_at=collected_at, last_refresh=last_refresh,
                    force=force, manual=manual,
                ))
            elif name == "topology":
                result.extend(self._route_change_subsystem(
                    name, state, group_name="topology", now=now,
                    collected_at=collected_at, last_refresh=last_refresh,
                    force=force, manual=manual,
                ))
            else:
                result.extend(self._route_change_subsystem(
                    name, state, group_name=f"subsystem/{_slug(name)}", now=now,
                    collected_at=collected_at, last_refresh=last_refresh,
                    force=force, manual=manual,
                ))
        return tuple(result)

    def profile_summary(self) -> dict[str, object]:
        if not self._profiles:
            return {"state": PublicationProfile.NORMAL.value, "resources": {}, "reason": None}
        highest = max(self._profiles.values(), key=_PROFILE_RANK.__getitem__)
        resources = {
            key: profile.value
            for key, profile in sorted(self._profiles.items())
        }
        reason = None
        for key in sorted(self._profiles):
            if self._profiles[key] is not highest:
                continue
            candidate = self._profile_reasons.get(key)
            if candidate:
                reason = f"{key}:{candidate}"
                break
        return {"state": highest.value, "resources": resources, "reason": reason}
