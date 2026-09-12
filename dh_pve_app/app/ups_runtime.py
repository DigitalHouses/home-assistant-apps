from __future__ import annotations

import dataclasses
import json
import logging
import queue
from collections.abc import Callable
from datetime import datetime

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
from .ups_policy import (
    PolicyApplyResult,
    PolicySafetyFacts,
    PolicyValidationError,
    PolicyValidationResult,
    UpsPolicyDraft,
    parse_policy_value,
    policy_hash,
    validate_policy,
)
from .ups_shutdown_policy import UpsShutdownPolicy, read_shutdown_policy
from .ups_test_history import append_test_history, normalize_test_result
from .ups_test_schedule import TestSchedule, is_test_eligible_now, next_scheduled_test


_LEGACY_DISCOVERY_REMOVALS = {
    "estimated_real_power": "sensor",
}

_DEFAULT_POLICY_DRAFT = UpsPolicyDraft(
    on_battery_delay_minutes=30,
    power_restore_delay_seconds=120,
)

_DEFAULT_TEST_SCHEDULES = {
    "quick": TestSchedule(interval_days=30, preferred_time="12:00"),
    "deep": TestSchedule(interval_days=180, preferred_time="13:00"),
}

_POLICY_STATUSES = {
    "Active",
    "Pending changes",
    "Validation failed",
    "Apply failed",
    "Commissioning",
    "Unknown",
}


def _policy_from_mapping(value: object) -> UpsPolicyDraft | None:
    if not isinstance(value, dict):
        return None
    try:
        draft = UpsPolicyDraft(
            on_battery_delay_minutes=int(value["on_battery_delay_minutes"]),
            power_restore_delay_seconds=int(value["power_restore_delay_seconds"]),
        )
        parse_policy_value(
            "on_battery_delay_minutes", str(draft.on_battery_delay_minutes)
        )
        parse_policy_value(
            "power_restore_delay_seconds", str(draft.power_restore_delay_seconds)
        )
        return draft
    except (KeyError, TypeError, ValueError, PolicyValidationError):
        return None


def _aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


