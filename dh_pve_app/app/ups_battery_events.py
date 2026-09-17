from __future__ import annotations

from .state_store import StateStore, StateStoreError


DISCHARGE_THRESHOLDS = (90, 80, 70, 60, 50, 40, 30, 20, 10)
_SCHEMA_VERSION = 1
_CHARGER_STATUSES = {
    "charging",
    "discharging",
    "floating",
    "resting",
    "idle",
    "unknown",
}
_DIRECT_COMPLETED_STATUSES = {"floating", "resting"}


class UpsBatteryEventTracker:
    def __init__(self, state_store: StateStore) -> None:
        self.state_store = state_store
        self.session_active = False
        self.session_started_at: str | None = None
        self.last_observed_charge_percent: float | int | None = None
        self.emitted_thresholds: set[int] = set()

        self.charge_cycle_active = False
        self.charge_cycle_emitted = False
        self.charge_cycle_started_at: str | None = None
        self.last_charger_status: str | None = None
        self.last_cycle_charge_percent: float | int | None = None
        self.last_charging_charge_percent: float | int | None = None
        self.legacy_completion_samples = 0
        self._load()

    @staticmethod
    def _valid_charge(value: object) -> bool:
        return value is None or (
            not isinstance(value, bool) and isinstance(value, (int, float))
        )

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
        if not self._valid_charge(last_charge):
            raise StateStoreError("invalid UPS battery event state")
        if not isinstance(emitted, list) or any(
            isinstance(value, bool) or not isinstance(value, int) for value in emitted
        ):
            raise StateStoreError("invalid UPS battery event state")
        if any(value not in DISCHARGE_THRESHOLDS for value in emitted):
            raise StateStoreError("invalid UPS battery event state")

        charge_cycle_active = state.get("charge_cycle_active", False)
        charge_cycle_emitted = state.get("charge_cycle_emitted", False)
        charge_cycle_started_at = state.get("charge_cycle_started_at")
        last_charger_status = state.get("last_charger_status")
        last_cycle_charge = state.get("last_cycle_charge_percent")
        last_charging_charge = state.get("last_charging_charge_percent")
        legacy_completion_samples = state.get("legacy_completion_samples", 0)

        if not isinstance(charge_cycle_active, bool) or not isinstance(
            charge_cycle_emitted, bool
        ):
            raise StateStoreError("invalid UPS battery event state")
        if charge_cycle_started_at is not None and not isinstance(
            charge_cycle_started_at, str
        ):
            raise StateStoreError("invalid UPS battery event state")
        if last_charger_status is not None and last_charger_status not in _CHARGER_STATUSES:
            raise StateStoreError("invalid UPS battery event state")
        if not self._valid_charge(last_cycle_charge) or not self._valid_charge(
            last_charging_charge
        ):
            raise StateStoreError("invalid UPS battery event state")
        if (
            isinstance(legacy_completion_samples, bool)
            or not isinstance(legacy_completion_samples, int)
            or legacy_completion_samples < 0
        ):
            raise StateStoreError("invalid UPS battery event state")

        self.session_active = session_active
        self.session_started_at = session_started_at
        self.last_observed_charge_percent = last_charge
        self.emitted_thresholds = set(emitted)

        self.charge_cycle_active = charge_cycle_active
        self.charge_cycle_emitted = charge_cycle_emitted
        self.charge_cycle_started_at = charge_cycle_started_at
        self.last_charger_status = last_charger_status
        self.last_cycle_charge_percent = last_cycle_charge
        self.last_charging_charge_percent = last_charging_charge
        self.legacy_completion_samples = legacy_completion_samples

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
                "charge_cycle_active": self.charge_cycle_active,
                "charge_cycle_emitted": self.charge_cycle_emitted,
                "charge_cycle_started_at": self.charge_cycle_started_at,
                "last_charger_status": self.last_charger_status,
                "last_cycle_charge_percent": self.last_cycle_charge_percent,
                "last_charging_charge_percent": self.last_charging_charge_percent,
                "legacy_completion_samples": self.legacy_completion_samples,
            }
        )

    def _reset_session(self) -> None:
        self.session_active = False
        self.session_started_at = None
        self.last_observed_charge_percent = None
        self.emitted_thresholds.clear()

    def _start_charge_cycle(
        self,
        *,
        charge_percent: float | int | None,
        observed_at: str,
    ) -> None:
        self.charge_cycle_active = True
        self.charge_cycle_emitted = False
        self.charge_cycle_started_at = observed_at
        self.last_charging_charge_percent = charge_percent
        self.legacy_completion_samples = 0

    def _abort_charge_cycle(self) -> None:
        self.charge_cycle_active = False
        self.charge_cycle_emitted = False
        self.charge_cycle_started_at = None
        self.last_charging_charge_percent = None
        self.legacy_completion_samples = 0

    def observe_discharge(
        self,
        *,
        on_battery: bool,
        charge_percent: float | None,
        observed_at: str,
    ) -> tuple[tuple[str, dict[str, object]], ...]:
        if not self._valid_charge(charge_percent):
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

    def observe_charge_cycle(
        self,
        *,
        charger_status: str,
        charge_percent: float | None,
        line_power: bool,
        raw_status_tokens: tuple[str, ...],
        observed_at: str,
    ) -> tuple[tuple[str, dict[str, object]], ...]:
        if charger_status not in _CHARGER_STATUSES:
            raise ValueError(f"unsupported charger status: {charger_status}")
        if not self._valid_charge(charge_percent):
            raise TypeError("charge_percent must be numeric or None")

        raw_tokens = {token.upper() for token in raw_status_tokens}
        previous_status = self.last_charger_status
        previous_charge = self.last_cycle_charge_percent
        first_observation = previous_status is None

        if charger_status == "charging":
            if (
                not self.charge_cycle_active
                or self.charge_cycle_emitted
                or previous_status == "discharging"
            ):
                self._start_charge_cycle(
                    charge_percent=charge_percent,
                    observed_at=observed_at,
                )
            elif charge_percent is not None:
                self.last_charging_charge_percent = charge_percent

            self.last_charger_status = charger_status
            self.last_cycle_charge_percent = charge_percent
            self.legacy_completion_samples = 0
            self._persist()
            return ()

        if first_observation:
            self.last_charger_status = charger_status
            self.last_cycle_charge_percent = charge_percent
            self.legacy_completion_samples = 0
            self._persist()
            return ()

        if (
            charger_status in _DIRECT_COMPLETED_STATUSES
            and self.charge_cycle_active
            and not self.charge_cycle_emitted
        ):
            self.charge_cycle_emitted = True
            self.legacy_completion_samples = 0
            self.last_charger_status = charger_status
            self.last_cycle_charge_percent = charge_percent
            self._persist()

            payload: dict[str, object] = {
                "schema_version": 2,
                "event_type": "battery_fully_charged",
                "observed_at": observed_at,
                "previous_charge_percent": previous_charge,
                "current_charge_percent": charge_percent,
                "previous_charger_status": previous_status,
                "current_charger_status": charger_status,
                "detection_source": "charger_status",
            }
            cycle_key = self.charge_cycle_started_at or observed_at
            return ((f"battery_fully_charged:{cycle_key}", payload),)

        legacy_idle = (
            charger_status == "idle"
            and line_power
            and "CHRG" not in raw_tokens
            and "DISCHRG" not in raw_tokens
        )
        if (
            legacy_idle
            and self.charge_cycle_active
            and not self.charge_cycle_emitted
        ):
            self.legacy_completion_samples += 1
            self.last_charger_status = charger_status
            self.last_cycle_charge_percent = charge_percent

            if self.legacy_completion_samples >= 2:
                self.charge_cycle_emitted = True
                self._persist()
                payload = {
                    "schema_version": 2,
                    "event_type": "battery_fully_charged",
                    "observed_at": observed_at,
                    "previous_charge_percent": self.last_charging_charge_percent,
                    "current_charge_percent": charge_percent,
                    "previous_charger_status": "charging",
                    "current_charger_status": "idle",
                    "detection_source": "legacy_status_fallback",
                }
                cycle_key = self.charge_cycle_started_at or observed_at
                return ((f"battery_fully_charged:{cycle_key}", payload),)

            self._persist()
            return ()

        if charger_status == "discharging":
            self._abort_charge_cycle()
        else:
            self.legacy_completion_samples = 0

        self.last_charger_status = charger_status
        self.last_cycle_charge_percent = charge_percent
        self._persist()
        return ()
