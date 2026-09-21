from __future__ import annotations

import logging
import statistics
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from typing import Protocol

from .collectors.cooling import FanSnapshot
from .state_store import StateStore

CALIBRATION_SAMPLE_INTERVAL_SECONDS = 1.0
CALIBRATION_MAX_SAMPLES = 15
CALIBRATION_MIN_SPINUP_SAMPLES = 3
CALIBRATION_PLATEAU_SAMPLES = 3
CALIBRATION_PLATEAU_SPREAD = 0.03
CALIBRATION_MIN_ACCELERATION = 0.01
OBSERVED_MAX_TOLERANCE = 0.03
OBSERVED_MAX_CONFIRMATIONS = 3


class FanCalibrationAdapter(Protocol):
    profile_name: str

    def supports(self, fan: FanSnapshot) -> bool: ...
    def hardware_identity(self, fan: FanSnapshot) -> str: ...
    def capture(self, fan: FanSnapshot) -> Mapping[str, str]: ...
    def enter_max(self, fan: FanSnapshot) -> None: ...
    def read_rpm(self, fan: FanSnapshot) -> int | None: ...
    def restore(self, fan: FanSnapshot, original: Mapping[str, str]) -> None: ...
    def verify_restored(
        self, fan: FanSnapshot, original: Mapping[str, str]
    ) -> bool: ...
    def original_is_max(self, original: Mapping[str, str]) -> bool: ...


