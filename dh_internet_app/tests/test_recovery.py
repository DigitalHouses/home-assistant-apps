from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from config import RecoveryTarget
from recovery import RecoveryExecutor, RecoveryStopped, choose_targets


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def call_service(self, domain: str, service: str, entity_id: str) -> None:
        self.calls.append((domain, service, entity_id))


class RecoveryPolicyTests(unittest.TestCase):
    def test_smart_reboots_ont_when_router_is_alive(self) -> None:
        selected = choose_targets(
            mode="smart", internet_up=False, router_up=True
        )
        self.assertEqual(selected.targets, ("ont",))

    def test_smart_reboots_router_when_router_is_down(self) -> None:
        selected = choose_targets(
            mode="smart", internet_up=False, router_up=False
        )
        self.assertEqual(selected.targets, ("router",))

    def test_both_always_selects_ont_then_router(self) -> None:
        selected = choose_targets(
            mode="both", internet_up=False, router_up=False
        )
        self.assertEqual(selected.targets, ("ont", "router"))

    def test_no_recovery_when_internet_is_available(self) -> None:
        selected = choose_targets(
            mode="both", internet_up=True, router_up=False
        )
        self.assertEqual(selected.targets, ())

    def test_switch_restore_is_attempted_when_turn_off_errors(self) -> None:
        class FailingApi(FakeApi):
            def call_service(
                self, domain: str, service: str, entity_id: str
            ) -> None:
                super().call_service(domain, service, entity_id)
                if service == "turn_off":
                    raise RuntimeError("response lost")

        api = FailingApi()
        executor = RecoveryExecutor(api, threading.Event(), sleep=lambda _: None)
        target = RecoveryTarget(
            action="switch",
            entity_id="switch.ont",
            power_off_seconds=10,
        )

        with self.assertRaises(RuntimeError):
            executor.execute(target)

        self.assertEqual(
            api.calls,
            [
                ("switch", "turn_off", "switch.ont"),
                ("switch", "turn_on", "switch.ont"),
            ],
        )

    def test_switch_is_restored_when_stop_arrives(self) -> None:
        api = FakeApi()
        stop = threading.Event()

        def sleep(_seconds: float) -> None:
            stop.set()

        executor = RecoveryExecutor(api, stop, sleep=sleep)
        target = RecoveryTarget(
            action="switch",
            entity_id="switch.ont",
            power_off_seconds=10,
        )

        with self.assertRaises(RecoveryStopped):
            executor.execute(target)

        self.assertEqual(
            api.calls,
            [
                ("switch", "turn_off", "switch.ont"),
                ("switch", "turn_on", "switch.ont"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
