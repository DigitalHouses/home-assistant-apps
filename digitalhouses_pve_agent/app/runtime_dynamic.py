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

_DISCOVERY_MANIFEST_KEY = "discovery_manifest"


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
        self._discovery_manifest = self._load_discovery_manifest()

    def _load_discovery_manifest(self) -> dict[str, dict[str, object]]:
        try:
            persisted = self.state_store.load()
        except Exception:
            return {}
        raw = persisted.get(_DISCOVERY_MANIFEST_KEY)
        if not isinstance(raw, dict):
            return {}

        manifest: dict[str, dict[str, object]] = {}
        for key, item in raw.items():
            if not isinstance(key, str) or not isinstance(item, dict):
                continue
            platform = item.get("platform")
            topics = item.get("topics")
            if not isinstance(platform, str) or not isinstance(topics, list):
                continue
            normalized_topics = sorted(
                {
                    str(topic)
                    for topic in topics
                    if isinstance(topic, str) and topic
                }
            )
            manifest[key] = {
                "platform": platform,
                "topics": normalized_topics,
            }
        return manifest

    def _persist_runtime_state(self) -> None:
        try:
            persisted = dict(self.state_store.load())
        except Exception:
            persisted = {}
        persisted.update(
            {
                "last_refresh": self.last_refresh,
                "runtime_settings": self.settings.as_dict(),
                _DISCOVERY_MANIFEST_KEY: self._discovery_manifest,
            }
        )
        self.state_store.save(persisted)

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

    @staticmethod
    def _component_topics(component: Mapping[str, object]) -> list[str]:
        topics: set[str] = set()
        for key in ("state_topic", "json_attributes_topic"):
            topic = component.get(key)
            if isinstance(topic, str) and topic:
                topics.add(topic)

        availability = component.get("availability")
        if isinstance(availability, list):
            for item in availability:
                if not isinstance(item, Mapping):
                    continue
                topic = item.get("topic")
                if isinstance(topic, str) and topic:
                    topics.add(topic)

        for topic in tuple(topics):
            if "/problems/" in topic and topic.endswith("/state"):
                topics.add(topic.removesuffix("/state") + "/metric")

        return sorted(topics)

    @classmethod
    def _manifest_from_payload(
        cls,
        payload: Mapping[str, object],
    ) -> dict[str, dict[str, object]]:
        raw_components = payload.get("components")
        if not isinstance(raw_components, Mapping):
            return {}

        manifest: dict[str, dict[str, object]] = {}
        for key, component in raw_components.items():
            if not isinstance(component, Mapping):
                continue
            platform = component.get("platform")
            if not isinstance(platform, str):
                continue
            manifest[str(key)] = {
                "platform": platform,
                "topics": cls._component_topics(component),
            }
        return manifest

    def _removed_component_cleanup(
        self,
        current_manifest: Mapping[str, Mapping[str, object]],
    ) -> tuple[dict[str, str], tuple[str, ...]]:
        removals: dict[str, str] = {}
        candidate_topics: set[str] = set()

        for key, previous in self._discovery_manifest.items():
            if key in current_manifest:
                continue
            platform = previous.get("platform")
            if not isinstance(platform, str):
                continue
            removals[key] = platform
            topics = previous.get("topics")
            if isinstance(topics, list):
                candidate_topics.update(
                    str(topic)
                    for topic in topics
                    if isinstance(topic, str) and topic
                )

        current_topics = {
            str(topic)
            for item in current_manifest.values()
            for topic in item.get("topics", [])
            if isinstance(topic, str) and topic
        }
        return removals, tuple(sorted(candidate_topics - current_topics))

    def _drop_removed_group_cache(self, topics: tuple[str, ...]) -> None:
        marker = "/state/"
        for topic in topics:
            if marker not in topic:
                continue
            group = topic.split(marker, 1)[1]
            if not group:
                continue
            self._published_groups.pop(group, None)
            self._pending_groups.pop(group, None)

    def sync_discovery(self, *, force: bool = False) -> bool:
        built_payload = self.discovery_builder(self._inventory())
        payload, tombstones = self._split_component_tombstones(built_payload)
        current_manifest = self._manifest_from_payload(payload)
        removed_components, retained_topics = self._removed_component_cleanup(
            current_manifest
        )
        for key, platform in removed_components.items():
            tombstones.setdefault(key, platform)

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
        manifest_changed = current_manifest != self._discovery_manifest
        if (
            not force
            and fingerprint == self._discovery_fingerprint
            and not pending_tombstones
            and not manifest_changed
        ):
            return True

        setter = getattr(self.bridge, "set_discovery_payload", None)
        if not callable(setter):
            return False

        if retained_topics:
            cleaner = getattr(self.bridge, "clear_retained_topics", None)
            if not callable(cleaner) or not cleaner(retained_topics):
                self._last_discovery_ok = False
                return False
            self._drop_removed_group_cache(retained_topics)

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
            if manifest_changed:
                previous_manifest = self._discovery_manifest
                self._discovery_manifest = current_manifest
                try:
                    self._persist_runtime_state()
                except Exception:
                    self._discovery_manifest = previous_manifest
                    self._last_discovery_ok = False
                    return False
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
