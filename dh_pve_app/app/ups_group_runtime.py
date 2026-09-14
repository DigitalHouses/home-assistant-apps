from __future__ import annotations

from .presentation_ups import UpsPresentationRouter
from .ups_runtime import UpsRuntime


class AdaptiveUpsRuntime(UpsRuntime):
    """UPS runtime that publishes independent retained presentation groups.

    The legacy monolithic path remains available when a bridge does not expose
    ``publish_ups_state_group`` so older unit fakes and compatibility callers
    keep their existing contract. Production MqttBridge uses this group path.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.presentation = UpsPresentationRouter(
            source_interval_seconds=self.config.poll_interval_seconds
        )
        self._last_group_payloads: dict[str, dict[str, object]] = {}

    def _group_capable(self) -> bool:
        return callable(getattr(self.bridge, "publish_ups_state_group", None))

    def _publish_groups(self, publications) -> bool:
        publish = getattr(self.bridge, "publish_ups_state_group")
        for publication in publications:
            if not publish(publication.group, publication.payload):
                return False
            self._last_group_payloads[publication.group] = dict(publication.payload)
        return True

    def _collect(self, *, force: bool = False, manual_refresh: bool = False) -> bool:
        if not self._group_capable():
            return super()._collect(force=force, manual_refresh=manual_refresh)

        collected_at = self.now_iso()
        now = self.now_monotonic()
        try:
            snapshot = self.reader(self.config)
        except Exception as exc:
            self.nut_available = False
            error = f"{type(exc).__name__}: {exc}"
            self.log.warning("Не удалось прочитать UPS через NUT: %s", exc)
            payload = self._failure_payload(collected_at=collected_at, error=error)
            publications = self.presentation.route(
                payload,
                now=now,
                force=bool(force and not self._last_group_payloads),
                manual=False,
            )
            self._publish_groups(publications)
            self.sync_discovery(force=False)
            return False

        self.nut_available = True
        self.last_snapshot = snapshot
        history_changed = self._update_open_test_history(snapshot)
        previous_refresh = self.last_refresh
        if manual_refresh:
            self.last_refresh = collected_at

        payload = self._success_payload(snapshot, collected_at=collected_at)
        discovery_ok = self.sync_discovery(force=force or manual_refresh)
        publications = self.presentation.route(
            payload,
            now=now,
            # ``force=True`` is used by several existing UPS event paths. Only
            # startup needs to force all groups; later semantic changes are
            # detected by their own change-only groups.
            force=bool(force and not self._last_group_payloads),
            manual=manual_refresh,
        )
        state_ok = self._publish_groups(publications)

        if state_ok:
            self._last_state_payload = payload
            if manual_refresh or history_changed:
                self._persist()
        elif manual_refresh:
            self.last_refresh = previous_refresh

        return bool(discovery_ok and state_ok)

    def republish_after_reconnect(self) -> bool:
        if not self._group_capable():
            return super().republish_after_reconnect()

        availability_ok = self.bridge.publish_ups_availability(True)
        if not self._last_group_payloads:
            self._refresh_auxiliary()
            self._refresh_policy_validation()
            return bool(availability_ok and self._collect(force=True))

        discovery_ok = self.sync_discovery(force=True)
        state_ok = True
        publish = getattr(self.bridge, "publish_ups_state_group")
        for group, payload in self._last_group_payloads.items():
            state_ok = bool(publish(group, payload)) and state_ok
        return bool(availability_ok and discovery_ok and state_ok)
