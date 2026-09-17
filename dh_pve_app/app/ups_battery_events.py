from __future__ import annotations

from .state_store import StateStore, StateStoreError


DISCHARGE_THRESHOLDS = (90, 80, 70, 60, 50, 40, 30, 20, 10)
_SCHEMA_VERSION = 1


class UpsBatteryEventTracker:
    def __init__(self, state_store: StateStore) -> None:
        self.state_store = state_store
        self.session_active = False
        self.session_started_at: str | None = None
        self.last_observed_charge_percent: float | int | None = None
        self.emitted_thresholds: set[int] = set()
        self._load()

    def _load(self) -> None:
        state = self.state_store.load()
        if not state:
            return
        if state.get("schema_version") != _SCHEMA_VERSION:
            raise StateStoreError("unsupported UPS battery event state schema")

        session_active = state.get("session_active")
        session_started_at = state.get("session_started_at")
        last_charge = state.get("last_observed_charge_percent")
        emitted = state.get("emitted_thresholds")

        if not isinstance(session_active, bool):
            raise StateStoreError("invalid UPS battery event state")
        if session_started_at is not None and not isinstance(session_started_at, str):
            raise StateStoreError("invalid UPS battery event state")
        if last_charge is not None and (
            isinstance(last_charge, bool) or not isinstance(last_charge, (int, float))
        ):
            raise StateStoreError("invalid UPS battery event state")
        if not isinstance(emitted, list) or any(
            isinstance(value, bool) or not isinstance(value, int) for value in emitted
        ):
            raise StateStoreError("invalid UPS battery event state")
        if any(value not in DISCHARGE_THRESHOLDS for value in emitted):
            raise StateStoreError("invalid UPS battery event state")

        self.session_active = session_active
        self.session_started_at = session_started_at
        self.last_observed_charge_percent = last_charge
        self.emitted_thresholds = set(emitted)

    def _persist(self) -> None:
        self.state_store.save(
            {
                "schema_version": _SCHEMA_VERSION,
                "session_active": self.session_active,
                "session_started_at": self.session_started_at,
                "last_observed_charge_percent": self.last_observed_charge_percent,
                "emitted_thresholds": [
                    threshold
                    for threshold in DISCHARGE_THRESHOLDS
                    if threshold in self.emitted_thresholds
                ],
            }
        )

    def _reset_session(self) -> None:
        self.session_active = False
        self.session_started_at = None
        self.last_observed_charge_percent = None
        self.emitted_thresholds.clear()

    def observe_discharge(
        self,
        *,
        on_battery: bool,
        charge_percent: float | None,
        observed_at: str,
    ) -> tuple[tuple[str, dict[str, object]], ...]:
        if charge_percent is not None and (
            isinstance(charge_percent, bool) or not isinstance(charge_percent, (int, float))
        ):
            raise TypeError("charge_percent must be numeric or None")

        if not on_battery:
            if (
                self.session_active
                or self.session_started_at is not None
                or self.last_observed_charge_percent is not None
                or self.emitted_thresholds
            ):
                self._reset_session()
                self._persist()
            return ()

        if not self.session_active:
            self.session_active = True
            self.session_started_at = observed_at
            self.last_observed_charge_percent = charge_percent
            self.emitted_thresholds.clear()
            self._persist()
            return ()

        previous = self.last_observed_charge_percent
        if charge_percent is None:
            return ()

        if previous is None:
            self.last_observed_charge_percent = charge_percent
            self._persist()
            return ()

        self.last_observed_charge_percent = charge_percent

        crossed = [
            threshold
            for threshold in DISCHARGE_THRESHOLDS
            if threshold not in self.emitted_thresholds
            and previous > threshold >= charge_percent
        ]

        if crossed:
            self.emitted_thresholds.update(crossed)

        self._persist()

        if not crossed:
            return ()

        payload: dict[str, object] = {
            "schema_version": 2,
            "event_type": "battery_discharge_level_crossed",
            "observed_at": observed_at,
            "previous_charge_percent": previous,
            "current_charge_percent": charge_percent,
            "crossed_thresholds": crossed,
        }
        session_key = self.session_started_at or "unknown"
        key = (
            f"battery_discharge:{session_key}:"
            + ",".join(str(threshold) for threshold in crossed)
        )
        return ((key, payload),)
