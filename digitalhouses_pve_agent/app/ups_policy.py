from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Sequence


class PolicyValidationError(ValueError):
    """Raised when a shutdown-policy value or combination is unsafe."""


DEFAULT_SHUTDOWN_BATTERY_CHARGE_THRESHOLD_PERCENT = 20
DEFAULT_RUNTIME_RESERVE_SECONDS = 180


@dataclass(frozen=True)
class UpsPolicyDraft:
    shutdown_battery_charge_threshold_percent: int
    runtime_reserve_seconds: int

    def as_dict(self) -> dict[str, int]:
        return {
            "shutdown_battery_charge_threshold_percent": (
                self.shutdown_battery_charge_threshold_percent
            ),
            "runtime_reserve_seconds": self.runtime_reserve_seconds,
        }


@dataclass(frozen=True)
class GuestShutdownTask:
    vmid: int
    order: int | None
    timeout_seconds: int


@dataclass(frozen=True)
class PolicySafetyFacts:
    """Legacy-compatible host facts container pending the canonical budget engine."""

    guest_shutdown_budget_seconds: int
    hostsync_seconds: int
    finaldelay_seconds: int
    host_shutdown_reserve_seconds: int = 60
    ups_poweroff_delay_seconds: int = 60
    safety_margin_seconds: int = 60


@dataclass(frozen=True)
class PolicyValidationResult:
    shutdown_battery_charge_threshold_percent: int
    runtime_reserve_seconds: int


@dataclass(frozen=True)
class PolicyApplyResult:
    success: bool
    message: str


_POLICY_RANGES: dict[str, tuple[int, int, int]] = {
    "shutdown_battery_charge_threshold_percent": (10, 30, 5),
    "runtime_reserve_seconds": (60, 900, 60),
}


def _validate_value(key: str, value: int) -> int:
    limits = _POLICY_RANGES.get(key)
    if limits is None:
        raise PolicyValidationError(f"Неизвестный параметр политики: {key}")
    minimum, maximum, step = limits
    if value < minimum or value > maximum:
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


def policy_from_mapping(value: object) -> UpsPolicyDraft | None:
    if not isinstance(value, dict):
        return None
    expected = {
        "shutdown_battery_charge_threshold_percent",
        "runtime_reserve_seconds",
    }
    if set(value) != expected:
        return None
    try:
        draft = UpsPolicyDraft(
            shutdown_battery_charge_threshold_percent=int(
                value["shutdown_battery_charge_threshold_percent"]
            ),
            runtime_reserve_seconds=int(value["runtime_reserve_seconds"]),
        )
        validate_policy(draft)
    except (TypeError, ValueError, PolicyValidationError):
        return None
    return draft


def migrate_legacy_policy_state(
    raw: object,
    *,
    shutdown_battery_charge_threshold_percent: int | None,
) -> UpsPolicyDraft | None:
    """Build an unapplied v2 draft from legacy state without reusing timer semantics."""

    current = policy_from_mapping(raw)
    if current is not None:
        return current
    if not isinstance(raw, dict):
        return None
    if not ({"on_battery_delay_minutes", "power_restore_delay_seconds"} & set(raw)):
        return None
    if shutdown_battery_charge_threshold_percent is None:
        return None
    try:
        threshold = _validate_value(
            "shutdown_battery_charge_threshold_percent",
            int(shutdown_battery_charge_threshold_percent),
        )
    except (TypeError, ValueError, PolicyValidationError):
        return None
    return UpsPolicyDraft(
        shutdown_battery_charge_threshold_percent=threshold,
        runtime_reserve_seconds=DEFAULT_RUNTIME_RESERVE_SECONDS,
    )


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
        raise PolicyValidationError(
            "Количество Proxmox shutdown workers должно быть не меньше 1."
        )

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
    facts: PolicySafetyFacts | None = None,
) -> PolicyValidationResult:
    charge_threshold = _validate_value(
        "shutdown_battery_charge_threshold_percent",
        draft.shutdown_battery_charge_threshold_percent,
    )
    reserve = _validate_value(
        "runtime_reserve_seconds",
        draft.runtime_reserve_seconds,
    )

    if facts is not None:
        for name, value in (
            ("guest_shutdown_budget_seconds", facts.guest_shutdown_budget_seconds),
            ("hostsync_seconds", facts.hostsync_seconds),
            ("finaldelay_seconds", facts.finaldelay_seconds),
            ("host_shutdown_reserve_seconds", facts.host_shutdown_reserve_seconds),
            ("ups_poweroff_delay_seconds", facts.ups_poweroff_delay_seconds),
            ("safety_margin_seconds", facts.safety_margin_seconds),
        ):
            if value < 0:
                raise PolicyValidationError(
                    f"Некорректный расчетный параметр политики: {name}."
                )

    return PolicyValidationResult(
        shutdown_battery_charge_threshold_percent=charge_threshold,
        runtime_reserve_seconds=reserve,
    )
