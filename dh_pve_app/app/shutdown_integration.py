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
from .ups_shutdown_budget import ShutdownBudgetResult
from .ups_trigger import SoftwareShutdownController, SoftwareShutdownTriggerResult


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
    if getattr(policy, "upssched_present", None) is not True or getattr(
        policy, "upssched_active", None
    ) is not True:
        issues.append("upssched_inactive")
    if getattr(policy, "on_battery_delay_minutes", None) is None:
        issues.append("on_battery_delay_unreadable")
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

    def _evaluate_software_shutdown(self) -> None:
        controller = self.software_shutdown_controller
        budget_reader = self.shutdown_budget_reader
        snapshot = self.last_snapshot
        if (
            controller is None
            or budget_reader is None
            or snapshot is None
            or not self.nut_available
        ):
            return
        try:
            budget = budget_reader()
            self.last_shutdown_budget = budget
            self.last_software_shutdown_trigger = controller.evaluate_and_commit(
                snapshot,
                self.policy_active,
                budget,
            )
        except Exception as exc:
            # A local FSD/helper failure must never kill monitoring. Do not latch;
            # the controller will retry on the next successful UPS sample.
            self.log.error(
                "Не удалось зафиксировать software shutdown UPS (%s); повтор на следующем опросе",
                type(exc).__name__,
            )

    def _collect(self, *, force: bool = False, manual_refresh: bool = False) -> bool:
        result = super()._collect(force=force, manual_refresh=manual_refresh)
        if self.nut_available and self.last_snapshot is not None:
            self._evaluate_software_shutdown()
        return result

    def _auxiliary_fields(self) -> dict[str, object]:
        fields = super()._auxiliary_fields()
        budget = (
            self.shutdown_policy.guest_shutdown_budget_seconds
            if self.shutdown_policy is not None
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
