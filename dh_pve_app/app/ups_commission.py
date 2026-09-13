from __future__ import annotations

import os
import subprocess
from collections.abc import Callable

from .config import UpsConfig
from .ups_nut import UpsSnapshot, read_ups
from .ups_policy import PolicyApplyResult, UpsPolicyDraft
from .ups_policy_apply import ManagedNutPaths, PolicyApplyError, UpsPolicyApplier
from .ups_policy_host import read_policy_safety_facts
from .ups_test_history import normalize_test_result


def commission_ups_policy(
    config: UpsConfig,
    *,
    on_battery_delay_minutes: int,
    power_restore_delay_seconds: int,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ups_reader: Callable[[UpsConfig], UpsSnapshot] = read_ups,
    geteuid: Callable[[], int] = os.geteuid,
    applier_factory=UpsPolicyApplier,
) -> PolicyApplyResult:
    """Explicit root-only NUT commissioning. Never called by the daemon/MQTT."""
    if geteuid() != 0:
        return PolicyApplyResult(
            False,
            "Commissioning UPS/NUT требует запуска от root.",
        )

    try:
        snapshot = ups_reader(config)
    except Exception as exc:
        return PolicyApplyResult(
            False,
            f"Не удалось прочитать UPS перед commissioning: {type(exc).__name__}.",
        )

    if normalize_test_result(snapshot.test_result) == "Running":
        return PolicyApplyResult(
            False,
            "Commissioning UPS/NUT запрещен во время теста батареи.",
        )
    if (
        not snapshot.line_power
        or snapshot.on_battery
        or snapshot.low_battery
        or snapshot.discharging
    ):
        status = snapshot.status_raw or "unknown"
        return PolicyApplyResult(
            False,
            "Commissioning UPS/NUT разрешен только при стабильном питании "
            f"от сети (OL); текущий статус: {status}.",
        )

    try:
        facts = read_policy_safety_facts(config)
    except Exception as exc:
        return PolicyApplyResult(
            False,
            f"Не удалось рассчитать shutdown budget PVE: {type(exc).__name__}.",
        )

    draft = UpsPolicyDraft(
        on_battery_delay_minutes=on_battery_delay_minutes,
        power_restore_delay_seconds=power_restore_delay_seconds,
    )

    def effective_restart_delay_reader() -> int:
        current = ups_reader(config)
        value = current.ups_start_delay_seconds
        if value is None or value < 0 or not float(value).is_integer():
            raise PolicyApplyError(
                "UPS не сообщил корректную задержку восстановления питания."
            )
        return int(value)

    applier = applier_factory(
        paths=ManagedNutPaths(),
        ups_name=config.name,
        runner=runner,
        effective_restart_delay_reader=effective_restart_delay_reader,
    )
    return applier.apply(draft, facts)
