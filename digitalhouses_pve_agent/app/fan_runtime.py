from __future__ import annotations

import logging
import queue
from collections.abc import Callable

from .collectors.cooling import FanSnapshot
from .fan_max_rpm import FanMaxRpmRegistry
from .runtime_problems import ProblemAwareRuntime
from .state_store import StateStore


class FanAwareRuntime(ProblemAwareRuntime):
    """Persist user RPM limits, then refresh the fan readings."""

    def __init__(
        self,
        *args,
        fan_max_rpm_registry: FanMaxRpmRegistry,
        fan_source: Callable[[], tuple[FanSnapshot, ...]],
        fan_presence_state_store: StateStore,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.fan_max_rpm_registry = fan_max_rpm_registry
        self.fan_source = fan_source
        self.fan_presence_state_store = fan_presence_state_store
        self.log = logging.getLogger(__name__)

    def _confirmed_ids(self) -> set[str]:
        try:
            presence = self.fan_presence_state_store.load()
        except Exception:
            return set()
        confirmed = presence.get("confirmed")
        if not isinstance(confirmed, list):
            return set()
        current = {fan.fan_id for fan in self.fan_source()}
        return {fan_id for fan_id in confirmed if fan_id in current}

    def process_events(self) -> bool:
        handled = super().process_events()
        changed = False
        while True:
            try:
                update = self.bridge.fan_max_rpm_updates.get_nowait()
            except queue.Empty:
                break
            handled = True
            if update.fan_id not in self._confirmed_ids():
                self.log.warning("Ignoring RPM limit for unknown fan %s", update.fan_id)
                continue
            try:
                changed |= self.fan_max_rpm_registry.set(update.fan_id, update.max_rpm)
            except Exception:
                self.log.exception("Could not save max RPM for %s", update.fan_id)
        if changed:
            self.run_collection(names=("fans",), force=True)
        return handled
