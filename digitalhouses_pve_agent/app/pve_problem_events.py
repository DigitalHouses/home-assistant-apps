from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .problems import ProblemState, ProblemTransition


PVE_USER_EVENT_TYPES = (
    "cpu_temperature_high",
    "cpu_temperature_normal",
    "cpu_throttling_started",
    "cpu_throttling_cleared",
    "storage_usage_high",
    "storage_usage_normal",
    "disk_temperature_high",
    "disk_temperature_normal",
    "gpu_temperature_high",
    "gpu_temperature_normal",
    "fan_control_restore_failed",
    "fan_control_restored",
    "disk_smart_failed",
    "disk_smart_restored",
)


def _event_type(transition: ProblemTransition) -> str | None:
    state = transition.current
    started = transition.event_type == "problem_started"
    recovered = transition.event_type == "problem_recovered"
    if not (started or recovered):
        return None

    if state.problem_id == "cpu_temperature":
        return "cpu_temperature_high" if started else "cpu_temperature_normal"
    if state.problem_id == "cpu_throttling":
        return "cpu_throttling_started" if started else "cpu_throttling_cleared"
    if state.problem_id.startswith("storage_") and state.metric == "percent_used":
        return "storage_usage_high" if started else "storage_usage_normal"
    if (
        state.problem_id.startswith("disk_")
        and state.problem_id.endswith("_temperature")
        and state.metric == "temperature_c"
    ):
        return "disk_temperature_high" if started else "disk_temperature_normal"
    if (
        state.problem_id.startswith("gpu_")
        and state.problem_id.endswith("_temperature")
        and state.metric == "temperature_c"
    ):
        return "gpu_temperature_high" if started else "gpu_temperature_normal"
    if (
        state.problem_id.startswith("fan_")
        and state.problem_id.endswith("_control_restore")
    ):
        return "fan_control_restore_failed" if started else "fan_control_restored"
    if (
        state.problem_id.startswith("disk_")
        and state.problem_id.endswith("_smart")
        and state.metric == "smart_passed"
    ):
        return "disk_smart_failed" if started else "disk_smart_restored"
    return None


def _state_payload(state: ProblemState | None) -> dict[str, object] | None:
    if state is None:
        return None
    return {
        "active": state.active,
        "value": state.value,
        "average": state.average,
        "threshold": state.threshold,
    }


def semantic_pve_problem_event(
    transition: ProblemTransition,
    *,
    observed_at: str,
    context: Mapping[str, object] | None = None,
    active_problem_count: int | None = None,
) -> dict[str, object]:
    event_type = _event_type(transition)
    if event_type is None:
        raise ValueError(
            f"unsupported PVE problem transition: "
            f"{transition.current.problem_id}/{transition.event_type}"
        )

    state = transition.current
    payload: dict[str, object] = {
        "schema_version": 2,
        "event_type": event_type,
        "observed_at": observed_at,
        "problem_id": state.problem_id,
        "category": state.category,
        "severity": state.severity,
        "object_id": state.object_id,
        "object_name": state.object_name,
        "metric": state.metric,
        "value": state.value,
        "average": state.average,
        "threshold": state.threshold,
        "previous": _state_payload(transition.previous),
        "current": _state_payload(state),
    }
    if active_problem_count is not None:
        payload["active_problem_count"] = active_problem_count

    if state.metric == "temperature_c":
        payload.update(
            {
                "temperature_c": state.value,
                "average_temperature_c": state.average,
                "threshold_c": state.threshold,
            }
        )
    elif state.metric == "percent_used":
        payload.update(
            {
                "used_percent": state.value,
                "average_used_percent": state.average,
                "threshold_percent": state.threshold,
            }
        )

    if context:
        payload.update(
            {
                str(key): value
                for key, value in context.items()
                if value is not None
            }
        )
    return payload


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def pve_problem_context(
    state: ProblemState,
    subsystem_states: Mapping[str, object],
) -> dict[str, object]:
    """Return event-time assessment data for the concrete PVE problem."""

    context: dict[str, object] = {}

    if state.problem_id.startswith("cpu_"):
        cpu = _mapping(subsystem_states.get("cpu"))
        frequency = _mapping(cpu.get("frequency"))
        context.update(
            {
                "temperature_c": cpu.get("temperature_c"),
                "cpu_frequency_mhz": frequency.get("average_mhz"),
                "cpu_usage_percent": cpu.get("usage_percent"),
            }
        )
        throttling = _mapping(cpu.get("throttling"))
        for key in (
            "counter_source",
            "count_since_boot",
            "time_since_boot_ms",
        ):
            if throttling.get(key) is not None:
                context[f"throttling_{key}"] = throttling.get(key)

    elif state.category == "storage":
        storage = _mapping(subsystem_states.get("storage"))
        item = _mapping(storage.get(state.object_id))
        for source_key, target_key in (
            ("storage_type", "storage_type"),
            ("status", "storage_status"),
            ("total_gib", "total_gib"),
            ("used_gib", "used_gib"),
            ("available_gib", "available_gib"),
            ("usage_percent", "used_percent"),
        ):
            if item.get(source_key) is not None:
                context[target_key] = item.get(source_key)

    elif state.category == "disk" and state.metric == "temperature_c":
        disks = _mapping(subsystem_states.get("disk_temperature"))
        item = _mapping(disks.get(state.object_id))
        for key in (
            "disk_type",
            "model",
            "serial",
            "device_path",
            "source_type",
            "source_guest_id",
            "source_guest_name",
            "temperature_c",
        ):
            if item.get(key) is not None:
                context[key] = item.get(key)

    elif state.category == "gpu":
        gpus = _mapping(subsystem_states.get("gpu"))
        item = _mapping(gpus.get(state.object_id))
        for key in (
            "display_name",
            "model",
            "owner",
            "source_type",
            "source_id",
            "source_name",
            "temperature_c",
            "transcoding_load_percent",
        ):
            if item.get(key) is not None:
                context[key] = item.get(key)

    elif state.category == "fan":
        fans = _mapping(subsystem_states.get("fans"))
        item = _mapping(fans.get(state.object_id))
        for key in (
            "label",
            "display_name",
            "rpm",
            "calibration_status",
        ):
            if item.get(key) is not None:
                context[key] = item.get(key)

    elif state.category == "disk" and state.metric == "smart_passed":
        smart = _mapping(subsystem_states.get("smart"))
        item = _mapping(smart.get(state.object_id))
        for key in (
            "disk_type",
            "model",
            "serial",
            "device_path",
            "temperature_c",
            "wear_used_percent",
            "life_remaining_percent",
            "power_on_hours",
            "data_written_tb",
            "critical_warning",
            "media_errors",
            "error_log_entries",
            "unsafe_shutdowns",
            "reallocated_sectors",
            "pending_sectors",
            "offline_uncorrectable",
            "uncorrectable_errors",
            "crc_errors",
            "health_state",
            "health_reasons",
            "recommendation",
        ):
            if item.get(key) is not None:
                context[key] = item.get(key)

    return context


