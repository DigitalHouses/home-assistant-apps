from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Real

from .runtime_windows import RollingAverage


@dataclass(frozen=True)
class ProblemState:
    problem_id: str
    category: str
    severity: str
    object_id: str
    object_name: str
    metric: str
    active: bool
    value: object | None
    average: float | None
    threshold: float | None
    summary: str
    details: str


@dataclass(frozen=True)
class ProblemTransition:
    event_type: str
    previous: ProblemState | None
    current: ProblemState


@dataclass(frozen=True)
class ProblemAggregate:
    count: int
    severity: str
    summary: str
    active: tuple[dict[str, object], ...]


@dataclass
class _NumericBinding:
    problem_id: str
    category: str
    severity: str
    object_id: str
    object_name: str
    metric: str
    threshold_key: str
    window_seconds: float
    unit: str
    label: str
    average_window: RollingAverage
    first_seen: float | None = None
    last_now: float | None = None
    last_value: float | None = None


_SLUG = re.compile(r"[^a-z0-9]+")
_SEVERITY_RANK = {"ok": 0, "info": 1, "warning": 2, "critical": 3}
_DISK_THRESHOLDS = {
    "HDD": "hdd_temperature_threshold",
    "SSD": "ssd_temperature_threshold",
    "NVME": "nvme_temperature_threshold",
}


def _slug(value: object) -> str:
    text = _SLUG.sub("_", str(value).casefold()).strip("_")
    return text or "unknown"


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    data = getattr(value, "data", None)
    return data if isinstance(data, Mapping) else {}


def _compact(state: ProblemState) -> dict[str, object]:
    return {
        "problem_id": state.problem_id,
        "category": state.category,
        "severity": state.severity,
        "object_id": state.object_id,
        "object_name": state.object_name,
        "metric": state.metric,
        "value": state.value,
        "average": state.average,
        "threshold": state.threshold,
        "summary": state.summary,
        "details": state.details,
    }


