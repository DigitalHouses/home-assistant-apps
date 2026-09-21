from __future__ import annotations

import threading
from collections.abc import Callable

from .collectors.cooling import FanSnapshot
from .fan_calibration import FanCalibrationManager
from .runtime_problems import ProblemAwareRuntime
from .state_store import StateStore


class FanAwareRuntime(ProblemAwareRuntime):
    """Problem-aware PVE runtime with non-blocking fan calibration orchestration."""

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
        self._fan_completed = threading.Event()
        self._fan_worker: threading.Thread | None = None
        self._fan_last_result: dict[str, str] = {}
        self._fan_result_lock = threading.Lock()
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
            fan for fan in self.fan_source() if fan.fan_id in confirmed
        )

    def recover_fan_control(self) -> dict[str, str]:
        return self.fan_calibration_manager.recover_pending(self.fan_source())

    def cancel_fan_calibration(self) -> None:
        self._fan_cancel_requested.set()

    def wait_fan_calibration(self) -> None:
        worker = self._fan_worker
        if worker is not None and worker.is_alive():
            worker.join()

    def _targets(self, *, automatic: bool) -> tuple[FanSnapshot, ...]:
        fans = self._confirmed_fans()
        if not automatic:
            return tuple(
                fan
                for fan in fans
                if self.fan_calibration_manager.adapter_for(fan) is not None
            )

        result = []
        for fan in fans:
            adapter = self.fan_calibration_manager.adapter_for(fan)
            if adapter is None:
                continue
            if self.fan_calibration_manager.registry.needs_automatic_calibration(
                fan, adapter
            ):
                result.append(fan)
        return tuple(result)

    def _start_fan_calibration(self, *, automatic: bool) -> bool:
        worker = self._fan_worker
        if worker is not None and worker.is_alive():
            return False

        targets = self._targets(automatic=automatic)
        if not targets:
            return False

        self._fan_cancel_requested.clear()
        self._fan_completed.clear()

        def work() -> None:
            result = self.fan_calibration_manager.calibrate(
                targets,
                automatic=automatic,
                cancelled=self._fan_cancel_requested.is_set,
            )
            with self._fan_result_lock:
                self._fan_last_result = dict(result)
            self._fan_completed.set()

        self._fan_worker = threading.Thread(
            target=work,
            name="dh-pve-fan-calibration",
            daemon=False,
        )
        self._fan_worker.start()
        return True

    def _finish_fan_calibration(self) -> bool:
        if not self._fan_completed.is_set():
            return False
        worker = self._fan_worker
        if worker is not None:
            worker.join()
        self._fan_completed.clear()
        with self._fan_result_lock:
            result = dict(self._fan_last_result)
            self._fan_last_result = {}
        if result and result.get("_status") != "busy":
            self.run_collection(names=("fans",), force=True)
        return True

    def process_events(self) -> bool:
        handled = super().process_events()
        if self._finish_fan_calibration():
            handled = True

        request = getattr(self.bridge, "fan_calibration_requested", None)
        if request is not None and request.is_set():
            request.clear()
            self._start_fan_calibration(automatic=False)
            handled = True
        return handled

    def tick(self, now_monotonic: float) -> bool:
        published = super().tick(now_monotonic)
        if now_monotonic >= self._next_auto_calibration_check:
            self._next_auto_calibration_check = now_monotonic + 10.0
            self._start_fan_calibration(automatic=True)
        return published