@dataclass
class _Pending:
    transition: ProblemTransition
    due_at: float


class PveProblemEventDebouncer:
    """Debounce user-facing PVE start/recovery events.

    Retained problem state may update immediately. Notifications are emitted
    only after the state has remained unchanged for delay_seconds.
    """

    def __init__(self, *, delay_seconds: float) -> None:
        self.delay_seconds = max(0.0, float(delay_seconds))
        self._pending: dict[str, _Pending] = {}
        self._notified_active: set[str] = set()

    def observe(self, transition: ProblemTransition, *, now: float) -> None:
        problem_id = transition.current.problem_id
        event_type = transition.event_type

        if event_type == "problem_started":
            pending = self._pending.get(problem_id)
            if pending is not None and pending.transition.event_type == "problem_recovered":
                self._pending.pop(problem_id, None)
                if problem_id in self._notified_active:
                    return
            if problem_id in self._notified_active:
                return
            self._pending[problem_id] = _Pending(
                transition=transition,
                due_at=float(now) + self.delay_seconds,
            )
            return

        if event_type == "problem_recovered":
            pending = self._pending.get(problem_id)
            if pending is not None and pending.transition.event_type == "problem_started":
                self._pending.pop(problem_id, None)
                if problem_id not in self._notified_active:
                    return
            if problem_id not in self._notified_active:
                return
            self._pending[problem_id] = _Pending(
                transition=transition,
                due_at=float(now) + self.delay_seconds,
            )

    def due(
        self,
        *,
        now: float,
        current_states: Mapping[str, ProblemState],
    ) -> tuple[ProblemTransition, ...]:
        ready: list[ProblemTransition] = []
        for problem_id in sorted(self._pending):
            pending = self._pending[problem_id]
            if float(now) < pending.due_at:
                continue
            current = current_states.get(problem_id)
            expected_active = pending.transition.event_type == "problem_started"
            if current is None or current.active != expected_active:
                continue
            ready.append(
                ProblemTransition(
                    pending.transition.event_type,
                    pending.transition.previous,
                    current,
                )
            )
        return tuple(ready)

    def acknowledge(self, transition: ProblemTransition) -> None:
        problem_id = transition.current.problem_id
        pending = self._pending.get(problem_id)
        if pending is None:
            return
        if transition.event_type == "problem_started":
            self._notified_active.add(problem_id)
        elif transition.event_type == "problem_recovered":
            self._notified_active.discard(problem_id)
        self._pending.pop(problem_id, None)
