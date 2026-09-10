from __future__ import annotations

import dataclasses
import queue
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from .publish_policy import MetricValue, PublishPolicy
from .runtime_settings import RuntimeSettings
from .scheduler import Scheduler
from .state_store import StateStore


@dataclass(frozen=True)
class CollectorSample:
    data: object
    metrics: Mapping[str, MetricValue]


@dataclass
class SubsystemState:
    available: bool
    data: object | None
    metrics: dict[str, MetricValue]
    last_success: str | None
    error: str | None


class RuntimeBridge(Protocol):
    refresh_requested: Any
    reconnect_requested: Any
    setting_updates: Any

    def publish_discovery(self) -> bool: ...
    def publish_state(self, payload: dict[str, object]) -> bool: ...
    def publish_setting_value(self, key: str, value: float) -> bool: ...


class DhPveRuntime:
    """Orchestrate collectors and MQTT without coupling collectors to transport."""

    def __init__(
        self,
        *,
        collectors: Mapping[str, Callable[[], CollectorSample]],
        bridge: RuntimeBridge,
        settings: RuntimeSettings,
        publish_policy: PublishPolicy,
        state_store: StateStore,
        scheduler: Scheduler,
        now_iso: Callable[[], str],
        now_monotonic: Callable[[], float] = time.monotonic,
        setting_tasks: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.collectors = dict(collectors)
        self.bridge = bridge
        self.settings = settings
        self.publish_policy = publish_policy
        self.state_store = state_store
        self.scheduler = scheduler
        self.now_iso = now_iso
        self.now_monotonic = now_monotonic
        self.setting_tasks = dict(setting_tasks or {})
        self._subsystems: dict[str, SubsystemState] = {}
        self.last_refresh: str | None = None
        self._load_persisted_runtime_state()

    def _load_persisted_runtime_state(self) -> None:
        persisted = self.state_store.load()
        last_refresh = persisted.get("last_refresh")
        if isinstance(last_refresh, str) and last_refresh:
            self.last_refresh = last_refresh
        values = persisted.get("runtime_settings")
        apply = getattr(self.settings, "apply", None)
        if isinstance(values, dict) and callable(apply):
            for key, value in values.items():
                try:
                    apply(str(key), str(value))
                except (ValueError, TypeError):
                    continue

    def _persist_runtime_state(self) -> None:
        self.state_store.save(
            {
                "last_refresh": self.last_refresh,
                "runtime_settings": self.settings.as_dict(),
            }
        )

    @staticmethod
    def _jsonable(value: object) -> object:
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return DhPveRuntime._jsonable(dataclasses.asdict(value))
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, Mapping):
            return {str(k): DhPveRuntime._jsonable(v) for k, v in value.items()}
        if isinstance(value, (tuple, list, set)):
            return [DhPveRuntime._jsonable(item) for item in value]
        return value

    def _collect_one(self, name: str, collected_at: str) -> None:
        previous = self._subsystems.get(name)
        try:
            sample = self.collectors[name]()
            if not isinstance(sample, CollectorSample):
                raise TypeError("collector must return CollectorSample")
            metrics = {
                str(key): metric
                for key, metric in sample.metrics.items()
                if isinstance(metric, MetricValue)
            }
            if len(metrics) != len(sample.metrics):
                raise TypeError("collector metrics must contain MetricValue values")
            self._subsystems[name] = SubsystemState(
                available=True,
                data=sample.data,
                metrics=metrics,
                last_success=collected_at,
                error=None,
            )
        except Exception as exc:
            self._subsystems[name] = SubsystemState(
                available=False,
                data=previous.data if previous is not None else None,
                metrics=dict(previous.metrics) if previous is not None else {},
                last_success=previous.last_success if previous is not None else None,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _policy_metrics(self) -> dict[str, MetricValue]:
        result: dict[str, MetricValue] = {}
        for name in sorted(self._subsystems):
            state = self._subsystems[name]
            result[f"subsystem.{name}.available"] = MetricValue(
                state.available, "discrete"
            )
            for key, metric in state.metrics.items():
                result[f"{name}.{key}"] = metric
        return result

    def _state_payload(
        self,
        *,
        collected_at: str,
        last_refresh: str | None = None,
    ) -> dict[str, object]:
        subsystems: dict[str, object] = {}
        for name in sorted(self._subsystems):
            state = self._subsystems[name]
            subsystems[name] = {
                "available": state.available,
                "data": self._jsonable(state.data),
                "last_success": state.last_success,
                "error": state.error,
            }
        return {
            "collected_at": collected_at,
            "last_refresh": self.last_refresh if last_refresh is None else last_refresh,
            "subsystems": subsystems,
        }

    def run_collection(
        self,
        names: tuple[str, ...] | list[str] | None = None,
        *,
        force: bool = False,
        manual_refresh: bool = False,
    ) -> bool:
        selected = tuple(self.collectors) if names is None else tuple(names)
        collected_at = self.now_iso()
        for name in selected:
            if name not in self.collectors:
                continue
            self._collect_one(name, collected_at)

        candidate_refresh = self.last_refresh
        if manual_refresh and all(
            self._subsystems.get(name) is not None
            and self._subsystems[name].available
            for name in self.collectors
        ):
            candidate_refresh = collected_at

        metrics = self._policy_metrics()
        decision = self.publish_policy.evaluate(metrics, force=force or manual_refresh)
        if not decision.publish:
            return False

        payload = self._state_payload(
            collected_at=collected_at,
            last_refresh=candidate_refresh,
        )
        if not self.bridge.publish_state(payload):
            return False

        self.publish_policy.mark_published(metrics)
        if manual_refresh and candidate_refresh != self.last_refresh:
            self.last_refresh = candidate_refresh
            self._persist_runtime_state()
        return True

    def manual_refresh(self) -> bool:
        return self.run_collection(force=True, manual_refresh=True)

    def publish_settings(self) -> bool:
        ok = True
        for key, value in self.settings.as_dict().items():
            ok = self.bridge.publish_setting_value(key, value) and ok
        return ok

    def startup(self) -> bool:
        discovery_ok = self.bridge.publish_discovery()
        settings_ok = self.publish_settings()
        state_ok = self.run_collection(force=True)
        return discovery_ok and settings_ok and state_ok

    def republish_after_reconnect(self) -> bool:
        discovery_ok = self.bridge.publish_discovery()
        settings_ok = self.publish_settings()
        if not self._subsystems:
            state_ok = self.run_collection(force=True)
            return discovery_ok and settings_ok and state_ok

        collected_at = self.now_iso()
        metrics = self._policy_metrics()
        payload = self._state_payload(collected_at=collected_at)
        state_ok = self.bridge.publish_state(payload)
        if state_ok:
            self.publish_policy.mark_published(metrics)
        return discovery_ok and settings_ok and state_ok

    def process_events(self) -> bool:
        handled = False
        if self.bridge.reconnect_requested.is_set():
            self.bridge.reconnect_requested.clear()
            self.republish_after_reconnect()
            handled = True
        if self.bridge.refresh_requested.is_set():
            self.bridge.refresh_requested.clear()
            self.manual_refresh()
            handled = True

        while True:
            try:
                update = self.bridge.setting_updates.get_nowait()
            except queue.Empty:
                break
            self.bridge.publish_setting_value(update.key, update.value)
            for task_name in self.setting_tasks.get(update.key, ()):
                try:
                    self.scheduler.set_interval(
                        task_name, update.value, now=self.now_monotonic()
                    )
                except KeyError:
                    continue
            self._persist_runtime_state()
            handled = True
        return handled

    def tick(self, now_monotonic: float) -> bool:
        due = self.scheduler.due(now_monotonic)
        if not due:
            return False
        published = self.run_collection(due)
        for name in due:
            self.scheduler.mark_run(name, now=now_monotonic)
        return published
