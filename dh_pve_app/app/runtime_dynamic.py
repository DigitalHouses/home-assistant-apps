from __future__ import annotations

import json
from collections.abc import Callable, Mapping

from .app import DhPveRuntime


_LEGACY_DISCOVERY_REMOVALS = {
    "setting_fast_poll_interval_seconds": "number",
    "setting_disk_poll_interval_seconds": "number",
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
        self._component_tombstones_applied: set[str] = set()

    def _inventory(self) -> dict[str, object]:
        return {
            name: self._jsonable(state.data)
            for name, state in self._subsystems.items()
            if state.data is not None
        }

    @staticmethod
    def _split_component_tombstones(
        payload: dict[str, object],
    ) -> tuple[dict[str, object], dict[str, str]]:
        raw_components = payload.get("components")
        if not isinstance(raw_components, dict):
            return payload, {}

        final_components: dict[str, object] = {}
        tombstones: dict[str, str] = {}
        for key, component in raw_components.items():
            if (
                isinstance(component, dict)
                and set(component) == {"platform"}
                and isinstance(component.get("platform"), str)
            ):
                tombstones[str(key)] = str(component["platform"])
                continue
            final_components[str(key)] = component

        if not tombstones:
            return payload, {}

        final_payload = dict(payload)
        final_payload["components"] = final_components
        return final_payload, tombstones

    @staticmethod
    def _component_cleanup_payload(
        payload: dict[str, object],
        removals: Mapping[str, str],
    ) -> dict[str, object]:
        cleanup = dict(payload)
        raw_components = payload.get("components")
        components = dict(raw_components) if isinstance(raw_components, dict) else {}
        for key, platform in removals.items():
            components[key] = {"platform": platform}
        cleanup["components"] = components
        return cleanup

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
        built_payload = self.discovery_builder(self._inventory())
        payload, tombstones = self._split_component_tombstones(built_payload)

        raw_components = payload.get("components")
        if isinstance(raw_components, dict):
            self._component_tombstones_applied.difference_update(
                str(key) for key in raw_components
            )
        pending_tombstones = {
            key: platform
            for key, platform in tombstones.items()
            if key not in self._component_tombstones_applied
        }

        fingerprint = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if (
            not force
            and fingerprint == self._discovery_fingerprint
            and not pending_tombstones
        ):
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

        if pending_tombstones:
            cleanup = self._component_cleanup_payload(payload, pending_tombstones)
            setter(cleanup)
            if not self.bridge.publish_discovery():
                self._last_discovery_ok = False
                return False
            self._component_tombstones_applied.update(pending_tombstones)

        setter(payload)
        ok = self.bridge.publish_discovery()
        self._last_discovery_ok = ok
        if ok:
            self._discovery_fingerprint = fingerprint
        return ok

    def _sync_discovery_before_state(self) -> bool:
        """Keep retained discovery current before any state uses its templates."""
        return self.sync_discovery(force=self._discovery_fingerprint is None)

    def _run_group_publication(self, *args, **kwargs) -> bool:
        if not self._sync_discovery_before_state():
            return False
        return super()._run_group_publication(*args, **kwargs)

    def _run_legacy_publication(self, *args, **kwargs) -> bool:
        if not self._sync_discovery_before_state():
            return False
        return super()._run_legacy_publication(*args, **kwargs)

    def startup(self) -> bool:
        cleanup_ok = True
        if self._group_capable():
            cleaner = getattr(self.bridge, "clear_legacy_state", None)
            if callable(cleaner):
                cleanup_ok = bool(cleaner())
        settings_ok = self.publish_settings()
        state_ok = self.run_collection(force=True)
        if self._static_collectors_available():
            self._prime_version_fingerprint()
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
