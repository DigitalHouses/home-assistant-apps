from concurrent.futures import Future
from queue import Queue
from threading import Event
from types import SimpleNamespace

import pytest

from app.ups_setup_runtime import UpsSetupManager, REFRESH_SECONDS


class ManualWorker:
    def __init__(self):
        self.calls = []

    def submit(self, fn, *args):
        future = Future()
        self.calls.append((fn, args, future))
        return future


@pytest.fixture
def setup(tmp_path):
    clock = SimpleNamespace(now=0.0)
    bridge = SimpleNamespace(
        ups_setup_driver_updates=Queue(), ups_setup_requests=Queue(),
        ups_scan_requested=Event(), publish_ups_setup_state=lambda _: None,
    )
    manager = UpsSetupManager(bridge, config_path=tmp_path / "config",
                              state_dir=tmp_path, now=lambda: clock.now)
    manager.worker.shutdown()
    manager.worker = ManualWorker()
    return manager, bridge, clock


@pytest.mark.parametrize("failure", [False, True])
def test_periodic_inspection_does_not_reschedule_itself(setup, failure):
    manager, bridge, clock = setup
    manager.tick()
    assert len(manager.worker.calls) == 1
    future = manager.future
    manager.latest = {"ready": True, "actions": {"activate": True}}
    if failure:
        future.set_exception(RuntimeError("read failed"))
    else:
        future.set_result({"ready": True})
    clock.now = 1.0
    manager.tick()
    if failure:
        assert not manager.latest["ready"]
        assert not manager.latest["actions"]
    for elapsed in range(1, int(REFRESH_SECONDS)):
        clock.now = 1.0 + elapsed
        manager.tick()
        assert len(manager.worker.calls) == 1
    clock.now = 1.0 + REFRESH_SECONDS
    manager.tick()
    assert len(manager.worker.calls) == 2


def test_explicit_apply_refreshes_immediately_without_loop(setup):
    manager, bridge, clock = setup
    manager.tick()
    manager.future.set_result({"actions": {"server": True}})
    manager.tick()
    bridge.ups_setup_requests.put("server")
    manager.tick()
    assert manager.kind == "apply"
    manager.future.set_result(None)
    manager.tick()
    assert manager.kind == "inspect"
    manager.future.set_result({"ready": True})
    manager.tick()
    assert manager.future is None
    assert len(manager.worker.calls) == 3


def test_driver_selection_during_inspection_is_not_lost(setup):
    manager, bridge, clock = setup
    manager.tick()
    bridge.ups_setup_driver_updates.put("usbhid-ups")
    manager.tick()
    assert len(manager.worker.calls) == 1
    manager.future.set_result({"ready": False})
    manager.tick()
    assert len(manager.worker.calls) == 2
    manager.future.set_result({"ready": False})
    manager.tick()
    assert manager.future is None
