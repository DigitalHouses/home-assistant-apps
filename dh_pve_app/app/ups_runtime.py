from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Callable

from .config import MqttConfig, UpsConfig
from .discovery_ups import build_ups_discovery_payload
from .identity import HostIdentity
from .publish_policy import MetricValue, PublishPolicy
from .runtime_settings import RuntimeSettings
from .scheduler import Scheduler
from .state_store import StateStore
from .ups_control import UpsCapabilities, list_ups_commands, run_ups_battery_test
from .ups_health import summarize_ups_problems
from .ups_nut import UpsSnapshot, read_ups, ups_metrics
from .ups_shutdown_policy import UpsShutdownPolicy, read_shutdown_policy


_LEGACY_DISCOVERY_REMOVALS = {
    "estimated_real_power": "sensor",
}


class UpsRuntime:
    """NUT runtime for UPS telemetry plus explicitly allowed battery-test controls."""

    def __init__(
        self,
        config: UpsConfig,
        mqtt_config: MqttConfig,
        bridge,
        identity: HostIdentity,
        version: str,
        state_store: StateStore,
        now_iso: Callable[[], str],
        now_monotonic: Callable[[], float],
        reader: Callable[[UpsConfig], UpsSnapshot] = read_ups,
        capability_reader: Callable[[UpsConfig], UpsCapabilities] = list_ups_commands,
        command_executor: Callable[[UpsConfig, str], None] = run_ups_battery_test,
        shutdown_policy_reader: Callable[[], UpsShutdownPolicy] = read_shutdown_policy,
    ) -> None:
        self.config = config
        self.mqtt_config = mqtt_config
        self.bridge = bridge
        self.identity = identity
        self.version = version
        self.state_store = state_store
        self.now_iso = now_iso
        self.now_monotonic = now_monotonic
        self.reader = reader
        self.capability_reader = capability_reader
        self.command_executor = command_executor
        self.shutdown_policy_reader = shutdown_policy_reader
        self.log = logging.getLogger(__name__)
        self.policy = PublishPolicy(RuntimeSettings())
        self.scheduler = Scheduler()
        self.scheduler.add(
            "ups",
            interval_seconds=config.poll_interval_seconds,
            now=now_monotonic(),
        )
        persisted = state_store.load()
        last_refresh = persisted.get("last_refresh")
        self.last_refresh = last_refresh if isinstance(last_refresh, str) else None

        persisted_components = persisted.get("discovery_components")
        if isinstance(persisted_components, dict):
            self._discovery_components = {
                str(key): str(value)
                for key, value in persisted_components.items()
                if isinstance(key, str) and isinstance(value, str)
            }
        else:
            self._discovery_components = {}
        self._discovery_cleanup_v1 = persisted.get("discovery_cleanup_v1") is True

        self.last_snapshot: UpsSnapshot | None = None
        self.capabilities: UpsCapabilities | None = None
        self.shutdown_policy: UpsShutdownPolicy | None = None
        self.last_discovery_payload: dict[str, object] | None = None
        self._discovery_fingerprint: str | None = None
        self._last_state_payload: dict[str, object] | None = None

    @staticmethod
    def _human_status(snapshot: UpsSnapshot) -> str:
        if snapshot.overload:
            return "Overload"
        if snapshot.replace_battery:
            return "Replace battery"
        if snapshot.low_battery:
            return "Low battery"
        if snapshot.bypass:
            return "Bypass"
        if snapshot.on_battery:
            return "On battery"
        if snapshot.charging:
            return "Charging"
        if snapshot.discharging:
            return "Discharging"
        if snapshot.line_power:
            return "Online"
        return "Unknown"

    def _persist(self) -> None:
        self.state_store.save(
            {
                "last_refresh": self.last_refresh,
                "discovery_components": dict(sorted(self._discovery_components.items())),
                "discovery_cleanup_v1": self._discovery_cleanup_v1,
            }
        )

    @staticmethod
    def _component_platforms(payload: dict[str, object]) -> dict[str, str]:
        raw_components = payload.get("components")
        if not isinstance(raw_components, dict):
            return {}
        result: dict[str, str] = {}
        for key, component in raw_components.items():
            if not isinstance(key, str) or not isinstance(component, dict):
                continue
            platform = component.get("platform")
            if isinstance(platform, str) and platform:
                result[key] = platform
        return result

    @staticmethod
    def _with_tombstones(
        payload: dict[str, object],
        removed: dict[str, str],
    ) -> dict[str, object]:
        tombstone_payload = dict(payload)
        raw_components = payload.get("components")
        components = dict(raw_components) if isinstance(raw_components, dict) else {}
        for key, platform in removed.items():
            components[key] = {"platform": platform}
        tombstone_payload["components"] = components
        return tombstone_payload

    def _snapshot_data(self, snapshot: UpsSnapshot) -> dict[str, object]:
        data = dataclasses.asdict(snapshot)
        data["status_tokens"] = list(snapshot.status_tokens)
        if snapshot.runtime_seconds is not None:
            data["battery_runtime_minutes"] = round(snapshot.runtime_seconds / 60.0, 1)
        return data

    @staticmethod
    def _problem_fields(
        snapshot: UpsSnapshot | None,
        *,
        nut_available: bool,
    ) -> dict[str, object]:
        summary = summarize_ups_problems(snapshot, nut_available=nut_available)
        return {
            "problems_count": summary.count,
            "problems_severity": summary.severity,
            "problems": list(summary.problems),
            "problems_details": summary.details,
        }

    def _capabilities_payload(self) -> dict[str, object]:
        if self.capabilities is None:
            return {
                "available": False,
                "count": 0,
                "commands": [],
                "battery_tests": [],
                "beeper_control": False,
                "load_control": False,
                "shutdown_control": False,
                "supported_features": [],
            }
        return self.capabilities.as_dict()

    def _shutdown_policy_payload(self) -> dict[str, object]:
        if self.shutdown_policy is None:
            return {
                "state": "Unknown",
                "role": "unknown",
                "nut_monitor": "unknown",
                "shutdown_enabled": False,
                "shutdown_command": None,
                "minsuppplies": None,
                "pollfreq_seconds": None,
                "pollfreqalert_seconds": None,
                "deadtime_seconds": None,
                "hostsync_seconds": None,
                "finaldelay_seconds": None,
                "upssched_present": False,
                "upssched_rules": 0,
                "upssched_active": False,
                "guest_shutdown_budget_seconds": None,
                "power_restore_behavior": "Not configured",
            }
        return self.shutdown_policy.as_dict()

    def _auxiliary_fields(self) -> dict[str, object]:
        return {
            "capabilities": self._capabilities_payload(),
            "shutdown_policy": self._shutdown_policy_payload(),
        }

    def _success_payload(
        self,
        snapshot: UpsSnapshot,
        *,
        collected_at: str,
    ) -> dict[str, object]:
        data = self._snapshot_data(snapshot)
        payload: dict[str, object] = {
            "available": True,
            "collected_at": collected_at,
            "last_refresh": self.last_refresh,
            "status": self._human_status(snapshot),
            "error": None,
            "data": data,
        }
        payload.update(data)
        payload.update(self._problem_fields(snapshot, nut_available=True))
        payload.update(self._auxiliary_fields())
        return payload

    def _failure_payload(self, *, collected_at: str, error: str) -> dict[str, object]:
        data = self._snapshot_data(self.last_snapshot) if self.last_snapshot is not None else {}
        payload: dict[str, object] = {
            "available": False,
            "collected_at": collected_at,
            "last_refresh": self.last_refresh,
            "status": "Unavailable",
            "error": error,
            "data": data,
        }
        payload.update(data)
        payload["available"] = False
        payload["status"] = "Unavailable"
        payload["error"] = error
        payload.update(self._problem_fields(None, nut_available=False))
        payload.update(self._auxiliary_fields())
        return payload

    def _build_discovery(self) -> dict[str, object]:
        return build_ups_discovery_payload(
            config=self.mqtt_config,
            identity=self.identity,
            version=self.version,
            snapshot=self.last_snapshot,
            capabilities=self.capabilities,
            shutdown_policy=self.shutdown_policy,
        )

    def _refresh_auxiliary(self) -> None:
        try:
            self.capabilities = self.capability_reader(self.config)
        except Exception as exc:
            self.capabilities = None
            self.log.warning("Не удалось получить возможности UPS через NUT: %s", exc)

        try:
            self.shutdown_policy = self.shutdown_policy_reader()
        except Exception as exc:
            self.shutdown_policy = None
            self.log.warning("Не удалось прочитать политику shutdown NUT/PVE: %s", exc)

    def sync_discovery(self, *, force: bool = False) -> bool:
        payload = self._build_discovery()
        fingerprint = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.last_discovery_payload = payload

        desired_components = self._component_platforms(payload)
        removed = {
            key: platform
            for key, platform in self._discovery_components.items()
            if key not in desired_components
        }
        if not self._discovery_cleanup_v1:
            for key, platform in _LEGACY_DISCOVERY_REMOVALS.items():
                if key not in desired_components:
                    removed.setdefault(key, platform)

        if (
            not force
            and fingerprint == self._discovery_fingerprint
            and not removed
            and self._discovery_cleanup_v1
        ):
            return True

        if removed:
            if not self.bridge.publish_ups_discovery(
                self._with_tombstones(payload, removed)
            ):
                return False

        ok = self.bridge.publish_ups_discovery(payload)
        if ok:
            self._discovery_fingerprint = fingerprint
            self._discovery_components = desired_components
            self._discovery_cleanup_v1 = True
            self._persist()
        return ok

    def _collect(self, *, force: bool = False, manual_refresh: bool = False) -> bool:
        collected_at = self.now_iso()
        try:
            snapshot = self.reader(self.config)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self.log.warning("Не удалось прочитать UPS через NUT: %s", exc)
            metrics = {"available": MetricValue(False, "discrete")}
            decision = self.policy.evaluate(metrics, force=force or manual_refresh)
            payload = self._failure_payload(collected_at=collected_at, error=error)
            if decision.publish:
                if self.bridge.publish_ups_state(payload):
                    self.policy.mark_published(metrics)
                    self._last_state_payload = payload
            self.sync_discovery(force=False)
            return False

        self.last_snapshot = snapshot
        if manual_refresh:
            self.last_refresh = collected_at

        metrics = ups_metrics(snapshot)
        decision = self.policy.evaluate(metrics, force=force or manual_refresh)
        payload = self._success_payload(snapshot, collected_at=collected_at)
        discovery_ok = self.sync_discovery(force=force or manual_refresh)
        state_ok = True
        if decision.publish:
            state_ok = self.bridge.publish_ups_state(payload)
            if state_ok:
                self.policy.mark_published(metrics)
                self._last_state_payload = payload
        if manual_refresh and state_ok:
            self._persist()
        return bool(discovery_ok and state_ok)

    def startup(self) -> bool:
        self._refresh_auxiliary()
        availability_ok = self.bridge.publish_ups_availability(True)
        collection_ok = self._collect(force=True)
        return bool(availability_ok and collection_ok)

    def tick(self, now: float) -> bool:
        if "ups" not in self.scheduler.due(now):
            return False
        try:
            return self._collect()
        finally:
            self.scheduler.mark_run("ups", now=now)

    def manual_refresh(self) -> bool:
        self._refresh_auxiliary()
        return self._collect(force=True, manual_refresh=True)

    def _run_battery_test(self, action: str) -> bool:
        if self.capabilities is None or not self.capabilities.supports_test(action):
            self.log.warning("UPS не поддерживает тест батареи: %s", action)
            return False
        try:
            self.command_executor(self.config, action)
        except Exception as exc:
            self.log.warning("Не удалось выполнить тест UPS %s: %s", action, exc)
            self.manual_refresh()
            return False
        self.log.info("Команда теста UPS выполнена: %s", action)
        self.manual_refresh()
        return True

    def republish_after_reconnect(self) -> bool:
        availability_ok = self.bridge.publish_ups_availability(True)
        if self.last_snapshot is None and self._last_state_payload is None:
            self._refresh_auxiliary()
            return bool(availability_ok and self._collect(force=True))
        discovery_ok = self.sync_discovery(force=True)
        state = self._last_state_payload
        state_ok = True if state is None else self.bridge.publish_ups_state(state)
        return bool(availability_ok and discovery_ok and state_ok)

    def process_events(self) -> bool:
        handled = False
        if self.bridge.ups_reconnect_requested.is_set():
            self.bridge.ups_reconnect_requested.clear()
            self.republish_after_reconnect()
            handled = True
        if self.bridge.ups_refresh_requested.is_set():
            self.bridge.ups_refresh_requested.clear()
            self.manual_refresh()
            handled = True

        for action, attr in (
            ("quick", "ups_test_quick_requested"),
            ("deep", "ups_test_deep_requested"),
            ("stop", "ups_test_stop_requested"),
        ):
            event = getattr(self.bridge, attr, None)
            if event is not None and event.is_set():
                event.clear()
                self._run_battery_test(action)
                handled = True
        return handled