class UpsRuntime:
    """NUT runtime for UPS telemetry, battery tests, and managed policy state."""

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
        now_local: Callable[[], datetime] | None = None,
        reader: Callable[[UpsConfig], UpsSnapshot] = read_ups,
        capability_reader: Callable[[UpsConfig], UpsCapabilities] = list_ups_commands,
        command_executor: Callable[[UpsConfig, str], None] = run_ups_battery_test,
        shutdown_policy_reader: Callable[[], UpsShutdownPolicy] = read_shutdown_policy,
        policy_facts_reader: Callable[[], PolicySafetyFacts] | None = None,
        policy_applier: Callable[
            [UpsPolicyDraft, PolicySafetyFacts], PolicyApplyResult
        ] | None = None,
    ) -> None:
        self.config = config
        self.mqtt_config = mqtt_config
        self.bridge = bridge
        self.identity = identity
        self.version = version
        self.state_store = state_store
        self.now_iso = now_iso
        self.now_monotonic = now_monotonic
        self.now_local = now_local or self._local_from_iso
        self.reader = reader
        self.capability_reader = capability_reader
        self.command_executor = command_executor
        self.shutdown_policy_reader = shutdown_policy_reader
        self.policy_facts_reader = policy_facts_reader
        self.policy_applier = policy_applier
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

        self.policy_active = _policy_from_mapping(persisted.get("policy_active"))
        self.policy_draft = (
            _policy_from_mapping(persisted.get("policy_draft"))
            or self.policy_active
            or _DEFAULT_POLICY_DRAFT
        )
        persisted_status = persisted.get("policy_status")
        if isinstance(persisted_status, str) and persisted_status in _POLICY_STATUSES:
            self.policy_status = persisted_status
        elif self.policy_active is not None:
            self.policy_status = "Active"
        else:
            self.policy_status = "Commissioning"
        persisted_result = persisted.get("policy_apply_result")
        self.policy_apply_result = (
            persisted_result if isinstance(persisted_result, str) else "Not applied"
        )
        persisted_applied = persisted.get("policy_last_applied")
        self.policy_last_applied = (
            persisted_applied if isinstance(persisted_applied, str) else None
        )
        persisted_revision = persisted.get("policy_revision")
        self.policy_revision = (
            persisted_revision
            if isinstance(persisted_revision, int) and persisted_revision >= 0
            else 0
        )
        persisted_hash = persisted.get("policy_hash")
        self.policy_hash = persisted_hash if isinstance(persisted_hash, str) else None
        if self.policy_active is None:
            self.policy_revision = 0
            self.policy_hash = None
            self.policy_last_applied = None
        elif self.policy_hash is None:
            self.policy_hash = policy_hash(self.policy_active)

        self.policy_validation: PolicyValidationResult | None = None

        local_now = self._local_now()
        persisted_test_schedule = persisted.get("test_schedule")
        self.test_schedule = {
            test_type: self._load_test_schedule_entry(
                persisted_test_schedule,
                test_type,
                default,
                local_now,
            )
            for test_type, default in _DEFAULT_TEST_SCHEDULES.items()
        }
        self.test_schedule_last_decision = (
            persisted_test_schedule.get("last_decision")
            if isinstance(persisted_test_schedule, dict)
            and isinstance(persisted_test_schedule.get("last_decision"), str)
            else None
        )
        raw_history = persisted.get("test_history")
        if isinstance(raw_history, list):
            self.test_history = [
                dict(item) for item in raw_history[-10:] if isinstance(item, dict)
            ]
        else:
            self.test_history = []

        self.last_snapshot: UpsSnapshot | None = None
        self.nut_available = False
        self.capabilities: UpsCapabilities | None = None
        self.shutdown_policy: UpsShutdownPolicy | None = None
        self.last_discovery_payload: dict[str, object] | None = None
        self._discovery_fingerprint: str | None = None
        self._last_state_payload: dict[str, object] | None = None

    def _local_from_iso(self) -> datetime:
        parsed = datetime.fromisoformat(self.now_iso())
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return parsed.astimezone()
        return parsed

    def _local_now(self) -> datetime:
        value = self.now_local()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("UPS test scheduler requires timezone-aware local time")
        return value

    @staticmethod
    def _load_test_schedule_entry(
        persisted_schedule: object,
        test_type: str,
        default: TestSchedule,
        local_now: datetime,
    ) -> dict[str, object]:
        raw = (
            persisted_schedule.get(test_type)
            if isinstance(persisted_schedule, dict)
            else None
        )
        if not isinstance(raw, dict):
            raw = {}
        try:
            schedule = TestSchedule(
                interval_days=int(raw.get("interval_days", default.interval_days)),
                preferred_time=str(raw.get("preferred_time", default.preferred_time)),
            )
        except (TypeError, ValueError):
            schedule = default
        anchor = _aware_datetime(raw.get("anchor")) or local_now
        last_window_date = raw.get("last_window_date")
        return {
            "interval_days": schedule.interval_days,
            "preferred_time": schedule.preferred_time,
            "anchor": anchor.isoformat(),
            "last_window_date": (
                last_window_date if isinstance(last_window_date, str) else None
            ),
        }

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

    def _persisted_test_schedule(self) -> dict[str, object]:
        return {
            "quick": dict(self.test_schedule["quick"]),
            "deep": dict(self.test_schedule["deep"]),
            "last_decision": self.test_schedule_last_decision,
        }

    def _persist(self) -> None:
        self.state_store.save(
            {
                "last_refresh": self.last_refresh,
                "discovery_components": dict(sorted(self._discovery_components.items())),
                "discovery_cleanup_v1": self._discovery_cleanup_v1,
                "policy_active": (
                    self.policy_active.as_dict() if self.policy_active is not None else None
                ),
                "policy_draft": self.policy_draft.as_dict(),
                "policy_status": self.policy_status,
                "policy_apply_result": self.policy_apply_result,
                "policy_last_applied": self.policy_last_applied,
                "policy_revision": self.policy_revision,
                "policy_hash": self.policy_hash,
                "test_schedule": self._persisted_test_schedule(),
                "test_history": list(self.test_history),
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
                "min_supplies": None,
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

    def _policy_payload(self) -> dict[str, object]:
        return {
            "draft": self.policy_draft.as_dict(),
            "active": (
                self.policy_active.as_dict() if self.policy_active is not None else None
            ),
            "status": self.policy_status,
            "apply_result": self.policy_apply_result,
            "last_applied": self.policy_last_applied,
            "policy_revision": self.policy_revision,
            "policy_hash": self.policy_hash,
        }

    def _last_test_summary(self, test_type: str) -> tuple[object, object]:
        label = test_type.capitalize()
        for record in reversed(self.test_history):
            if record.get("type") == label:
                return record.get("result"), record.get("started_at")
        return None, None

    def _test_schedule_payload(self) -> dict[str, object]:
        result: dict[str, object] = {}
        for test_type in ("quick", "deep"):
            entry = self.test_schedule[test_type]
            schedule = TestSchedule(
                interval_days=int(entry["interval_days"]),
                preferred_time=str(entry["preferred_time"]),
            )
            anchor = _aware_datetime(entry.get("anchor"))
            next_due = next_scheduled_test(schedule, anchor) if anchor is not None else None
            last_result, last_time = self._last_test_summary(test_type)
            result[test_type] = {
                "interval_days": schedule.interval_days,
                "preferred_time": schedule.preferred_time,
                "anchor": entry["anchor"],
                "next_due": next_due.isoformat() if next_due is not None else None,
                "last_result": last_result,
                "last_time": last_time,
            }
        running = normalize_test_result(
            self.last_snapshot.test_result if self.last_snapshot is not None else None
        )
        result["current_state"] = "Running" if running == "Running" else "Idle"
        result["last_decision"] = self.test_schedule_last_decision
        return result

    def _auxiliary_fields(self) -> dict[str, object]:
        return {
            "capabilities": self._capabilities_payload(),
            "shutdown_policy": self._shutdown_policy_payload(),
            "policy": self._policy_payload(),
            "test_schedule": self._test_schedule_payload(),
            "test_history": list(self.test_history),
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

    def _refresh_policy_validation(self) -> None:
        if self.policy_facts_reader is None:
            self.policy_validation = None
            return
        try:
            facts = self.policy_facts_reader()
            self.policy_validation = validate_policy(self.policy_draft, facts)
        except Exception:
            self.policy_validation = None

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

    def _update_open_test_history(self, snapshot: UpsSnapshot) -> bool:
        if not self.test_history:
            return False
        record = self.test_history[-1]
        if record.get("finished_at") is not None:
            return False
        if record.get("result") not in {"Started", "Running"}:
            return False
        raw_result = snapshot.test_result
        normalized = normalize_test_result(raw_result)
        if normalized == "Unknown":
            return False
        if (
            record.get("result") == "Started"
            and raw_result == record.get("nut_result_before")
        ):
            return False

        updated = dict(record)
        updated["nut_result"] = raw_result
        if normalized == "Running":
            updated["result"] = "Running"
            self.test_history[-1] = updated
            self._persist()
            return True

        updated["result"] = normalized
        finished = self._local_now()
        updated["finished_at"] = finished.isoformat()
        started = _aware_datetime(updated.get("started_at"))
        updated["duration_seconds"] = (
            max(0, int((finished - started).total_seconds()))
            if started is not None
            else None
        )
        updated["battery_charge_after"] = snapshot.battery_charge_percent
        updated["runtime_after_seconds"] = snapshot.runtime_seconds
        self.test_history[-1] = updated
        self._persist()
        return True

    def _collect(self, *, force: bool = False, manual_refresh: bool = False) -> bool:
        collected_at = self.now_iso()
        try:
            snapshot = self.reader(self.config)
        except Exception as exc:
            self.nut_available = False
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

        self.nut_available = True
        self.last_snapshot = snapshot
        history_changed = self._update_open_test_history(snapshot)
        if manual_refresh:
            self.last_refresh = collected_at

        metrics = ups_metrics(snapshot)
        decision = self.policy.evaluate(
            metrics,
            force=force or manual_refresh or history_changed,
        )
        payload = self._success_payload(snapshot, collected_at=collected_at)
        discovery_ok = self.sync_discovery(force=force or manual_refresh)
        state_ok = True
        if decision.publish:
            state_ok = self.bridge.publish_ups_state(payload)
            if state_ok:
                self.policy.mark_published(metrics)
                self._last_state_payload = payload
        if (manual_refresh or history_changed) and state_ok:
            self._persist()
        return bool(discovery_ok and state_ok)

    def startup(self) -> bool:
        self._refresh_auxiliary()
        self._refresh_policy_validation()
        availability_ok = self.bridge.publish_ups_availability(True)
        collection_ok = self._collect(force=True)
        self._persist()
        return bool(availability_ok and collection_ok)

    def _schedule_object(self, test_type: str) -> TestSchedule:
        entry = self.test_schedule[test_type]
        return TestSchedule(
            interval_days=int(entry["interval_days"]),
            preferred_time=str(entry["preferred_time"]),
        )

    def _schedule_anchor(self, test_type: str) -> datetime:
        anchor = _aware_datetime(self.test_schedule[test_type].get("anchor"))
        if anchor is None:
            anchor = self._local_now()
            self.test_schedule[test_type]["anchor"] = anchor.isoformat()
        return anchor

    def _eligible_schedule_types(self, now: datetime) -> tuple[bool, bool]:
        today = now.date().isoformat()
        quick = (
            self.test_schedule["quick"].get("last_window_date") != today
            and is_test_eligible_now(
                now=now,
                schedule=self._schedule_object("quick"),
                anchor=self._schedule_anchor("quick"),
            )
        )
        deep = (
            self.test_schedule["deep"].get("last_window_date") != today
            and is_test_eligible_now(
                now=now,
                schedule=self._schedule_object("deep"),
                anchor=self._schedule_anchor("deep"),
            )
        )
        return quick, deep

    def _scheduled_test_safe(self) -> bool:
        snapshot = self.last_snapshot
        if not self.nut_available or snapshot is None:
            return False
        if not snapshot.line_power or snapshot.on_battery or snapshot.low_battery:
            return False
        if snapshot.replace_battery or snapshot.overload or snapshot.bypass:
            return False
        if snapshot.charging or snapshot.discharging:
            return False
        if "FSD" in snapshot.status_tokens:
            return False
        return normalize_test_result(snapshot.test_result) != "Running"

    def _process_scheduled_tests(self) -> bool:
        now = self._local_now()
        quick_due, deep_due = self._eligible_schedule_types(now)
        if not quick_due and not deep_due:
            return False

        today = now.date().isoformat()
        if not self._scheduled_test_safe():
            if quick_due:
                self.test_schedule["quick"]["last_window_date"] = today
            if deep_due:
                self.test_schedule["deep"]["last_window_date"] = today
            self.test_schedule_last_decision = "Safety gate blocked scheduled test"
            self._persist()
            self._collect(force=True)
            return True

        action = "deep" if deep_due else "quick"
        if deep_due and quick_due:
            self.test_schedule["quick"]["last_window_date"] = today
            self.test_schedule_last_decision = "Deep priority; Quick deferred"

        self.test_schedule[action]["last_window_date"] = today
        if self.capabilities is None or not self.capabilities.supports_test(action):
            self.test_schedule_last_decision = (
                f"{action.capitalize()} capability unavailable"
            )
            self._persist()
            self._collect(force=True)
            return True

        success = self._run_battery_test(action, source="Scheduled")
        if success:
            self.test_schedule[action]["anchor"] = now.isoformat()
            if not (deep_due and quick_due):
                self.test_schedule_last_decision = (
                    f"{action.capitalize()} scheduled test started"
                )
        else:
            self.test_schedule_last_decision = (
                f"{action.capitalize()} scheduled test failed to start"
            )
        self._persist()
        self._collect(force=True)
        return True

    def tick(self, now: float) -> bool:
        if "ups" not in self.scheduler.due(now):
            return False
        try:
            collection_ok = self._collect()
            scheduled_changed = self._process_scheduled_tests()
            return bool(collection_ok or scheduled_changed)
        finally:
            self.scheduler.mark_run("ups", now=now)

    def manual_refresh(self) -> bool:
        self._refresh_auxiliary()
        self._refresh_policy_validation()
        return self._collect(force=True, manual_refresh=True)

    def _test_history_record(
        self,
        action: str,
        source: str,
        started: datetime,
        before: UpsSnapshot | None,
    ) -> dict[str, object]:
        return {
            "started_at": started.isoformat(),
            "finished_at": None,
            "type": action.capitalize(),
            "source": source,
            "result": "Started",
            "nut_result": None,
            "nut_result_before": before.test_result if before is not None else None,
            "duration_seconds": None,
            "battery_charge_before": (
                before.battery_charge_percent if before is not None else None
            ),
            "battery_charge_after": None,
            "runtime_before_seconds": before.runtime_seconds if before is not None else None,
            "runtime_after_seconds": None,
            "load_before_percent": before.load_percent if before is not None else None,
            "failure_reason": None,
        }

    def _run_battery_test(self, action: str, *, source: str = "Manual") -> bool:
        if self.capabilities is None or not self.capabilities.supports_test(action):
            self.log.warning("UPS не поддерживает тест батареи: %s", action)
            return False
        if action == "stop":
            try:
                self.command_executor(self.config, action)
            except Exception as exc:
                self.log.warning("Не удалось остановить тест UPS: %s", exc)
                self.manual_refresh()
                return False
            self.log.info("Команда остановки теста UPS выполнена")
            self.manual_refresh()
            return True

        started = self._local_now()
        before = self.last_snapshot
        record = self._test_history_record(action, source, started, before)
        try:
            self.command_executor(self.config, action)
        except Exception as exc:
            finished = self._local_now()
            record["finished_at"] = finished.isoformat()
            record["duration_seconds"] = max(
                0, int((finished - started).total_seconds())
            )
            record["result"] = "Failed"
            record["failure_reason"] = str(exc)
            self.test_history = append_test_history(self.test_history, record)
            self._persist()
            self.log.warning("Не удалось выполнить тест UPS %s: %s", action, exc)
            self.manual_refresh()
            return False

        self.log.info("Команда теста UPS выполнена: %s", action)
        self.manual_refresh()
        after = self.last_snapshot
        raw_result = after.test_result if after is not None else None
        before_result = before.test_result if before is not None else None
        normalized = normalize_test_result(raw_result)
        if raw_result is not None and raw_result != before_result:
            record["nut_result"] = raw_result
            if normalized == "Running":
                record["result"] = "Running"
            elif normalized != "Unknown":
                finished = self._local_now()
                record["result"] = normalized
                record["finished_at"] = finished.isoformat()
                record["duration_seconds"] = max(
                    0, int((finished - started).total_seconds())
                )
                record["battery_charge_after"] = after.battery_charge_percent
                record["runtime_after_seconds"] = after.runtime_seconds
        self.test_history = append_test_history(self.test_history, record)
        self._persist()
        self._collect(force=True)
        return True

    def _rollback_draft_to_active(self) -> None:
        self.policy_draft = self.policy_active or _DEFAULT_POLICY_DRAFT
        self._refresh_policy_validation()

    def _apply_policy(self) -> None:
        draft = UpsPolicyDraft(**self.policy_draft.as_dict())
        try:
            if self.policy_facts_reader is None:
                raise PolicyValidationError(
                    "Расчет безопасности политики на этом хосте еще не настроен."
                )
            facts = self.policy_facts_reader()
            validation = validate_policy(draft, facts)
        except PolicyValidationError as exc:
            self.policy_status = "Validation failed"
            self.policy_apply_result = str(exc)
            self._rollback_draft_to_active()
            self._persist()
            return
        except Exception as exc:
            self.log.warning(
                "Не удалось проверить политику UPS: %s", type(exc).__name__
            )
            self.policy_status = "Validation failed"
            self.policy_apply_result = "Не удалось проверить безопасность политики."
            self._rollback_draft_to_active()
            self._persist()
            return

        if self.policy_applier is None:
            result = PolicyApplyResult(
                False,
                "Применение политики на этом хосте еще не настроено.",
            )
        else:
            try:
                result = self.policy_applier(draft, facts)
            except Exception as exc:
                self.log.warning(
                    "Не удалось применить политику UPS: %s", type(exc).__name__
                )
                result = PolicyApplyResult(False, "Не удалось применить политику.")

        if not result.success:
            self.policy_status = "Apply failed"
            self.policy_apply_result = result.message
            self._rollback_draft_to_active()
            self._persist()
            return

        self.policy_active = draft
        self.policy_draft = draft
        self.policy_status = "Active"
        self.policy_apply_result = result.message
        self.policy_last_applied = self.now_iso()
        self.policy_revision += 1
        self.policy_hash = policy_hash(draft)
        self.policy_validation = validation
        self._persist()

    def _process_policy_events(self) -> bool:
        changed = False
        updates = getattr(self.bridge, "ups_policy_updates", None)
        if updates is not None:
            while True:
                try:
                    update = updates.get_nowait()
                except queue.Empty:
                    break
                current = dataclasses.replace(
                    self.policy_draft,
                    **{update.key: update.value},
                )
                if current == self.policy_draft:
                    continue
                self.policy_draft = current
                if self.policy_active is not None and current == self.policy_active:
                    self.policy_status = "Active"
                elif self.policy_active is None and current == _DEFAULT_POLICY_DRAFT:
                    self.policy_status = "Commissioning"
                else:
                    self.policy_status = "Pending changes"
                    self.policy_apply_result = "Есть непримененные изменения."
                self._refresh_policy_validation()
                self._persist()
                changed = True

        apply_event = getattr(self.bridge, "ups_policy_apply_requested", None)
        if apply_event is not None and apply_event.is_set():
            apply_event.clear()
            self._apply_policy()
            changed = True

        if changed:
            self._collect(force=True)
        return changed

    def _process_test_schedule_events(self) -> bool:
        updates = getattr(self.bridge, "ups_test_schedule_updates", None)
        if updates is None:
            return False
        changed = False
        while True:
            try:
                update = updates.get_nowait()
            except queue.Empty:
                break
            if update.test_type not in self.test_schedule:
                continue
            current = dict(self.test_schedule[update.test_type])
            current[update.field] = update.value
            try:
                schedule = TestSchedule(
                    interval_days=int(current["interval_days"]),
                    preferred_time=str(current["preferred_time"]),
                )
            except (TypeError, ValueError):
                continue
            if (
                schedule.interval_days == self.test_schedule[update.test_type]["interval_days"]
                and schedule.preferred_time
                == self.test_schedule[update.test_type]["preferred_time"]
            ):
                continue
            now = self._local_now()
            self.test_schedule[update.test_type] = {
                "interval_days": schedule.interval_days,
                "preferred_time": schedule.preferred_time,
                "anchor": now.isoformat(),
                "last_window_date": None,
            }
            self.test_schedule_last_decision = (
                f"{update.test_type.capitalize()} schedule updated"
            )
            changed = True

        if changed:
            self._persist()
            self._collect(force=True)
        return changed

    def republish_after_reconnect(self) -> bool:
        availability_ok = self.bridge.publish_ups_availability(True)
        if self.last_snapshot is None and self._last_state_payload is None:
            self._refresh_auxiliary()
            self._refresh_policy_validation()
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
                self._run_battery_test(action, source="Manual")
                handled = True

        if self._process_test_schedule_events():
            handled = True
        if self._process_policy_events():
            handled = True
        return handled
