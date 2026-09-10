from __future__ import annotations

import json
from collections.abc import Callable, Mapping

from .app import DhPveRuntime


class DynamicDiscoveryRuntime(DhPveRuntime):
    """DhPveRuntime with inventory-driven MQTT Device Discovery."""

    def __init__(
        self,
        *args,
        discovery_builder: Callable[[Mapping[str, object]], dict[str, object]],
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.discovery_builder = discovery_builder
        self._discovery_fingerprint: str | None = None
        self._last_discovery_ok = False

    def _inventory(self) -> dict[str, object]:
        return {
            name: self._jsonable(state.data)
            for name, state in self._subsystems.items()
            if state.data is not None
        }

    def sync_discovery(self, *, force: bool = False) -> bool:
        payload = self.discovery_builder(self._inventory())
        fingerprint = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if not force and fingerprint == self._discovery_fingerprint:
            return True

        setter = getattr(self.bridge, "set_discovery_payload", None)
        if not callable(setter):
            return False
        setter(payload)
        ok = self.bridge.publish_discovery()
        self._last_discovery_ok = ok
        if ok:
            self._discovery_fingerprint = fingerprint
        return ok

    def run_collection(self, *args, **kwargs) -> bool:
        state_published = super().run_collection(*args, **kwargs)
        self.sync_discovery(force=self._discovery_fingerprint is None)
        return state_published

    def startup(self) -> bool:
        settings_ok = self.publish_settings()
        state_ok = self.run_collection(force=True)
        return settings_ok and state_ok and self._last_discovery_ok

    def republish_after_reconnect(self) -> bool:
        discovery_ok = self.sync_discovery(force=True)
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
