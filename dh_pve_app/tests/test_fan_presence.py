from __future__ import annotations

from app.collectors.cooling import FanSnapshot
from app.fan_presence import FanPresenceTracker


class MemoryStore:
    def __init__(self) -> None:
        self.state: dict[str, object] = {}
        self.save_calls = 0

    def load(self) -> dict[str, object]:
        return dict(self.state)

    def save(self, data) -> None:
        self.save_calls += 1
        self.state = dict(data)


def _fan(rpm: int | None) -> FanSnapshot:
    return FanSnapshot(
        fan_id="it8613_it87_2608_fan2",
        chip="it8613",
        chip_display_name="it8613",
        source_device="it87.2608",
        fan_name="fan2",
        fan_index=2,
        label="Fan 2",
        display_name="Fan 2 RPM - it8613",
        rpm=rpm,
        available=rpm is not None,
        input_path="/sys/class/hwmon/hwmon3/fan2_input",
    )


def test_confirmation_is_persisted_once_and_restored_after_restart():
    store = MemoryStore()
    tracker = FanPresenceTracker(state_store=store)

    assert tracker.observe((_fan(3792),)).confirmed_count == 0
    confirmed = tracker.observe((_fan(3813),))
    assert confirmed.confirmed_count == 1
    assert store.save_calls == 1

    tracker.observe((_fan(3879),))
    assert store.save_calls == 1

    restarted = FanPresenceTracker(state_store=store)
    restored = restarted.observe((_fan(0),))

    assert restored.confirmed_count == 1
    assert restored.confirmed_fans[0].rpm == 0


def test_positive_debounce_is_session_only_and_is_not_persisted():
    store = MemoryStore()
    tracker = FanPresenceTracker(state_store=store)

    assert tracker.observe((_fan(3792),)).confirmed_count == 0
    assert store.save_calls == 0

    restarted = FanPresenceTracker(state_store=store)
    assert restarted.observe((_fan(3813),)).confirmed_count == 0
    assert store.save_calls == 0

    assert restarted.observe((_fan(3879),)).confirmed_count == 1
    assert store.save_calls == 1


def test_persisted_confirmation_does_not_synthesize_an_absent_hwmon_channel():
    store = MemoryStore()
    tracker = FanPresenceTracker(state_store=store)
    tracker.observe((_fan(3792),))
    tracker.observe((_fan(3813),))

    restarted = FanPresenceTracker(state_store=store)
    absent = restarted.observe(())

    assert absent.candidate_count == 0
    assert absent.confirmed_count == 0
    assert absent.confirmed_fans == ()

    returned = restarted.observe((_fan(0),))
    assert returned.candidate_count == 1
    assert returned.confirmed_count == 1
    assert returned.confirmed_fans[0].rpm == 0
