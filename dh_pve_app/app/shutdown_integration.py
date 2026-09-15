from __future__ import annotations

import re
from collections.abc import Callable, Mapping

from .app import CollectorSample
from .publish_policy import MetricValue
from .production_guest import GuestAwareProductionCollectors
from .shutdown_discovery import build_shutdown_aware_ups_discovery_payload
from .shutdown_history import ShutdownHistoryTracker, evaluate_shutdown_readiness
from .topology import TopologyManager
from .ups_group_runtime import AdaptiveUpsRuntime
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
        **kwargs,
    ) -> None:
        self.shutdown_history_tracker = shutdown_history_tracker
        self.shutdown_budget_reader = shutdown_budget_reader
        self.software_shutdown_controller = (
            SoftwareShutdownController(software_shutdown_executor)
            if software_shutdown_executor is not None
            else None
        )
        self.last_software_shutdown_trigger: SoftwareShutdownTriggerResult | None = None
        self.last_shutdown_budget: ShutdownBudgetResult | None = None
        self._shutdown_budget_refreshed_at: float | None = None
        self._pending_policy_config_event: dict[str, object] | None = None

        def observed_reader(config):
            snapshot = reader(config)
            self.shutdown_history_tracker.observe_ups(snapshot)
            return snapshot

        super().__init__(*args, reader=observed_reader, **kwargs)

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
                self.shutdown_history_tracker.record_shutdown_budget_fingerprint(fingerprint)
            except Exception:
                self.log.exception("Не удалось сохранить fingerprint shutdown budget")
        return budget

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
            # A local FSD/helper failure must never kill monitoring. Do not latch;
            # the controller will retry on the next successful UPS sample.
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
                # The shutdown commitment has already happened; history failure
                # is diagnostic only and must not alter the irreversible latch.
                self.log.exception("Не удалось сохранить причину software shutdown UPS")

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
            self._persist()
            return

        backup = self._policy_state_backup()
        old_values = self.policy_active.as_dict() if self.policy_active is not None else {}
        new_revision = self.policy_revision + 1
        new_hash = policy_hash(draft)
        try:
            self.policy_active = draft
            self.policy_draft = draft
            self.policy_status = "Active"
            self.policy_apply_result = "Applied"
            self.policy_last_applied = self.now_iso()
            self.policy_revision = new_revision
            self.policy_hash = new_hash
            self.policy_validation = validation
            self._persist()
            if not self._verify_persisted_policy(
                draft,
                revision=new_revision,
                target_hash=new_hash,
            ):
                raise RuntimeError("policy persistence verification mismatch")
        except Exception as exc:
            self._restore_policy_state(backup)
            self.policy_draft = self.policy_active or self.policy_draft
            self.policy_status = "Apply failed"
            self.policy_apply_result = "Не удалось применить и проверить политику."
            self._pending_policy_config_event = None
            try:
                self._persist()
            except Exception:
                self.log.exception("Не удалось сохранить rollback UPS policy")
            self.log.error("UPS policy Apply rollback: %s", type(exc).__name__)
            return

        # A successful Apply may affect future budget-derived policy fields.
        # Force a fresh cheap SLOW budget read before the next trigger decision.
        self._shutdown_budget_refreshed_at = None
        self._pending_policy_config_event = {
            "schema_version": 1,
            "event_type": "config_changed",
            "category": "policy",
            "severity": "info",
            "object_id": "ups_trigger_policy",
            "object_name": "UPS Trigger Policy",
            "summary": "UPS Trigger Policy изменена",
            "details": "Активная политика UPS успешно применена и проверена.",
            "old_values": old_values,
            "new_values": draft.as_dict(),
        }

    def _flush_pending_policy_config_event(self) -> None:
        event = self._pending_policy_config_event
        if event is None:
            return
        publish = getattr(self.bridge, "publish_ups_diagnostic_event", None)
        if not callable(publish):
            return
        payload = dict(event)
        try:
            payload["active_problem_count"] = self.problem_engine.aggregate().count
        except Exception:
            payload["active_problem_count"] = 0
        if publish(payload):
            self._pending_policy_config_event = None

    def _collect(self, *, force: bool = False, manual_refresh: bool = False) -> bool:
        result = super()._collect(force=force, manual_refresh=manual_refresh)
        if self.nut_available and self.last_snapshot is not None:
            self._evaluate_software_shutdown(force_budget_refresh=manual_refresh)
        if result:
            self._flush_pending_policy_config_event()
        return result

    def _auxiliary_fields(self) -> dict[str, object]:
        fields = super()._auxiliary_fields()
        budget = (
            self.last_shutdown_budget.shutdown_budget_seconds
            if self.last_shutdown_budget is not None
            else None
        )
        history = self.shutdown_history_tracker.payload()
        previous = history.get("previous_shutdown")
        fields["shutdown_readiness"] = evaluate_shutdown_readiness(
            ups_present=True,
            guest_shutdown_budget_seconds=budget,
            previous_shutdown=previous if isinstance(previous, Mapping) else None,
            additional_issues=shutdown_policy_issues(
                self.shutdown_policy,
                nut_available=self.nut_available,
            ),
        )
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
