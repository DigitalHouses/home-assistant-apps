from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .collectors.cooling import FanSnapshot


@dataclass(frozen=True)
class FanPresenceSnapshot:
    candidate_count: int
    confirmed_count: int
    unconfirmed_count: int
    confirmed_fans: tuple[FanSnapshot, ...]


class FanPresenceTracker:
    """Confirm physical fans without treating every exported tach input as a fan."""

    def __init__(self, confirmed_ids: Iterable[str] = ()) -> None:
        self._confirmed = set(confirmed_ids)
        self._positive_streaks: dict[str, int] = {}

    @property
    def confirmed_ids(self) -> frozenset[str]:
        return frozenset(self._confirmed)

    def observe(self, fans: Iterable[FanSnapshot]) -> FanPresenceSnapshot:
        current = tuple(fans)
        present_ids = {fan.fan_id for fan in current}

        # Forget debounce for channels that disappeared from current hwmon.
        for fan_id in tuple(self._positive_streaks):
            if fan_id not in present_ids:
                self._positive_streaks.pop(fan_id, None)

        for fan in current:
            if fan.fan_id in self._confirmed:
                continue
            if fan.rpm is not None and fan.rpm > 0:
                streak = self._positive_streaks.get(fan.fan_id, 0) + 1
                if streak >= 2:
                    self._confirmed.add(fan.fan_id)
                    self._positive_streaks.pop(fan.fan_id, None)
                else:
                    self._positive_streaks[fan.fan_id] = streak
            else:
                self._positive_streaks.pop(fan.fan_id, None)

        confirmed_fans = tuple(
            fan for fan in current
            if fan.fan_id in self._confirmed
        )
        candidate_count = len(current)
        confirmed_count = len(confirmed_fans)
        return FanPresenceSnapshot(
            candidate_count=candidate_count,
            confirmed_count=confirmed_count,
            unconfirmed_count=candidate_count - confirmed_count,
            confirmed_fans=confirmed_fans,
        )
