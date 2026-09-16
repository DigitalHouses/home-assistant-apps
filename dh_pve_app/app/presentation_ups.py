from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .presentation import AdaptiveGroup, ProfileWindows, PublicationProfile
from .presentation_policy import ups_profile_selector


@dataclass(frozen=True)
class UpsPublication:
    group: str
    payload: dict[str, object]
    reason: str
    profile: PublicationProfile


_TELEMETRY_FIELDS = (
    "battery_charge_percent",
    "battery_runtime_minutes",
    "runtime_seconds",
    "battery_voltage_v",
    "load_percent",
    "input_voltage_v",
    "output_voltage_v",
    "input_frequency_hz",
    "output_frequency_hz",
)

_STATUS_FIELDS = (
    "available",
    "status",
    "error",
    "status_raw",
    "status_tokens",
    "line_power",
    "on_battery",
    "low_battery",
    "replace_battery",
    "overload",
    "bypass",
    "charging",
    "discharging",
    "problems_count",
    "problems_severity",
    "problems",
    "problems_details",
)

_CONFIG_FIELDS = (
    "manufacturer",
    "model",
    "serial",
    "driver_name",
    "driver_version",
    "driver_data",
    "battery_nominal_voltage_v",
    "nominal_real_power_w",
    "input_nominal_voltage_v",
    "input_transfer_high_v",
    "input_transfer_low_v",
    "warning_charge_percent",
    "low_charge_percent",
    "low_runtime_seconds",
    "ups_shutdown_delay_seconds",
    "ups_start_delay_seconds",
    "capabilities",
    "shutdown_policy",
    "policy",
)

_TEST_FIELDS = (
    "test_result",
    "beeper_status",
    "test_schedule",
    "test_history",
)

_DIAGNOSTIC_FIELDS = (
    "last_refresh",
    "shutdown_readiness",
    "shutdown_budget",
)


def _selected(payload: Mapping[str, object], fields: tuple[str, ...]) -> dict[str, object]:
    return {key: payload[key] for key in fields if key in payload}


def _numeric(payload: Mapping[str, object], fields: tuple[str, ...]) -> dict[str, object]:
    return {key: payload.get(key) for key in fields}


class UpsPresentationRouter:
    """Partition one raw UPS snapshot into independent Recorder-facing groups."""

    def __init__(
        self,
        *,
        windows: ProfileWindows | None = None,
        source_interval_seconds: float = 5.0,
    ) -> None:
        self.windows = windows or ProfileWindows()
        self.source_interval_seconds = max(0.0, float(source_interval_seconds))
        self.selector = ups_profile_selector()
        self.telemetry = AdaptiveGroup(
            windows=self.windows,
            source_interval_seconds=self.source_interval_seconds,
        )
        self.change_groups = {
            name: AdaptiveGroup(windows=self.windows)
            for name in ("status", "config", "tests", "diagnostics")
        }
        self._profile_reason: str | None = None

    @staticmethod
    def _publication(group: str, decision, data: Mapping[str, object]) -> UpsPublication | None:
        if not decision.publish or decision.reason is None:
            return None
        return UpsPublication(
            group=group,
            payload=dict(data),
            reason=decision.reason,
            profile=decision.profile,
        )

    def _change_only(
        self,
        group: str,
        data: Mapping[str, object],
        *,
        now: float,
        force: bool,
        manual: bool,
    ) -> UpsPublication | None:
        decision = self.change_groups[group].observe(
            now=now,
            continuous={},
            discrete={"semantic": dict(data)},
            force=force,
            manual=manual,
        )
        return self._publication(group, decision, data)

    def route(
        self,
        payload: Mapping[str, object],
        *,
        now: float,
        force: bool = False,
        manual: bool = False,
    ) -> tuple[UpsPublication, ...]:
        load = payload.get("load_percent")
        choice = self.selector.observe(
            now=now,
            metrics={"load": load},
            flags={
                "on_battery": payload.get("on_battery") is True,
                "bypass": payload.get("bypass") is True,
                "low_battery": payload.get("low_battery") is True,
                "overload": payload.get("overload") is True,
            },
        )
        self._profile_reason = choice.reason

        publications: list[UpsPublication] = []
        telemetry_decision = self.telemetry.observe(
            now=now,
            continuous=_numeric(payload, _TELEMETRY_FIELDS),
            requested_profile=choice.profile,
            force=force,
            manual=manual,
        )
        if telemetry_decision.publish:
            telemetry_payload = {
                key: value
                for key, value in telemetry_decision.values.items()
                if key in _TELEMETRY_FIELDS
            }
            publication = self._publication(
                "telemetry", telemetry_decision, telemetry_payload
            )
            if publication is not None:
                publications.append(publication)

        for group, fields in (
            ("status", _STATUS_FIELDS),
            ("config", _CONFIG_FIELDS),
            ("tests", _TEST_FIELDS),
            ("diagnostics", _DIAGNOSTIC_FIELDS),
        ):
            data = _selected(payload, fields)
            publication = self._change_only(
                group,
                data,
                now=now,
                force=force,
                manual=manual,
            )
            if publication is not None:
                publications.append(publication)

        return tuple(publications)

    def profile_summary(self) -> dict[str, object]:
        return {
            "profile": self.selector.profile.value,
            "reason": self._profile_reason,
        }