class FanCalibrationRegistry:
    def __init__(self, state_store: StateStore) -> None:
        self.state_store = state_store
        self._lock = threading.RLock()
        self._observed_high: dict[str, list[int]] = {}

    def _load(self) -> dict[str, object]:
        try:
            raw = self.state_store.load()
        except Exception:
            raw = {}
        fans = raw.get("fans")
        if not isinstance(fans, dict):
            fans = {}
        return {"schema_version": 1, "fans": dict(fans)}

    def _save(self, data: Mapping[str, object]) -> None:
        self.state_store.save(data)

    def _raw_record(self, fan_id: str) -> dict[str, object]:
        data = self._load()
        raw = data["fans"].get(fan_id)  # type: ignore[index]
        return dict(raw) if isinstance(raw, Mapping) else {}

    def _matching_record(
        self, fan: FanSnapshot, adapter: FanCalibrationAdapter
    ) -> dict[str, object]:
        raw = self._raw_record(fan.fan_id)
        if not raw:
            return {}
        if raw.get("profile") != adapter.profile_name:
            return {}
        if raw.get("hardware_identity") != adapter.hardware_identity(fan):
            return {}
        return raw

    def record(
        self, fan: FanSnapshot, adapter: FanCalibrationAdapter
    ) -> dict[str, object]:
        return self._matching_record(fan, adapter)

    def _replace(
        self,
        fan: FanSnapshot,
        adapter: FanCalibrationAdapter,
        values: Mapping[str, object],
    ) -> None:
        with self._lock:
            data = self._load()
            fans = data["fans"]  # type: ignore[assignment]
            current_raw = fans.get(fan.fan_id)  # type: ignore[union-attr]
            current = (
                dict(current_raw)
                if isinstance(current_raw, Mapping)
                else {}
            )
            current.update(
                {
                    "fan_id": fan.fan_id,
                    "profile": adapter.profile_name,
                    "hardware_identity": adapter.hardware_identity(fan),
                    "chip": fan.chip,
                    "source_device": fan.source_device,
                    "fan_index": fan.fan_index,
                }
            )
            current.update(dict(values))
            fans[fan.fan_id] = current  # type: ignore[index]
            self._save(data)

    def needs_automatic_calibration(
        self, fan: FanSnapshot, adapter: FanCalibrationAdapter
    ) -> bool:
        if not adapter.supports(fan):
            return False
        record = self._matching_record(fan, adapter)
        if not record:
            return True
        return record.get("calibration_status") == "not_calibrated"

    def begin(
        self,
        fan: FanSnapshot,
        adapter: FanCalibrationAdapter,
        *,
        original: Mapping[str, str],
        started_at: str,
    ) -> None:
        self._replace(
            fan,
            adapter,
            {
                "calibration_status": "calibrating",
                "calibration_started_at": started_at,
                "pending_restore": dict(original),
                "error": None,
            },
        )

    def save_calibration(
        self,
        fan: FanSnapshot,
        adapter: FanCalibrationAdapter,
        *,
        max_rpm: int,
        calibrated_at: str,
    ) -> None:
        with self._lock:
            self._replace(
                fan,
                adapter,
                {
                    "max_rpm": int(max_rpm),
                    "calibrated_at": calibrated_at,
                    "max_rpm_updated_at": calibrated_at,
                    "max_rpm_source": "calibration",
                    "calibration_status": "calibrated",
                    "error": None,
                    "pending_restore": None,
                },
            )
            self._observed_high.pop(fan.fan_id, None)

    def mark_failed(
        self,
        fan: FanSnapshot,
        adapter: FanCalibrationAdapter,
        *,
        error: str,
    ) -> None:
        self._replace(
            fan,
            adapter,
            {
                "calibration_status": "failed",
                "error": error,
                "pending_restore": None,
            },
        )

    def mark_restore_failed(
        self,
        fan: FanSnapshot,
        adapter: FanCalibrationAdapter,
        *,
        error: str,
        original: Mapping[str, str] | None = None,
    ) -> None:
        values: dict[str, object] = {
            "calibration_status": "restore_failed",
            "error": error,
        }
        if original is not None:
            values["pending_restore"] = dict(original)
        self._replace(fan, adapter, values)

    def pending_records(self) -> tuple[tuple[str, dict[str, object]], ...]:
        data = self._load()
        fans = data["fans"]  # type: ignore[assignment]
        result = []
        for fan_id, raw in sorted(fans.items()):  # type: ignore[union-attr]
            if isinstance(raw, Mapping) and isinstance(raw.get("pending_restore"), Mapping):
                result.append((str(fan_id), dict(raw)))
        return tuple(result)

    @staticmethod
    def _stable(values: list[int]) -> int | None:
        if len(values) < OBSERVED_MAX_CONFIRMATIONS:
            return None
        window = values[-OBSERVED_MAX_CONFIRMATIONS:]
        median = float(statistics.median(window))
        if median <= 0:
            return None
        if (max(window) - min(window)) / median > CALIBRATION_PLATEAU_SPREAD:
            return None
        return int(median + 0.5)

    def _observe_max(
        self,
        fan: FanSnapshot,
        adapter: FanCalibrationAdapter,
        record: dict[str, object],
        *,
        observed_at: str | None,
    ) -> dict[str, object]:
        with self._lock:
            latest = self._matching_record(fan, adapter)
            if latest:
                record = latest
            if record.get("calibration_status") != "calibrated":
                self._observed_high.pop(fan.fan_id, None)
                return record

            max_rpm = record.get("max_rpm")
            rpm = fan.rpm
            if (
                not isinstance(max_rpm, int)
                or max_rpm <= 0
                or not isinstance(rpm, int)
                or rpm <= int(max_rpm * (1.0 + OBSERVED_MAX_TOLERANCE))
            ):
                self._observed_high.pop(fan.fan_id, None)
                return record

            samples = self._observed_high.setdefault(fan.fan_id, [])
            samples.append(rpm)
            if len(samples) > OBSERVED_MAX_CONFIRMATIONS:
                del samples[:-OBSERVED_MAX_CONFIRMATIONS]
            candidate = self._stable(samples)
            if candidate is None or candidate <= max_rpm:
                return record

            updated_at = observed_at
            self._replace(
                fan,
                adapter,
                {
                    "max_rpm": candidate,
                    "max_rpm_source": "observed",
                    "max_rpm_updated_at": updated_at,
                },
            )
            self._observed_high.pop(fan.fan_id, None)
            return self._matching_record(fan, adapter)

    def presentation(
        self,
        fan: FanSnapshot,
        adapter: FanCalibrationAdapter | None,
        *,
        observed_at: str | None = None,
    ) -> dict[str, object]:
        if adapter is None or not adapter.supports(fan):
            return {
                "calibration_supported": False,
                "calibration_status": "unsupported",
                "max_rpm": None,
                "calibrated_at": None,
                "max_rpm_updated_at": None,
                "max_rpm_source": None,
                "speed_percent": None,
                "calibration_error": None,
            }

        record = self._matching_record(fan, adapter)
        if not record:
            record = {
                "calibration_status": "not_calibrated",
                "max_rpm": None,
            }
        else:
            record = self._observe_max(
                fan,
                adapter,
                record,
                observed_at=observed_at,
            )

        max_rpm = record.get("max_rpm")
        speed_percent: int | None = None
        if isinstance(max_rpm, int) and max_rpm > 0 and fan.rpm is not None:
            raw = min(100.0, max(0.0, fan.rpm / max_rpm * 100.0))
            speed_percent = int(raw + 0.5)

        return {
            "calibration_supported": True,
            "calibration_status": str(record.get("calibration_status") or "not_calibrated"),
            "max_rpm": max_rpm if isinstance(max_rpm, int) else None,
            "calibrated_at": record.get("calibrated_at"),
            "max_rpm_updated_at": record.get("max_rpm_updated_at"),
            "max_rpm_source": record.get("max_rpm_source"),
            "speed_percent": speed_percent,
            "calibration_error": record.get("error"),
        }


