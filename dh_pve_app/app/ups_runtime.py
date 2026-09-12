from __future__ import annotations

import dataclasses
import json
import logging
import queue
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


_LEGACY_DISCOVERY_REMOVALS = {
    "estimated_real_power": "sensor",
}

_DEFAULT_POLICY_DRAFT = UpsPolicyDraft(
    on_battery_delay_minutes=30,
    emergency_runtime_reserve_minutes=15,
    power_restore_delay_seconds=120,
)

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
            emergency_runtime_reserve_minutes=int(
                value["emergency_runtime_reserve_minutes"]
            ),
            power_restore_delay_seconds=int(value["power_restore_delay_seconds"]),
        )
        parse_policy_value(
            "on_battery_delay_minutes", str(draft.on_battery_delay_minutes)
        )
        parse_policy_value(
            "emergency_runtime_reserve_minutes",
            str(draft.emergency_runtime_reserve_minutes),
        )
        parse_policy_value(
            "power_restore_delay_seconds", str(draft.power_restore_delay_seconds)
        )
        return draft
    except (KeyError, TypeError, ValueError, PolicyValidationError):
        return None


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
                "policy_active": (
                    self.policy_active.as_dict() if self.policy_active is not None else None
                ),
                "policy_draft": self.policy_draft.as_dict(),
                "policy_status": self.policy_status,
                "policy_apply_result": self.policy_apply_result,
                "policy_last_applied": self.policy_last_applied,
                "policy_revision": self.policy_revision,
                "policy_hash": self.policy_hash,
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
        validation = self.policy_validation
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
            "minimum_emergency_runtime_reserve_seconds": (
                validation.minimum_emergency_runtime_reserve_seconds
                if validation is not None
                else None
            ),
            "recommended_emergency_runtime_reserve_seconds": (
                validation.recommended_emergency_runtime_reserve_seconds
                if validation is not None
                else None
            ),
        }

    def _auxiliary_fields(self) -> dict[str, object]:
        return {
            "capabilities": self._capabilities_payload(),
            "shutdown_policy": self._shutdown_policy_payload(),
            "policy": self._policy_payload(),
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
        self._refresh_policy_validation()
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
        self._refresh_policy_validation()
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
                self._run_battery_test(action)
                handled = True

        if self._process_policy_events():
            handled = True
        return handled