class PveProblemEngine:
    """Own PVE alert decisions without changing collection cadence.

    Continuous problems reuse the runtime foundation's RollingAverage and only
    become decision-ready after a complete 60/300 second window. Invalid or
    missing numeric samples neither become zero nor force recovery. Discrete
    SMART/throttling problems transition immediately.
    """

    def __init__(self) -> None:
        self._states: dict[str, ProblemState] = {}
        self._numeric: dict[str, _NumericBinding] = {}
        self._thresholds: dict[str, float] = {}

    def problem(self, problem_id: str) -> ProblemState | None:
        return self._states.get(problem_id)

    def _threshold(self, key: str, values: Mapping[str, object]) -> float | None:
        candidate = _finite(values.get(key))
        if candidate is not None:
            self._thresholds[key] = candidate
            return candidate
        return self._thresholds.get(key)

    def _binding(
        self,
        *,
        problem_id: str,
        category: str,
        severity: str,
        object_id: str,
        object_name: str,
        metric: str,
        threshold_key: str,
        window_seconds: float,
        unit: str,
        label: str,
    ) -> _NumericBinding:
        binding = self._numeric.get(problem_id)
        if binding is None:
            binding = _NumericBinding(
                problem_id=problem_id,
                category=category,
                severity=severity,
                object_id=object_id,
                object_name=object_name,
                metric=metric,
                threshold_key=threshold_key,
                window_seconds=float(window_seconds),
                unit=unit,
                label=label,
                average_window=RollingAverage(window_seconds),
            )
            self._numeric[problem_id] = binding
        else:
            binding.object_name = object_name
            binding.label = label
        return binding

    @staticmethod
    def _active_from_average(
        average: float,
        threshold: float,
        previous: ProblemState | None,
    ) -> bool:
        if average > threshold:
            return True
        if average < threshold:
            return False
        return previous.active if previous is not None else False

    @staticmethod
    def _numeric_text(label: str, active: bool) -> str:
        return f"{label} high" if active else f"{label} OK"

    @staticmethod
    def _numeric_details(average: float, threshold: float, unit: str) -> str:
        suffix = f" {unit}" if unit else ""
        return f"Average {average:g}{suffix}; threshold {threshold:g}{suffix}"

    def _commit(
        self,
        state: ProblemState,
        *,
        emit_update: bool = False,
    ) -> ProblemTransition | None:
        previous = self._states.get(state.problem_id)
        self._states[state.problem_id] = state
        if previous is None:
            if state.active:
                return ProblemTransition("problem_started", None, state)
            return None
        if previous.active != state.active:
            return ProblemTransition(
                "problem_started" if state.active else "problem_recovered",
                previous,
                state,
            )
        if emit_update and state.active and state != previous:
            return ProblemTransition("problem_updated", previous, state)
        return None

    def _observe_numeric(
        self,
        *,
        now: float,
        value: object,
        thresholds: Mapping[str, object],
        problem_id: str,
        category: str,
        severity: str,
        object_id: str,
        object_name: str,
        metric: str,
        threshold_key: str,
        window_seconds: float,
        unit: str,
        label: str,
    ) -> ProblemTransition | None:
        binding = self._binding(
            problem_id=problem_id,
            category=category,
            severity=severity,
            object_id=object_id,
            object_name=object_name,
            metric=metric,
            threshold_key=threshold_key,
            window_seconds=window_seconds,
            unit=unit,
            label=label,
        )
        numeric = _finite(value)
        binding.average_window.observe(now, numeric)
        binding.last_now = float(now)
        if numeric is not None:
            binding.last_value = numeric
            if binding.first_seen is None:
                binding.first_seen = float(now)

        threshold = self._threshold(threshold_key, thresholds)
        average = binding.average_window.average(now)
        if (
            threshold is None
            or average is None
            or binding.first_seen is None
            or float(now) - binding.first_seen < binding.window_seconds
        ):
            return None

        average = round(float(average), 3)
        previous = self._states.get(problem_id)
        active = self._active_from_average(average, threshold, previous)
        state = ProblemState(
            problem_id=problem_id,
            category=category,
            severity=severity,
            object_id=object_id,
            object_name=object_name,
            metric=metric,
            active=active,
            value=binding.last_value,
            average=average,
            threshold=threshold,
            summary=self._numeric_text(label, active),
            details=self._numeric_details(average, threshold, unit),
        )
        return self._commit(state)

    def _observe_discrete(
        self,
        *,
        problem_id: str,
        category: str,
        severity: str,
        object_id: str,
        object_name: str,
        metric: str,
        active: bool,
        label: str,
        value: object,
    ) -> ProblemTransition | None:
        state = ProblemState(
            problem_id=problem_id,
            category=category,
            severity=severity,
            object_id=object_id,
            object_name=object_name,
            metric=metric,
            active=bool(active),
            value=value,
            average=None,
            threshold=None,
            summary=f"{label} problem" if active else f"{label} OK",
            details=f"{label}: {'problem active' if active else 'OK'}",
        )
        return self._commit(state)

    def observe(
        self,
        now: float,
        subsystem_states: Mapping[str, object],
        thresholds: Mapping[str, object],
    ) -> tuple[ProblemTransition, ...]:
        now = float(now)
        transitions: list[ProblemTransition] = []

        cpu = _mapping(subsystem_states.get("cpu"))
        if "temperature_c" in cpu:
            transition = self._observe_numeric(
                now=now,
                value=cpu.get("temperature_c"),
                thresholds=thresholds,
                problem_id="cpu_temperature",
                category="cpu",
                severity="warning",
                object_id="cpu",
                object_name="CPU",
                metric="temperature_c",
                threshold_key="cpu_temperature_threshold",
                window_seconds=60.0,
                unit="°C",
                label="CPU temperature",
            )
            if transition is not None:
                transitions.append(transition)
        if isinstance(cpu.get("throttling_active"), bool):
            transition = self._observe_discrete(
                problem_id="cpu_throttling",
                category="cpu",
                severity="warning",
                object_id="cpu",
                object_name="CPU",
                metric="throttling",
                active=cpu.get("throttling_active") is True,
                label="CPU throttling",
                value=cpu.get("throttling_active"),
            )
            if transition is not None:
                transitions.append(transition)

        storage = _mapping(subsystem_states.get("storage"))
        for storage_id, raw in sorted(storage.items(), key=lambda item: str(item[0])):
            item = _mapping(raw)
            if "usage_percent" not in item:
                continue
            sid = str(storage_id)
            transition = self._observe_numeric(
                now=now,
                value=item.get("usage_percent"),
                thresholds=thresholds,
                problem_id=f"storage_{_slug(sid)}_percent_used",
                category="storage",
                severity="warning",
                object_id=sid,
                object_name=str(item.get("name") or sid),
                metric="percent_used",
                threshold_key="storage_percent_used_threshold",
                window_seconds=300.0,
                unit="%",
                label=f"Storage {item.get('name') or sid} percent used",
            )
            if transition is not None:
                transitions.append(transition)

        disks = _mapping(subsystem_states.get("disk_temperature"))
        for disk_id, raw in sorted(disks.items(), key=lambda item: str(item[0])):
            item = _mapping(raw)
            disk_type = str(item.get("disk_type") or "").strip().upper()
            threshold_key = _DISK_THRESHOLDS.get(disk_type)
            if threshold_key is None or "temperature_c" not in item:
                continue
            did = str(disk_id)
            name = str(item.get("model") or did)
            transition = self._observe_numeric(
                now=now,
                value=item.get("temperature_c"),
                thresholds=thresholds,
                problem_id=f"disk_{_slug(did)}_temperature",
                category="disk",
                severity="warning",
                object_id=did,
                object_name=name,
                metric="temperature_c",
                threshold_key=threshold_key,
                window_seconds=300.0,
                unit="°C",
                label=f"Disk {name} temperature",
            )
            if transition is not None:
                transitions.append(transition)

        gpus = _mapping(subsystem_states.get("gpu"))
        for gpu_id, raw in sorted(gpus.items(), key=lambda item: str(item[0])):
            item = _mapping(raw)
            if "temperature_c" not in item:
                continue
            gid = str(gpu_id)
            name = str(item.get("display_name") or item.get("model") or gid)
            transition = self._observe_numeric(
                now=now,
                value=item.get("temperature_c"),
                thresholds=thresholds,
                problem_id=f"gpu_{_slug(gid)}_temperature",
                category="gpu",
                severity="warning",
                object_id=gid,
                object_name=name,
                metric="temperature_c",
                threshold_key="gpu_temperature_threshold",
                window_seconds=300.0,
                unit="°C",
                label=f"GPU {name} temperature",
            )
            if transition is not None:
                transitions.append(transition)

        smart = _mapping(subsystem_states.get("smart"))
        for disk_id, raw in sorted(smart.items(), key=lambda item: str(item[0])):
            item = _mapping(raw)
            passed = item.get("smart_passed")
            if not isinstance(passed, bool):
                continue
            did = str(disk_id)
            name = str(item.get("model") or did)
            transition = self._observe_discrete(
                problem_id=f"disk_{_slug(did)}_smart",
                category="disk",
                severity="critical",
                object_id=did,
                object_name=name,
                metric="smart_passed",
                active=passed is False,
                label=f"SMART {name}",
                value=passed,
            )
            if transition is not None:
                transitions.append(transition)

        return tuple(transitions)

    def reevaluate_threshold(
        self,
        key: str,
        value: object,
    ) -> tuple[ProblemTransition, ...]:
        threshold = _finite(value)
        if threshold is None:
            raise ValueError(f"threshold {key!r} must be finite")
        self._thresholds[key] = threshold
        transitions: list[ProblemTransition] = []

        for problem_id, binding in sorted(self._numeric.items()):
            if binding.threshold_key != key or binding.last_now is None:
                continue
            average = binding.average_window.average(binding.last_now)
            if (
                average is None
                or binding.first_seen is None
                or binding.last_now - binding.first_seen < binding.window_seconds
            ):
                continue
            average = round(float(average), 3)
            previous = self._states.get(problem_id)
            active = self._active_from_average(average, threshold, previous)
            state = ProblemState(
                problem_id=problem_id,
                category=binding.category,
                severity=binding.severity,
                object_id=binding.object_id,
                object_name=binding.object_name,
                metric=binding.metric,
                active=active,
                value=binding.last_value,
                average=average,
                threshold=threshold,
                summary=self._numeric_text(binding.label, active),
                details=self._numeric_details(average, threshold, binding.unit),
            )
            transition = self._commit(state, emit_update=True)
            if transition is not None:
                transitions.append(transition)

        return tuple(transitions)

    def aggregate(self) -> ProblemAggregate:
        active_states = sorted(
            (state for state in self._states.values() if state.active),
            key=lambda state: state.problem_id,
        )
        count = len(active_states)
        severity = (
            max(active_states, key=lambda state: _SEVERITY_RANK.get(state.severity, 0)).severity
            if active_states
            else "ok"
        )
        if count == 0:
            summary = "No active problems"
        elif count == 1:
            summary = "1 active problem"
        else:
            summary = f"{count} active problems"
        return ProblemAggregate(
            count=count,
            severity=severity,
            summary=summary,
            active=tuple(_compact(state) for state in active_states),
        )
