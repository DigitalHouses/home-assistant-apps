from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping

from .app import CollectorSample
from .line_power_statistics import (
    LinePowerState,
    LinePowerStatisticsTracker,
    line_power_state_from_snapshot,
)
from .publish_policy import MetricValue
from .production_guest import GuestAwareProductionCollectors
from .shutdown_discovery import build_shutdown_aware_ups_discovery_payload
from .shutdown_history import ShutdownHistoryTracker, evaluate_shutdown_readiness
from .state_store import StateStore
from .topology import TopologyManager
from .ups_group_runtime import AdaptiveUpsRuntime
from .ups_event_context import (
    line_power_event_context,
    ups_snapshot_event_context,
)
from .ups_nut import read_ups
from .ups_policy import (
    PolicyValidationError,
    UpsPolicyDraft,
    policy_from_mapping,
    policy_hash,
    validate_policy,
)
from .ups_shutdown_budget import ShutdownBudgetResult
from .ups_trigger import SoftwareShutdownController, SoftwareShutdownTriggerResult


SHUTDOWN_BUDGET_REFRESH_SECONDS = 60.0
_LOG = logging.getLogger(__name__)
_PUBLIC_SHUTDOWN_REASON = {
    "charge_guard": "charge_threshold",
    "runtime_guard": "runtime_threshold",
}


def _shutdown_budget_payload(budget: ShutdownBudgetResult | None) -> dict[str, object]:
    if budget is None:
        return {
            "available": False,
            "configured_guest_budget_seconds": None,
            "observed_guest_budget_seconds": None,
            "effective_guest_budget_seconds": None,
            "hostsync_budget_seconds": None,
            "finaldelay_seconds": None,
            "observed_host_tail_seconds": None,
            "host_tail_fallback_seconds": None,
            "host_tail_budget_seconds": None,
            "shutdown_budget_seconds": None,
            "unavailable_reason": "not_collected",
            "configuration_fingerprint": None,
            "history_evidence_status": "none",
            "all_configured_guest_budget_seconds": None,
            "running_guests": [],
            "shutdown_sequence": [],
        }
    return {
        "available": budget.available,
        "configured_guest_budget_seconds": budget.configured_guest_budget_seconds,
        "observed_guest_budget_seconds": budget.observed_guest_budget_seconds,
        "effective_guest_budget_seconds": budget.effective_guest_budget_seconds,
        "hostsync_budget_seconds": budget.hostsync_budget_seconds,
        "finaldelay_seconds": budget.finaldelay_seconds,
        "observed_host_tail_seconds": budget.observed_host_tail_seconds,
        "host_tail_fallback_seconds": budget.host_tail_fallback_seconds,
        "host_tail_budget_seconds": budget.host_tail_budget_seconds,
        "shutdown_budget_seconds": budget.shutdown_budget_seconds,
        "unavailable_reason": budget.unavailable_reason,
        "configuration_fingerprint": budget.configuration_fingerprint,
        "history_evidence_status": budget.history_evidence_status,
        "all_configured_guest_budget_seconds": budget.all_configured_guest_budget_seconds,
        "running_guests": list(budget.running_guests),
        "shutdown_sequence": [list(group) for group in budget.shutdown_sequence],
    }


def parse_guest_shutdown_config(config: str) -> dict[str, object]:
    onboot = False
    timeout = 180
    order: int | None = None

    onboot_match = re.search(r"(?m)^onboot:\s*(\S+)\s*$", config)
    if onboot_match is not None:
        onboot = onboot_match.group(1).strip().casefold() in {"1", "true", "yes", "on"}

    startup_match = re.search(r"(?m)^startup:\s*(.+?)\s*$", config)
    if startup_match is not None:
        for raw in startup_match.group(1).split(","):
            key, separator, value = raw.strip().partition("=")
            if not separator:
                continue
            try:
                number = int(value.strip())
            except ValueError:
                continue
            if key.strip() == "order":
                order = number
            elif key.strip() == "down" and number >= 0:
                timeout = number

    return {
        "onboot": onboot,
        "shutdown_order": order,
        "shutdown_timeout_seconds": timeout,
    }


