from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Sequence


class PolicyValidationError(ValueError):
    """Raised when a shutdown-policy value or combination is unsafe."""


@dataclass(frozen=True)
class UpsPolicyDraft:
    on_battery_delay_minutes: int
    emergency_runtime_reserve_minutes: int
    power_restore_delay_seconds: int

    def as_dict(self) -> dict[str, int]:
        return {
            "on_battery_delay_minutes": self.on_battery_delay_minutes,
            "emergency_runtime_reserve_minutes": self.emergency_runtime_reserve_minutes,
            "power_restore_delay_seconds": self.power_restore_delay_seconds,
        }


@dataclass(frozen=True)
class GuestShutdownTask:
    vmid: int
    order: int | None
    timeout_seconds: int


@dataclass(frozen=True)
class PolicySafetyFacts:
    guest_shutdown_budget_seconds: int
    hostsync_seconds: int
    finaldelay_seconds: int
    host_shutdown_reserve_seconds: int = 60
    ups_poweroff_delay_seconds: int = 60
    safety_margin_seconds: int = 60


@dataclass(frozen=True)
class PolicyValidationResult:
    on_battery_delay_seconds: int
    emergency_runtime_reserve_seconds: int
    power_restore_delay_seconds: int
    minimum_emergency_runtime_reserve_seconds: int
    recommended_emergency_runtime_reserve_seconds: int


@dataclass(frozen=True)
class PolicyApplyResult:
    success: bool
    message: str


_POLICY_RANGES: dict[str, tuple[int, int, int]] = {
    "on_battery_delay_minutes": (5, 60, 5),
    "emergency_runtime_reserve_minutes": (10, 30, 1),
    "power_restore_delay_seconds": (60, 300, 30),
}


def _validate_value(key: str, value: int) -> int:
    limits = _POLICY_RANGES.get(key)
    if limits is None:
        raise PolicyValidationError(f"Неизвестный параметр политики: {key}")
    minimum, maximum, step = limits
    if value < minimum or value > maximum:
        if key == "emergency_runtime_reserve_minutes":
            raise PolicyValidationError(
                f"Аварийный резерв должен быть от {minimum} до {maximum} мин."
            )
        raise PolicyValidationError(
            f"Параметр {key} должен быть от {minimum} до {maximum}."
        )
    if (value - minimum) % step != 0:
        raise PolicyValidationError(
            f"Параметр {key} должен изменяться с шагом {step}."
        )
    return value


def parse_policy_value(key: str, text: str) -> int:
    try:
        numeric = float(text.strip())
    except (TypeError, ValueError, AttributeError) as exc:
        raise PolicyValidationError(f"Некорректное значение параметра {key}.") from exc
    if not math.isfinite(numeric) or not numeric.is_integer():
        raise PolicyValidationError(f"Некорректное значение параметра {key}.")
    return _validate_value(key, int(numeric))


def policy_hash(policy: UpsPolicyDraft) -> str:
    canonical = json.dumps(
        policy.as_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _group_budget(tasks: Sequence[GuestShutdownTask], max_workers: int) -> int:
    if not tasks:
        return 0
    workers = [0 for _ in range(max_workers)]
    for task in sorted(tasks, key=lambda item: item.vmid, reverse=True):
        worker = min(range(max_workers), key=lambda index: workers[index])
        workers[worker] += max(0, int(task.timeout_seconds))
    return max(workers)


def calculate_guest_shutdown_budget(
    tasks: Sequence[GuestShutdownTask],
    *,
    max_workers: int,
) -> int:
    if max_workers < 1:
        raise PolicyValidationError("Количество Proxmox shutdown workers должно быть не меньше 1.")

    groups: dict[int | None, list[GuestShutdownTask]] = {}
    for task in tasks:
        groups.setdefault(task.order, []).append(task)

    def order_key(order: int | None) -> tuple[int, int]:
        if order is None:
            return (1, 0)
        return (0, order)

    total = 0
    for order in sorted(groups, key=order_key, reverse=True):
        total += _group_budget(groups[order], max_workers)
    return total


def validate_policy(
    draft: UpsPolicyDraft,
    facts: PolicySafetyFacts,
) -> PolicyValidationResult:
    on_battery = _validate_value(
        "on_battery_delay_minutes", draft.on_battery_delay_minutes
    )
    reserve_minutes = _validate_value(
        "emergency_runtime_reserve_minutes",
        draft.emergency_runtime_reserve_minutes,
    )
    restore_delay = _validate_value(
        "power_restore_delay_seconds", draft.power_restore_delay_seconds
    )

    for name, value in (
        ("guest_shutdown_budget_seconds", facts.guest_shutdown_budget_seconds),
        ("hostsync_seconds", facts.hostsync_seconds),
        ("finaldelay_seconds", facts.finaldelay_seconds),
        ("host_shutdown_reserve_seconds", facts.host_shutdown_reserve_seconds),
        ("ups_poweroff_delay_seconds", facts.ups_poweroff_delay_seconds),
        ("safety_margin_seconds", facts.safety_margin_seconds),
    ):
        if value < 0:
            raise PolicyValidationError(f"Некорректный расчетный параметр политики: {name}.")

    minimum_reserve = (
        facts.guest_shutdown_budget_seconds
        + facts.hostsync_seconds
        + facts.finaldelay_seconds
        + facts.host_shutdown_reserve_seconds
        + facts.ups_poweroff_delay_seconds
        + facts.safety_margin_seconds
    )
    reserve_seconds = reserve_minutes * 60
    if reserve_seconds < minimum_reserve:
        minimum_minutes = math.ceil(minimum_reserve / 60)
        raise PolicyValidationError(
            "Аварийный резерв недостаточен: "
            f"нужно не менее {minimum_minutes} мин. для корректного выключения."
        )

    recommended = math.ceil((minimum_reserve + 300) / 60) * 60
    return PolicyValidationResult(
        on_battery_delay_seconds=on_battery * 60,
        emergency_runtime_reserve_seconds=reserve_seconds,
        power_restore_delay_seconds=restore_delay,
        minimum_emergency_runtime_reserve_seconds=minimum_reserve,
        recommended_emergency_runtime_reserve_seconds=recommended,
    )
