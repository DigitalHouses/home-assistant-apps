from __future__ import annotations

import threading
from collections.abc import Callable

from .collectors.cooling import FanSnapshot
from .fan_calibration import FanCalibrationManager
from .runtime_problems import ProblemAwareRuntime
from .state_store import StateStore


class FanAwareRuntime(ProblemAwareRuntime):
    """Problem-aware PVE runtime with isolated fan calibration orchestration."""

    def __init__(
        self,
        *args,
        fan_calibration_manager: FanCalibrationManager,
        fan_source: Callable[[], tuple[FanSnapshot, ...]],
        fan_presence_state_store: StateStore,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.fan_calibration_manager = fan_calibration_manager
        self.fan_source = fan_source
        self.fan_presence_state_store = fan_presence_state_store
        self._fan_cancel_requested = threading.Event()
        self._next_auto_calibration_check = 0.0

    def _confirmed_fans(self) -> tuple[FanSnapshot, ...]:
        try:
            presence = self.fan_presence_state_store.load()
        except Exception:
            return ()
        raw_ids = presence.get("confirmed")
        if not isinstance(raw_ids, list):
            return ()
        confirmed = {
            fan_id
            for fan_id in raw_ids
            if isinstance(fan_id, str) and fan_id
        }
        return tuple(
            fan
            for fan in self.fan_source()
            if fan.fan_id in confirmed
        )

    def recover_fan_control(self) -> dict[str, str]:
        return self.fan_calibration_manager.recover_pending(self.fan_source())

    def cancel_fan_calibration(self) -> None:
        self._fan_cancel_requested.set()

    def _run_fan_calibration(self, *, automatic: bool) -> dict[str, str]:
        self._fan_cancel_requested.clear()
        result = self.fan_calibration_manager.calibrate(
            self._confirmed_fans(),
            automatic=automatic,
            cancelled=self._fan_cancel_requested.is_set,
        )
        # Drop duplicate HA presses received while a synchronous calibration
        # was already in progress.
        request = getattr(self.bridge, "fan_calibration_requested", None)
        if request is not None:
            request.clear()

        if result and result.get("_status") != "busy":
            self.run_collection(names=("fans",), force=True)
        return result

    def process_events(self) -> bool:
        handled = super().process_events()
        request = getattr(self.bridge, "fan_calibration_requested", None)
        if request is not None and request.is_set():
            request.clear()
            self._run_fan_calibration(automatic=False)
            handled = True
        return handled

    def tick(self, now_monotonic: float) -> bool:
        published = super().tick(now_monotonic)
        if now_monotonic >= self._next_auto_calibration_check:
            self._next_auto_calibration_check = now_monotonic + 10.0
            result = self._run_fan_calibration(automatic=True)
            if result:
                published = True
        return published
