from __future__ import annotations

import re
from collections.abc import Mapping

from .app import CollectorSample
from .publish_policy import MetricValue
from .production_guest import GuestAwareProductionCollectors
from .shutdown_discovery import build_shutdown_aware_ups_discovery_payload
from .shutdown_history import ShutdownHistoryTracker, evaluate_shutdown_readiness
from .topology import TopologyManager
from .ups_nut import read_ups
from .ups_runtime import UpsRuntime


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


class ShutdownAwareUpsRuntime(UpsRuntime):
    def __init__(
        self,
        *args,
        shutdown_history_tracker: ShutdownHistoryTracker,
        reader=read_ups,
        **kwargs,
    ) -> None:
        self.shutdown_history_tracker = shutdown_history_tracker

        def observed_reader(config):
            snapshot = reader(config)
            self.shutdown_history_tracker.observe_ups(snapshot)
            return snapshot

        super().__init__(*args, reader=observed_reader, **kwargs)

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
