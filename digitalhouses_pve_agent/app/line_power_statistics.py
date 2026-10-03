from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from .state_store import StateStore, StateStoreError
from .ups_nut import UpsSnapshot


_SCHEMA_VERSION = 1
_MONTH_LABELS_RU = (
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)


class LinePowerState(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LinePowerStatisticsSnapshot:
    month_key: str
    month_label_ru: str
    tracking_since: str
    partial_month: bool
    state: LinePowerState
    state_since: str
    online_seconds: int
    offline_seconds: int
    unknown_seconds: int
    outages_month: int
    availability_percent: float | None
    current_outage_started: str | None
    last_failure: str | None
    last_restore: str | None
    last_outage_duration_seconds: int | None
    estimated_restore: bool
    outages: list[dict[str, object]]
    history_since: str
    history_partial_month: bool
    omitted_count: int

    def as_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["state"] = self.state.value
        return payload


def line_power_state_from_snapshot(
    snapshot: UpsSnapshot | None,
    *,
    nut_available: bool,
) -> LinePowerState:
    if not nut_available or snapshot is None:
        return LinePowerState.UNKNOWN
    tokens = set(snapshot.status_tokens)
    has_online = "OL" in tokens
    has_on_battery = "OB" in tokens
    if has_online and not has_on_battery:
        return LinePowerState.ONLINE
    if has_on_battery and not has_online:
        return LinePowerState.OFFLINE
    return LinePowerState.UNKNOWN


class LinePowerStatisticsTracker:
    def __init__(
        self,
        store: StateStore,
        *,
        now_local: Callable[[], datetime],
    ) -> None:
        self.store = store
        self.now_local = now_local
        raw = store.load()
        self._data: dict[str, Any] | None = None
        self._first_observation_after_load = False
        if raw:
            self._data = self._validate_loaded(raw)
            self._first_observation_after_load = True
            # v1 statistics already exist; retain their counters without
            # claiming unavailable per-incident history was reconstructed.
            if "outage_history" not in self._data:
                self._data["outage_history"] = []
                self._data["outage_history_since"] = self._iso(self._now())
                self._data["outage_uncertain"] = bool(
                    self._data.get("current_outage_started")
                )
                self._persist()

    def _now(self) -> datetime:
        value = self.now_local()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("line-power statistics require timezone-aware local time")
        return value

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.isoformat()

    @staticmethod
    def _parse_datetime(value: object) -> datetime:
        if not isinstance(value, str):
            raise StateStoreError("invalid line-power statistics timestamp")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise StateStoreError("invalid line-power statistics timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise StateStoreError("invalid line-power statistics timestamp")
        return parsed

    @staticmethod
    def _month_key(value: datetime) -> str:
        return f"{value.year:04d}-{value.month:02d}"

    @staticmethod
    def _month_start(value: datetime) -> datetime:
        return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    @staticmethod
    def _next_month_start(value: datetime) -> datetime:
        if value.month == 12:
            return value.replace(
                year=value.year + 1,
                month=1,
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        return value.replace(
            month=value.month + 1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    @staticmethod
    def _seconds(start: datetime, end: datetime) -> int:
        return max(0, int((end - start).total_seconds()))

    @staticmethod
    def _validate_loaded(raw: Mapping[str, Any]) -> dict[str, Any]:
        if raw.get("schema_version") != _SCHEMA_VERSION:
            raise StateStoreError("unsupported line-power statistics schema")
        required = {
            "month_key",
            "tracking_since",
            "partial_month",
            "last_known_state",
            "state_since",
            "online_accumulated_seconds",
            "offline_accumulated_seconds",
            "unknown_accumulated_seconds",
            "outages_month",
            "current_outage_started",
            "last_failure",
            "last_restore",
            "last_outage_duration_seconds",
            "estimated_restore",
        }
        if not required.issubset(raw):
            raise StateStoreError("invalid persisted line-power statistics")
        try:
            LinePowerState(str(raw["last_known_state"]))
        except ValueError as exc:
            raise StateStoreError("invalid persisted line-power state") from exc
        if "outage_history" in raw:
            history = raw["outage_history"]
            if not isinstance(history, list):
                raise StateStoreError("invalid persisted line-power outage history")
            for item in history:
                if not isinstance(item, dict):
                    raise StateStoreError("invalid persisted line-power outage row")
                LinePowerStatisticsTracker._parse_datetime(item.get("from"))
                LinePowerStatisticsTracker._parse_datetime(item.get("to"))
                if (type(item.get("duration_seconds")) is not int
                        or item["duration_seconds"] < 0
                        or not isinstance(item.get("estimated"), bool)):
                    raise StateStoreError("invalid persisted line-power outage facts")
            LinePowerStatisticsTracker._parse_datetime(raw.get("outage_history_since"))
            if not isinstance(raw.get("outage_uncertain"), bool):
                raise StateStoreError("invalid persisted line-power outage uncertainty")
        return dict(raw)

    def _persist(self) -> None:
        if self._data is not None:
            self.store.save(self._data)

    def _initialize(self, state: LinePowerState, now: datetime) -> None:
        month_start = self._month_start(now)
        iso_now = self._iso(now)
        self._data = {
            "schema_version": _SCHEMA_VERSION,
            "month_key": self._month_key(now),
            "tracking_since": iso_now,
            "partial_month": now != month_start,
            "last_known_state": state.value,
            "state_since": iso_now,
            "online_accumulated_seconds": 0,
            "offline_accumulated_seconds": 0,
            "unknown_accumulated_seconds": 0,
            "outages_month": 1 if state is LinePowerState.OFFLINE else 0,
            "current_outage_started": iso_now if state is LinePowerState.OFFLINE else None,
            "last_failure": iso_now if state is LinePowerState.OFFLINE else None,
            "last_restore": None,
            "last_outage_duration_seconds": None,
            "estimated_restore": False,
            "outage_history": [],
            "outage_history_since": iso_now,
            "outage_uncertain": state is LinePowerState.OFFLINE,
        }
        self._persist()

    def _accumulator_key(self, state: LinePowerState) -> str:
        return f"{state.value}_accumulated_seconds"

    def _accumulate_until(self, end: datetime) -> None:
        assert self._data is not None
        state = LinePowerState(str(self._data["last_known_state"]))
        start = self._parse_datetime(self._data["state_since"])
        key = self._accumulator_key(state)
        self._data[key] = int(self._data[key]) + self._seconds(start, end)
        self._data["state_since"] = self._iso(end)

    def _roll_months(self, now: datetime) -> bool:
        if self._data is None:
            return False
        rolled = False
        while str(self._data["month_key"]) != self._month_key(now):
            state_since = self._parse_datetime(self._data["state_since"])
            boundary = self._next_month_start(state_since)
            if boundary > now:
                break
            self._accumulate_until(boundary)
            self._data["month_key"] = self._month_key(boundary)
            self._data["partial_month"] = False
            self._data["online_accumulated_seconds"] = 0
            self._data["offline_accumulated_seconds"] = 0
            self._data["unknown_accumulated_seconds"] = 0
            self._data["outages_month"] = 0
            self._data["outage_history"] = []
            self._data["outage_history_since"] = self._iso(boundary)
            self._data["state_since"] = self._iso(boundary)
            rolled = True
        if rolled:
            self._persist()
        return rolled

    def observe(self, state: LinePowerState) -> bool:
        if not isinstance(state, LinePowerState):
            state = LinePowerState(str(state))
        now = self._now()
        if self._data is None:
            self._initialize(state, now)
            self._first_observation_after_load = False
            return True

        rolled = self._roll_months(now)
        old_state = LinePowerState(str(self._data["last_known_state"]))
        if old_state is state:
            self._first_observation_after_load = False
            return rolled

        self._accumulate_until(now)
        iso_now = self._iso(now)

        if state is LinePowerState.OFFLINE:
            if self._data.get("current_outage_started") is None:
                self._data["outages_month"] = int(self._data["outages_month"]) + 1
                self._data["current_outage_started"] = iso_now
                self._data["last_failure"] = iso_now
                self._data["outage_uncertain"] = old_state is LinePowerState.UNKNOWN
            self._data["estimated_restore"] = False
        elif state is LinePowerState.UNKNOWN:
            if self._data.get("current_outage_started") is not None:
                self._data["outage_uncertain"] = True
        elif state is LinePowerState.ONLINE:
            outage_started = self._data.get("current_outage_started")
            if isinstance(outage_started, str):
                started = self._parse_datetime(outage_started)
                self._data["last_outage_duration_seconds"] = self._seconds(started, now)
                self._data["last_restore"] = iso_now
                estimated = bool(
                    self._first_observation_after_load
                    or old_state is LinePowerState.UNKNOWN
                    or self._data.get("outage_uncertain", False)
                )
                self._data["estimated_restore"] = estimated
                self._data["outage_history"].append({
                    "from": outage_started,
                    "to": iso_now,
                    "duration_seconds": self._seconds(started, now),
                    "estimated": estimated,
                })
                self._data["current_outage_started"] = None
                self._data["outage_uncertain"] = False

        self._data["last_known_state"] = state.value
        self._data["state_since"] = iso_now
        self._persist()
        self._first_observation_after_load = False
        return True

    def snapshot(self) -> LinePowerStatisticsSnapshot:
        now = self._now()
        if self._data is None:
            self._initialize(LinePowerState.UNKNOWN, now)
        assert self._data is not None
        self._roll_months(now)

        online = int(self._data["online_accumulated_seconds"])
        offline = int(self._data["offline_accumulated_seconds"])
        unknown = int(self._data["unknown_accumulated_seconds"])
        state = LinePowerState(str(self._data["last_known_state"]))
        state_since = self._parse_datetime(self._data["state_since"])
        elapsed = self._seconds(state_since, now)
        if state is LinePowerState.ONLINE:
            online += elapsed
        elif state is LinePowerState.OFFLINE:
            offline += elapsed
        else:
            unknown += elapsed

        known = online + offline
        availability = round((online / known) * 100.0, 2) if known > 0 else None
        month = int(str(self._data["month_key"])[5:7])
        history_since = self._parse_datetime(self._data["outage_history_since"])
        history = [dict(row) for row in self._data["outage_history"]]
        started = self._data.get("current_outage_started")
        if isinstance(started, str):
            history.append({
                "from": started,
                "to": None,
                "duration_seconds": self._seconds(self._parse_datetime(started), now),
                "estimated": bool(self._data.get("outage_uncertain", False))
                or state is LinePowerState.UNKNOWN,
            })
        # MQTT attributes stay bounded while every incident remains stored
        # locally for the current month and the existing counter stays complete.
        omitted = max(0, len(history) - 10)

        return LinePowerStatisticsSnapshot(
            month_key=str(self._data["month_key"]),
            month_label_ru=_MONTH_LABELS_RU[month - 1],
            tracking_since=str(self._data["tracking_since"]),
            partial_month=bool(self._data["partial_month"]),
            state=state,
            state_since=str(self._data["state_since"]),
            online_seconds=online,
            offline_seconds=offline,
            unknown_seconds=unknown,
            outages_month=int(self._data["outages_month"]),
            availability_percent=availability,
            current_outage_started=(
                str(self._data["current_outage_started"])
                if self._data.get("current_outage_started") is not None
                else None
            ),
            last_failure=(
                str(self._data["last_failure"])
                if self._data.get("last_failure") is not None
                else None
            ),
            last_restore=(
                str(self._data["last_restore"])
                if self._data.get("last_restore") is not None
                else None
            ),
            last_outage_duration_seconds=(
                int(self._data["last_outage_duration_seconds"])
                if self._data.get("last_outage_duration_seconds") is not None
                else None
            ),
            estimated_restore=bool(self._data["estimated_restore"]),
            outages=history[-10:],
            history_since=self._iso(history_since),
            history_partial_month=history_since > self._month_start(now),
            omitted_count=omitted,
        )