def shutdown_policy_issues(policy: object | None, *, nut_available: bool) -> list[str]:
    if policy is None:
        return ["shutdown_policy_unavailable"]

    issues: list[str] = []
    if not nut_available:
        issues.append("nut_unavailable")
    if getattr(policy, "state", None) != "Enabled":
        issues.append("shutdown_policy_not_enabled")
    if getattr(policy, "role", None) != "primary":
        issues.append("nut_role_not_primary")
    if getattr(policy, "nut_monitor", None) != "active":
        issues.append("nut_monitor_not_active")
    if getattr(policy, "shutdown_enabled", None) is not True:
        issues.append("shutdown_disabled")
    if getattr(policy, "power_restore_delay_seconds", None) is None:
        issues.append("power_restore_delay_unreadable")
    return issues


class ShutdownAwareTopologyManager(TopologyManager):
    def guest_payload(self) -> dict[str, object]:
        payload = super().guest_payload()
        for plural, configs in (
            ("vms", self._vm_configs),
            ("lxcs", self._lxc_configs),
        ):
            records = payload.get(plural)
            if not isinstance(records, dict):
                continue
            for guest_id, raw in records.items():
                if not isinstance(raw, dict):
                    continue
                raw.update(parse_guest_shutdown_config(configs.get(str(guest_id), "")))
        return payload