class FanCalibrationManager:
    def __init__(
        self,
        *,
        registry: FanCalibrationRegistry,
        adapters: Iterable[FanCalibrationAdapter],
        now_iso: Callable[[], str],
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.registry = registry
        self.adapters = tuple(adapters)
        self.now_iso = now_iso
        self.sleep = sleep
        self.log = logging.getLogger(__name__)
        self._lock = threading.Lock()

    def adapter_for(self, fan: FanSnapshot) -> FanCalibrationAdapter | None:
        for adapter in self.adapters:
            if adapter.supports(fan):
                return adapter
        return None

    @staticmethod
    def _plateau(samples: list[int]) -> int | None:
        if len(samples) < CALIBRATION_PLATEAU_SAMPLES:
            return None
        window = samples[-CALIBRATION_PLATEAU_SAMPLES:]
        median = float(statistics.median(window))
        if median <= 0:
            return None
        if (max(window) - min(window)) / median > CALIBRATION_PLATEAU_SPREAD:
            return None
        return int(median + 0.5)

    def _calibrate_one(
        self,
        fan: FanSnapshot,
        adapter: FanCalibrationAdapter,
        *,
        cancelled: Callable[[], bool],
    ) -> str:
        original: Mapping[str, str] | None = None
        plateau: int | None = None
        error = "plateau not reached"
        restored = False

        try:
            original = dict(adapter.capture(fan))
            baseline = adapter.read_rpm(fan)
            self.registry.begin(
                fan,
                adapter,
                original=original,
                started_at=self.now_iso(),
            )
            adapter.enter_max(fan)
            samples: list[int] = []
            for sample_number in range(1, CALIBRATION_MAX_SAMPLES + 1):
                if cancelled():
                    raise RuntimeError("calibration cancelled")
                self.sleep(CALIBRATION_SAMPLE_INTERVAL_SECONDS)
                rpm = adapter.read_rpm(fan)
                if not isinstance(rpm, int) or rpm <= 0:
                    continue
                samples.append(rpm)
                candidate = self._plateau(samples)
                if (
                    candidate is not None
                    and sample_number >= CALIBRATION_MIN_SPINUP_SAMPLES
                ):
                    accelerated = (
                        baseline is None
                        or baseline <= 0
                        or adapter.original_is_max(original)
                        or candidate >= baseline * (1.0 + CALIBRATION_MIN_ACCELERATION)
                    )
                    if accelerated:
                        plateau = candidate
                        break
            if plateau is None:
                error = "plateau not reached"
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            if original is not None:
                try:
                    adapter.restore(fan, original)
                    restored = bool(adapter.verify_restored(fan, original))
                    if not restored:
                        raise RuntimeError("restored fan control state did not verify")
                except Exception as exc:
                    self.registry.mark_restore_failed(
                        fan,
                        adapter,
                        error=f"{type(exc).__name__}: {exc}",
                        original=original,
                    )
                    self.log.error(
                        "Fan calibration restore failed for %s: %s",
                        fan.fan_id,
                        exc,
                    )
                    return "restore_failed"

        if plateau is not None and restored:
            self.registry.save_calibration(
                fan,
                adapter,
                max_rpm=plateau,
                calibrated_at=self.now_iso(),
            )
            self.log.info("Fan %s calibrated: max_rpm=%s", fan.fan_id, plateau)
            return "calibrated"

        self.registry.mark_failed(fan, adapter, error=error)
        self.log.warning("Fan calibration failed for %s: %s", fan.fan_id, error)
        return "failed"

    def calibrate(
        self,
        fans: Iterable[FanSnapshot],
        *,
        automatic: bool,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> dict[str, str]:
        if not self._lock.acquire(blocking=False):
            return {"_status": "busy"}
        try:
            result: dict[str, str] = {}
            for fan in sorted(fans, key=lambda item: item.fan_id):
                adapter = self.adapter_for(fan)
                if adapter is None:
                    continue
                if automatic and not self.registry.needs_automatic_calibration(
                    fan, adapter
                ):
                    continue
                result[fan.fan_id] = self._calibrate_one(
                    fan,
                    adapter,
                    cancelled=cancelled,
                )
            return result
        finally:
            self._lock.release()

    def recover_pending(self, fans: Iterable[FanSnapshot]) -> dict[str, str]:
        by_id = {fan.fan_id: fan for fan in fans}
        result: dict[str, str] = {}
        for fan_id, record in self.registry.pending_records():
            fan = by_id.get(fan_id)
            if fan is None:
                result[fan_id] = "restore_failed"
                continue
            adapter = self.adapter_for(fan)
            original = record.get("pending_restore")
            if adapter is None or not isinstance(original, Mapping):
                result[fan_id] = "restore_failed"
                continue
            try:
                adapter.restore(fan, {str(k): str(v) for k, v in original.items()})
                if not adapter.verify_restored(
                    fan,
                    {str(k): str(v) for k, v in original.items()},
                ):
                    raise RuntimeError("restored fan control state did not verify")
            except Exception as exc:
                self.registry.mark_restore_failed(
                    fan,
                    adapter,
                    error=f"{type(exc).__name__}: {exc}",
                    original={str(k): str(v) for k, v in original.items()},
                )
                result[fan_id] = "restore_failed"
                continue
            self.registry.mark_failed(
                fan,
                adapter,
                error="interrupted calibration restored on startup",
            )
            result[fan_id] = "recovered"
        return result
