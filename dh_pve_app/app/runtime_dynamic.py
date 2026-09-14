from __future__ import annotations

import json
from collections.abc import Callable, Mapping

from .app import DhPveRuntime


_LEGACY_DISCOVERY_REMOVALS = {
    "setting_cpu_publish_delta": "number",
    "setting_memory_publish_delta": "number",
    "setting_temperature_publish_delta": "number",
    "setting_storage_publish_delta": "number",
    "setting_fan_publish_delta_rpm": "number",
    "setting_gpu_publish_delta": "number",
}


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
        self._legacy_discovery_cleanup_done = False

    def _inventory(self) -> dict[str, object]:
        return {
            name: self._jsonable(state.data)
            for name, state in self._subsystems.items()
            if state.data is not None
        }

    @staticmethod
    def _legacy_cleanup_payload(payload: dict[str, object]) -> dict[str, object] | None:
        raw_components = payload.get("components")
        if not isinstance(raw_components, dict):
            return None

        cleanup_components = dict(raw_components)
        added = False
        for key, platform in _LEGACY_DISCOVERY_REMOVALS.items():
            if key in cleanup_components:
                continue
            cleanup_components[key] = {"platform": platform}
            added = True
        if not added:
            return None

        cleanup = dict(payload)
        cleanup["components"] = cleanup_components
        return cleanup

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

        if not self._legacy_discovery_cleanup_done:
            cleanup = self._legacy_cleanup_payload(payload)
            if cleanup is not None:
                setter(cleanup)
                if not self.bridge.publish_discovery():
                    self._last_discovery_ok = False
                    return False
            self._legacy_discovery_cleanup_done = True

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
        cleanup_ok = True
        if self._group_capable():
            cleaner = getattr(self.bridge, "clear_legacy_state", None)
            if callable(cleaner):
                cleanup_ok = bool(cleaner())
        settings_ok = self.publish_settings()
        state_ok = self.run_collection(force=True)
        return cleanup_ok and settings_ok and state_ok and self._last_discovery_ok

    def republish_after_reconnect(self) -> bool:
        discovery_ok = self.sync_discovery(force=True)
        settings_ok = self.publish_settings()
        if self._group_capable():
            state_ok = self._republish_group_cache()
            return discovery_ok and settings_ok and state_ok
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