class ShutdownAwareProductionCollectors(GuestAwareProductionCollectors):
    def __init__(self, *args, shutdown_history_tracker: ShutdownHistoryTracker, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.shutdown_history_tracker = shutdown_history_tracker
        self._guest_status_cache: dict[tuple[str, str], str] = {}
        self._pending_guest_shutdowns: dict[tuple[str, str], str | None] = {}

    @staticmethod
    def _latest_guest_record(
        payload: Mapping[str, object],
        kind: str,
        guest_id: str,
    ) -> Mapping[str, object] | None:
        latest = payload.get("guest_last_shutdowns")
        if not isinstance(latest, Mapping):
            return None
        records = latest.get(kind)
        if not isinstance(records, Mapping):
            return None
        raw = records.get(guest_id)
        return raw if isinstance(raw, Mapping) else None

    def guests(self) -> CollectorSample:
        sample = super().guests()
        if not isinstance(sample.data, Mapping):
            return sample

        data = dict(sample.data)
        current_statuses: dict[tuple[str, str], str] = {}
        guest_timeouts: dict[tuple[str, str], int] = {}
        guest_names: dict[tuple[str, str], str] = {}
        for plural, kind in (("vms", "vm"), ("lxcs", "lxc")):
            records = data.get(plural)
            if not isinstance(records, Mapping):
                continue
            for guest_id, raw in records.items():
                if not isinstance(raw, Mapping):
                    continue
                key = (kind, str(guest_id))
                current_statuses[key] = str(
                    raw.get("status") or "unknown"
                ).casefold()
                name = raw.get("name")
                if isinstance(name, str) and name.strip():
                    guest_names[key] = name.strip()
                timeout = raw.get("shutdown_timeout_seconds")
                if (
                    isinstance(timeout, int)
                    and not isinstance(timeout, bool)
                    and timeout >= 0
                ):
                    guest_timeouts[key] = timeout

        try:
            self.shutdown_history_tracker.record_guest_inventory(guest_names)
        except Exception:
            _LOG.exception("Не удалось сохранить snapshot имён VM/LXC")

        history_before = self.shutdown_history_tracker.payload()
        refresh_needed = not self._guest_status_cache
        for key, status in current_statuses.items():
            previous_status = self._guest_status_cache.get(key)
            if previous_status in {"running", "paused"} and status == "stopped":
                previous_record = self._latest_guest_record(
                    history_before,
                    key[0],
                    key[1],
                )
                previous_finished = (
                    previous_record.get("finished_at")
                    if isinstance(previous_record, Mapping)
                    and isinstance(previous_record.get("finished_at"), str)
                    else None
                )
                self._pending_guest_shutdowns.setdefault(key, previous_finished)
                refresh_needed = True

        if self._pending_guest_shutdowns:
            refresh_needed = True

        if refresh_needed:
            try:
                self.shutdown_history_tracker.refresh_current_guest_shutdowns()
            except Exception:
                _LOG.exception("Не удалось обновить историю shutdown VM/LXC")

        try:
            self.shutdown_history_tracker.enrich_guest_last_shutdowns(guest_timeouts)
        except Exception:
            _LOG.exception("Не удалось дополнить факты shutdown VM/LXC конфигурацией")

        history_after = self.shutdown_history_tracker.payload()

        for key, baseline_finished in list(self._pending_guest_shutdowns.items()):
            record = self._latest_guest_record(history_after, key[0], key[1])
            if not isinstance(record, Mapping):
                continue
            finished = record.get("finished_at")
            duration = record.get("duration_seconds")
            if (
                isinstance(finished, str)
                and isinstance(duration, int)
                and not isinstance(duration, bool)
                and finished != baseline_finished
            ):
                self._pending_guest_shutdowns.pop(key, None)

        for plural, kind in (("vms", "vm"), ("lxcs", "lxc")):
            records = data.get(plural)
            if not isinstance(records, Mapping):
                continue
            enriched: dict[str, object] = {}
            for guest_id, raw in records.items():
                if not isinstance(raw, Mapping):
                    continue
                item = dict(raw)
                latest = self._latest_guest_record(
                    history_after,
                    kind,
                    str(guest_id),
                )
                if isinstance(latest, Mapping):
                    item.update(
                        {
                            "last_shutdown_started_at": latest.get("started_at"),
                            "last_shutdown_finished_at": latest.get("finished_at"),
                            "last_shutdown_duration_seconds": latest.get(
                                "duration_seconds"
                            ),
                            "last_shutdown_timeout_seconds": latest.get(
                                "timeout_seconds"
                            ),
                            "last_shutdown_timeout_ratio": latest.get(
                                "timeout_ratio"
                            ),
                            "last_shutdown_assessment": latest.get(
                                "assessment",
                                "unknown",
                            ),
                            "last_shutdown_result": latest.get("result", "unknown"),
                            "last_shutdown_forced": latest.get("forced", False),
                            "last_shutdown_source": latest.get("source", "unknown"),
                        }
                    )
                enriched[str(guest_id)] = item
            data[plural] = enriched

        self._guest_status_cache = current_statuses
        return CollectorSample(data=data, metrics=dict(sample.metrics))

    def host(self) -> CollectorSample:
        sample = super().host()
        if not isinstance(sample.data, Mapping):
            return sample
        data = dict(sample.data)
        history = self.shutdown_history_tracker.payload()
        data["shutdown_history"] = history
        metrics = dict(sample.metrics)
        previous = history.get("previous_shutdown")
        if isinstance(previous, Mapping):
            shutdown_class = previous.get("shutdown_class")
            if isinstance(shutdown_class, str):
                metrics["previous_shutdown_class"] = MetricValue(
                    shutdown_class,
                    "discrete",
                )
        return CollectorSample(data=data, metrics=metrics)


class ShutdownAwareUpsRuntime(AdaptiveUpsRuntime):
    def __init__(
        self,
        *args,
        shutdown_history_tracker: ShutdownHistoryTracker,
        reader=read_ups,
        shutdown_budget_reader: Callable[[], ShutdownBudgetResult] | None = None,
        software_shutdown_executor: Callable[[str], None] | None = None,
        policy_reload_executor: Callable[[], None] | None = None,
        line_power_statistics_tracker: LinePowerStatisticsTracker | None = None,
        **kwargs,
    ) -> None:
        self.shutdown_history_tracker = shutdown_history_tracker
        self.shutdown_budget_reader = shutdown_budget_reader
        self.policy_reload_executor = policy_reload_executor
        self.software_shutdown_controller = (
            SoftwareShutdownController(software_shutdown_executor)
            if software_shutdown_executor is not None
            else None
        )
        self.last_software_shutdown_trigger: SoftwareShutdownTriggerResult | None = None
        self.last_shutdown_budget: ShutdownBudgetResult | None = None
        self._shutdown_budget_refreshed_at: float | None = None
        self._pending_policy_config_event: dict[str, object] | None = None
        self.line_power_statistics_tracker = line_power_statistics_tracker

        def observed_reader(config):
            try:
                snapshot = reader(config)
            except Exception:
                tracker = self.line_power_statistics_tracker
                if tracker is not None:
                    tracker.observe(LinePowerState.UNKNOWN)
                raise
            tracker = self.line_power_statistics_tracker
            if tracker is not None:
                tracker.observe(
                    line_power_state_from_snapshot(snapshot, nut_available=True)
                )
            self.shutdown_history_tracker.observe_ups(snapshot)
            return snapshot

        super().__init__(*args, reader=observed_reader, **kwargs)
        if self.line_power_statistics_tracker is None:
            self.line_power_statistics_tracker = LinePowerStatisticsTracker(
                StateStore(
                    self.state_store.path.with_name("line_power_statistics.json")
                ),
                now_local=self.now_local,
            )
        self.policy_apply_store = StateStore(
            self.state_store.path.with_name("ups_policy_apply.json")
        )
        transaction = self.policy_apply_store.load()
        if transaction.get("phase") == "event_pending":
            event = transaction.get("event")
            if isinstance(event, dict):
                self._pending_policy_config_event = dict(event)

    @property
    def software_shutdown_committed(self) -> bool:
        controller = self.software_shutdown_controller
        return bool(controller is not None and controller.committed)

    @property
    def software_shutdown_reason(self) -> str | None:
        controller = self.software_shutdown_controller
        return controller.committed_reason if controller is not None else None

    @staticmethod
    def _budget_reader_failure() -> ShutdownBudgetResult:
        return ShutdownBudgetResult(
            available=False,
            configured_guest_budget_seconds=None,
            observed_guest_budget_seconds=None,
            effective_guest_budget_seconds=None,
            hostsync_budget_seconds=None,
            finaldelay_seconds=None,
            observed_host_tail_seconds=None,
            host_tail_fallback_seconds=None,
            host_tail_budget_seconds=None,
            shutdown_budget_seconds=None,
            unavailable_reason="budget_reader_failed",
        )

    def _current_shutdown_budget(self, *, force: bool = False) -> ShutdownBudgetResult | None:
        budget_reader = self.shutdown_budget_reader
        if budget_reader is None:
            return None
        now = self.now_monotonic()
        should_refresh = (
            force
            or self.last_shutdown_budget is None
            or self._shutdown_budget_refreshed_at is None
            or now - self._shutdown_budget_refreshed_at >= SHUTDOWN_BUDGET_REFRESH_SECONDS
        )
        if not should_refresh:
            return self.last_shutdown_budget

        try:
            budget = budget_reader()
        except Exception as exc:
            budget = self._budget_reader_failure()
            self.log.warning(
                "Не удалось обновить shutdown budget UPS (%s); Trigger B временно недоступен",
                type(exc).__name__,
            )
        self.last_shutdown_budget = budget
        self._shutdown_budget_refreshed_at = now
        fingerprint = budget.configuration_fingerprint
        if isinstance(fingerprint, str) and fingerprint:
            try:
                recorder = getattr(
                    self.shutdown_history_tracker,
                    "record_shutdown_plan",
                    None,
                )
                if callable(recorder):
                    recorder(
                        configuration_fingerprint=fingerprint,
                        planned_shutdown_seconds=budget.shutdown_budget_seconds,
                        planned_guest_shutdown_seconds=(
                            budget.effective_guest_budget_seconds
                        ),
                        planned_all_guest_shutdown_seconds=(
                            budget.all_configured_guest_budget_seconds
                        ),
                        running_guests=list(budget.running_guests),
                        shutdown_sequence=[
                            list(group) for group in budget.shutdown_sequence
                        ],
                    )
                else:
                    legacy_recorder = getattr(
                        self.shutdown_history_tracker,
                        "record_shutdown_budget_fingerprint",
                        None,
                    )
                    if callable(legacy_recorder):
                        legacy_recorder(fingerprint)
            except Exception:
                self.log.exception("Не удалось сохранить snapshot shutdown plan")
        return budget

    def _enqueue_shutdown_committed_event(
        self,
        result: SoftwareShutdownTriggerResult,
        budget: ShutdownBudgetResult,
    ) -> None:
        outbox = self.machine_event_outbox
        public_reason = _PUBLIC_SHUTDOWN_REASON.get(result.reason or "")
        if outbox is None or public_reason is None:
            return

        observed_at = self.now_iso()
        policy = self.policy_active
        payload: dict[str, object] = {
            "schema_version": 2,
            "event_type": "shutdown_committed",
            "observed_at": observed_at,
            "reason": public_reason,
            "battery_charge_percent": result.charge_percent,
            "battery_runtime_seconds": result.runtime_seconds,
            "shutdown_budget_seconds": budget.shutdown_budget_seconds,
            "runtime_reserve_seconds": (
                policy.runtime_reserve_seconds if policy is not None else None
            ),
            "runtime_guard_threshold_seconds": result.runtime_guard_threshold_seconds,
        }
        payload.update(ups_snapshot_event_context(self.last_snapshot))
        payload.update(line_power_event_context(self.line_power_statistics_tracker))
        outbox.enqueue(
            f"shutdown_committed:{observed_at}:{public_reason}",
            payload,
        )
        self._flush_machine_event_outbox()

    def _evaluate_software_shutdown(self, *, force_budget_refresh: bool = False) -> None:
        controller = self.software_shutdown_controller
        snapshot = self.last_snapshot
        if controller is None or snapshot is None or not self.nut_available:
            return
        budget = self._current_shutdown_budget(force=force_budget_refresh)
        if budget is None:
            return

        was_committed = controller.committed
        try:
            result = controller.evaluate_and_commit(
                snapshot,
                self.policy_active,
                budget,
            )
            self.last_software_shutdown_trigger = result
        except Exception as exc:
            self.log.error(
                "Не удалось зафиксировать software shutdown UPS (%s); повтор на следующем опросе",
                type(exc).__name__,
            )
            return

        if not was_committed and controller.committed and result is not None and result.reason:
            try:
                self.shutdown_history_tracker.record_software_shutdown_commit(
                    result.reason,
                    snapshot,
                )
            except Exception:
                self.log.exception("Не удалось сохранить причину software shutdown UPS")
            self._enqueue_shutdown_committed_event(result, budget)

    def _policy_state_backup(self) -> dict[str, object]:
        return {
            "active": self.policy_active,
            "draft": self.policy_draft,
            "status": self.policy_status,
            "apply_result": self.policy_apply_result,
            "last_applied": self.policy_last_applied,
            "revision": self.policy_revision,
            "hash": self.policy_hash,
            "validation": self.policy_validation,
        }

    def _restore_policy_state(self, backup: Mapping[str, object]) -> None:
        self.policy_active = backup["active"]  # type: ignore[assignment]
        self.policy_draft = backup["draft"]  # type: ignore[assignment]
        self.policy_status = str(backup["status"])
        self.policy_apply_result = str(backup["apply_result"])
        self.policy_last_applied = backup["last_applied"]  # type: ignore[assignment]
        self.policy_revision = int(backup["revision"])
        self.policy_hash = backup["hash"]  # type: ignore[assignment]
        self.policy_validation = backup["validation"]  # type: ignore[assignment]

    def _clear_policy_apply_transaction(self) -> None:
        self.policy_apply_store.path.unlink(missing_ok=True)

    def _save_policy_apply_transaction(self, transaction: Mapping[str, object]) -> None:
        self.policy_apply_store.save(transaction)

    def _rollback_from_transaction(
        self,
        transaction: Mapping[str, object],
        *,
        message: str,
    ) -> None:
        old_active = policy_from_mapping(transaction.get("old_values"))
        self.policy_active = old_active
        self.policy_draft = old_active or self.policy_draft
        old_revision = transaction.get("old_revision")
        self.policy_revision = old_revision if isinstance(old_revision, int) else 0
        old_hash = transaction.get("old_hash")
        self.policy_hash = old_hash if isinstance(old_hash, str) else None
        old_last_applied = transaction.get("old_last_applied")
        self.policy_last_applied = (
            old_last_applied if isinstance(old_last_applied, str) else None
        )
        self.policy_status = "Apply failed"
        self.policy_apply_result = message
        self._pending_policy_config_event = None
        self._clear_policy_apply_transaction()
        self._persist()

    def _verify_persisted_policy(
        self,
        target: UpsPolicyDraft,
        *,
        revision: int,
        target_hash: str,
    ) -> bool:
        persisted = self.state_store.load()
        active = policy_from_mapping(persisted.get("policy_active"))
        return bool(
            active == target
            and persisted.get("policy_revision") == revision
            and persisted.get("policy_hash") == target_hash
        )

    def _apply_policy(self) -> None:
        draft = UpsPolicyDraft(**self.policy_draft.as_dict())
        try:
            validation = validate_policy(draft)
        except PolicyValidationError as exc:
            self.policy_status = "Validation failed"
            self.policy_apply_result = str(exc)
            self.policy_draft = self.policy_active or self.policy_draft
            self._pending_policy_config_event = None
            self._persist()
            return

        if self.policy_active == draft:
            self.policy_draft = draft
            self.policy_status = "Active"
            self.policy_apply_result = "No changes"
            self.policy_validation = validation
            self._pending_policy_config_event = None
            self._clear_policy_apply_transaction()
            self._persist()
            return

        if self.policy_reload_executor is None:
            self.policy_draft = self.policy_active or self.policy_draft
            self.policy_status = "Apply failed"
            self.policy_apply_result = "Reload dh_pve_app.service не настроен."
            self._pending_policy_config_event = None
            self._persist()
            return

        old_values = self.policy_active.as_dict() if self.policy_active is not None else {}
        transaction: dict[str, object] = {
            "phase": "prepared",
            "requested_at": self.now_iso(),
            "old_values": old_values,
            "old_revision": self.policy_revision,
            "old_hash": self.policy_hash,
            "old_last_applied": self.policy_last_applied,
            "new_values": draft.as_dict(),
            "target_revision": self.policy_revision + 1,
            "target_hash": policy_hash(draft),
        }
        try:
            self._save_policy_apply_transaction(transaction)
            self.policy_status = "Applying"
            self.policy_apply_result = "Ожидается reload dh_pve_app.service."
            self.policy_validation = validation
            self._persist()
            self.policy_reload_executor()
            transaction["phase"] = "reload_requested"
            transaction["reload_requested_at"] = self.now_iso()
            self._save_policy_apply_transaction(transaction)
        except Exception as exc:
            self.log.error("UPS policy reload request failed: %s", type(exc).__name__)
            self._rollback_from_transaction(
                transaction,
                message="Не удалось выполнить reload dh_pve_app.service.",
            )

    def complete_policy_reload(self) -> bool:
        transaction = self.policy_apply_store.load()
        if transaction.get("phase") != "reload_requested":
            return False

        target = policy_from_mapping(transaction.get("new_values"))
        target_revision = transaction.get("target_revision")
        target_hash = transaction.get("target_hash")
        if (
            target is None
            or not isinstance(target_revision, int)
            or not isinstance(target_hash, str)
        ):
            self._rollback_from_transaction(
                transaction,
                message="Транзакция Apply повреждена; сохранена предыдущая политика.",
            )
            return False

        try:
            validation = validate_policy(target)
            self.policy_active = target
            self.policy_draft = target
            self.policy_status = "Active"
            self.policy_apply_result = "Applied"
            self.policy_last_applied = self.now_iso()
            self.policy_revision = target_revision
            self.policy_hash = target_hash
            self.policy_validation = validation
            self._persist()
            if not self._verify_persisted_policy(
                target,
                revision=target_revision,
                target_hash=target_hash,
            ):
                raise RuntimeError("policy persistence verification mismatch")
        except Exception as exc:
            self.log.error("UPS policy post-reload verification failed: %s", type(exc).__name__)
            self._rollback_from_transaction(
                transaction,
                message="Reload выполнен, но эффективная политика не прошла проверку.",
            )
            return False

        event = {
            "schema_version": 2,
            "event_type": "config_changed",
            "observed_at": self.now_iso(),
            "old_values": transaction.get("old_values", {}),
            "new_values": target.as_dict(),
            "previous_revision": transaction.get("old_revision"),
            "current_revision": target_revision,
        }
        self._pending_policy_config_event = event
        transaction = dict(transaction)
        transaction["phase"] = "event_pending"
        transaction["event"] = event
        self._save_policy_apply_transaction(transaction)

        self._shutdown_budget_refreshed_at = None
        self._collect(force=True)
        return True

    def _recover_interrupted_policy_apply(self) -> None:
        transaction = self.policy_apply_store.load()
        phase = transaction.get("phase")
        if phase in {"prepared", "reload_requested"}:
            self._rollback_from_transaction(
                transaction,
                message="Применение политики было прервано до post-reload проверки.",
            )
        elif phase == "event_pending":
            event = transaction.get("event")
            if isinstance(event, dict):
                self._pending_policy_config_event = dict(event)

    def startup(self) -> bool:
        self._recover_interrupted_policy_apply()
        return super().startup()

    def _flush_pending_policy_config_event(self) -> None:
        event = self._pending_policy_config_event
        if event is None:
            return
        publish = getattr(self.bridge, "publish_ups_diagnostic_event", None)
        if not callable(publish):
            return
        if publish(dict(event)):
            self._pending_policy_config_event = None
            transaction = self.policy_apply_store.load()
            if transaction.get("phase") == "event_pending":
                self._clear_policy_apply_transaction()

    def _collect(self, *, force: bool = False, manual_refresh: bool = False) -> bool:
        result = super()._collect(force=force, manual_refresh=manual_refresh)
        if self.nut_available and self.last_snapshot is not None:
            self._evaluate_software_shutdown(force_budget_refresh=manual_refresh)
        if result:
            self._flush_pending_policy_config_event()
        return result

    def _auxiliary_fields(self) -> dict[str, object]:
        fields = super()._auxiliary_fields()
        fields["line_power_statistics"] = (
            self.line_power_statistics_tracker.snapshot().as_payload()
        )
        budget = self._current_shutdown_budget()
        budget_payload = _shutdown_budget_payload(budget)
        fields["shutdown_budget"] = budget_payload

        history = self.shutdown_history_tracker.payload()
        previous = history.get("previous_shutdown")
        latest_guests = history.get("guest_last_shutdowns")
        guest_budget = budget.effective_guest_budget_seconds if budget is not None else None
        total_budget = budget.shutdown_budget_seconds if budget is not None else None
        readiness = evaluate_shutdown_readiness(
            ups_present=True,
            guest_shutdown_budget_seconds=guest_budget,
            previous_shutdown=previous if isinstance(previous, Mapping) else None,
            guest_shutdowns=latest_guests if isinstance(latest_guests, Mapping) else None,
            additional_issues=shutdown_policy_issues(
                self.shutdown_policy,
                nut_available=self.nut_available,
            ),
        )
        readiness["shutdown_budget_seconds"] = total_budget
        fields["shutdown_readiness"] = readiness
        return fields

    def _build_discovery(self) -> dict[str, object]:
        capabilities = self.capabilities
        if capabilities is not None and not hasattr(capabilities, "supports_test"):
            capabilities = None
        return build_shutdown_aware_ups_discovery_payload(
            config=self.mqtt_config,
            identity=self.identity,
            version=self.version,
            snapshot=self.last_snapshot,
            capabilities=capabilities,
            shutdown_policy=self.shutdown_policy,
        )
