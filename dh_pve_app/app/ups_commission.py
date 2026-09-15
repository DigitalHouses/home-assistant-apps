from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

from .config import UpsConfig
from .ups_control import verify_nut_credentials
from .ups_nut import UpsSnapshot, read_ups
from .ups_policy import PolicyApplyResult, UpsPolicyDraft
from .ups_policy_apply import ManagedNutPaths, PolicyApplyError, UpsPolicyApplier
from .ups_policy_host import read_policy_safety_facts
from .ups_shutdown_policy import UpsShutdownPolicy, read_shutdown_policy
from .ups_test_history import normalize_test_result


def commission_ups_policy(
    config: UpsConfig,
    *,
    on_battery_delay_minutes: int,
    power_restore_delay_seconds: int,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ups_reader: Callable[[UpsConfig], UpsSnapshot] = read_ups,
    shutdown_policy_reader: Callable[[], UpsShutdownPolicy] | None = None,
    killpower_path: Path = Path("/etc/killpower"),
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

    if killpower_path.exists():
        return PolicyApplyResult(
            False,
            f"Commissioning UPS/NUT запрещен: обнаружен POWERDOWNFLAG {killpower_path}.",
        )

    try:
        policy_reader = shutdown_policy_reader or (
            lambda: read_shutdown_policy(ups_name=config.name)
        )
        current_policy = policy_reader()
    except Exception as exc:
        return PolicyApplyResult(
            False,
            f"Не удалось прочитать текущую NUT policy: {type(exc).__name__}.",
        )
    if current_policy.role != "primary":
        return PolicyApplyResult(
            False,
            "Commissioning UPS/NUT разрешен только для upsmon PRIMARY; "
            f"текущая роль: {current_policy.role}.",
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

    def credential_verifier(username: str, password: str) -> None:
        verify_nut_credentials(
            host=config.host,
            port=config.port,
            ups_name=config.name,
            username=username,
            password=password,
            timeout_seconds=config.command_timeout_seconds,
        )

    applier = applier_factory(
        paths=ManagedNutPaths(),
        ups_name=config.name,
        runner=runner,
        effective_restart_delay_reader=effective_restart_delay_reader,
        credential_verifier=credential_verifier,
    )
    return applier.apply(draft, facts)
