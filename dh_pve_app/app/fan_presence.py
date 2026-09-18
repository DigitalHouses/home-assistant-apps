from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Protocol

from .collectors.cooling import FanSnapshot


class FanPresenceStateStore(Protocol):
    def load(self) -> dict[str, object]: ...
    def save(self, data: Mapping[str, object]) -> None: ...


@dataclass(frozen=True)
class FanPresenceSnapshot:
    candidate_count: int
    confirmed_count: int
    unconfirmed_count: int
    confirmed_fans: tuple[FanSnapshot, ...]


class FanPresenceTracker:
    """Confirm physical fans without treating every exported tach input as a fan."""

    def __init__(
        self,
        confirmed_ids: Iterable[str] = (),
        *,
        state_store: FanPresenceStateStore | None = None,
    ) -> None:
        self._state_store = state_store
        persisted: set[str] = set()
        if state_store is not None:
            raw = state_store.load()
            saved = raw.get("confirmed")
            if isinstance(saved, list):
                persisted = {
                    value
                    for value in saved
                    if isinstance(value, str) and value
                }
        self._confirmed = set(confirmed_ids) | persisted
        self._positive_streaks: dict[str, int] = {}

    @property
    def confirmed_ids(self) -> frozenset[str]:
        return frozenset(self._confirmed)

    def _persist(self) -> None:
        if self._state_store is None:
            return
        self._state_store.save(
            {
                "schema_version": 1,
                "confirmed": sorted(self._confirmed),
            }
        )

    def observe(self, fans: Iterable[FanSnapshot]) -> FanPresenceSnapshot:
        current = tuple(fans)
        present_ids = {fan.fan_id for fan in current}

        # Debounce is session-local. A channel that disappears must earn two
        # new consecutive positive observations if it was not confirmed yet.
        for fan_id in tuple(self._positive_streaks):
            if fan_id not in present_ids:
                self._positive_streaks.pop(fan_id, None)

        changed = False
        for fan in current:
            if fan.fan_id in self._confirmed:
                continue
            if fan.rpm is not None and fan.rpm > 0:
                streak = self._positive_streaks.get(fan.fan_id, 0) + 1
                if streak >= 2:
                    self._confirmed.add(fan.fan_id)
                    self._positive_streaks.pop(fan.fan_id, None)
                    changed = True
                else:
                    self._positive_streaks[fan.fan_id] = streak
            else:
                self._positive_streaks.pop(fan.fan_id, None)

        if changed:
            self._persist()

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
