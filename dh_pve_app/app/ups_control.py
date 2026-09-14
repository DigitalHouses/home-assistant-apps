from __future__ import annotations

import subprocess
from dataclasses import dataclass, replace
from typing import Callable

from .config import UpsConfig


_BATTERY_TEST_COMMANDS = {
    "quick": "test.battery.start.quick",
    "deep": "test.battery.start.deep",
    "stop": "test.battery.stop",
}


class NutControlError(RuntimeError):
    """Raised when an allowed NUT instant command cannot be completed."""


@dataclass(frozen=True)
class UpsCapabilities:
    commands: tuple[str, ...]
    battery_tests: tuple[str, ...]
    beeper_control: bool
    load_control: bool
    shutdown_control: bool
    supported_features: tuple[str, ...]
    controls_enabled: bool = True

    def supports_test(self, action: str) -> bool:
        return self.controls_enabled and action in self.battery_tests

    def as_dict(self) -> dict[str, object]:
        return {
            "available": True,
            "count": len(self.commands),
            "commands": list(self.commands),
            "battery_tests": list(self.battery_tests),
            "beeper_control": self.beeper_control,
            "load_control": self.load_control,
            "shutdown_control": self.shutdown_control,
            "supported_features": list(self.supported_features),
            "test_controls_enabled": self.controls_enabled,
        }


def parse_upscmd_list_output(text: str) -> UpsCapabilities:
    commands: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or " - " not in line:
            continue
        command = line.split(" - ", 1)[0].strip()
        if command and command not in commands:
            commands.append(command)

    command_set = set(commands)
    battery_tests = tuple(
        action
        for action in ("quick", "deep", "stop")
        if _BATTERY_TEST_COMMANDS[action] in command_set
    )
    beeper_control = any(command.startswith("beeper.") for command in commands)
    load_control = any(command.startswith("load.") for command in commands)
    shutdown_control = any(command.startswith("shutdown.") for command in commands)

    features: list[str] = []
    if battery_tests:
        features.append("Battery tests")
    if beeper_control:
        features.append("Beeper control")
    if load_control:
        features.append("Load control")
    if shutdown_control:
        features.append("Shutdown control")

    return UpsCapabilities(
        commands=tuple(commands),
        battery_tests=battery_tests,
        beeper_control=beeper_control,
        load_control=load_control,
        shutdown_control=shutdown_control,
        supported_features=tuple(features),
    )


def list_ups_commands(
    config: UpsConfig,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> UpsCapabilities:
    command = ["upscmd", "-l", f"{config.name}@{config.host}:{config.port}"]
    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            timeout=config.command_timeout_seconds,
            check=True,
        )
    except FileNotFoundError as exc:
        raise NutControlError("Команда upscmd не найдена") from exc
    except subprocess.TimeoutExpired as exc:
        raise NutControlError("Истекло время ожидания списка команд NUT") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise NutControlError(detail or "NUT не вернул список команд UPS") from exc
    except OSError as exc:
        raise NutControlError(f"Не удалось запустить upscmd: {exc}") from exc

    capabilities = parse_upscmd_list_output(completed.stdout)
    controls_enabled = bool(config.command_username and config.command_password)
    return replace(capabilities, controls_enabled=controls_enabled)


def _sanitize_detail(detail: str, config: UpsConfig) -> str:
    sanitized = detail
    for secret in (config.command_password, config.command_username):
        if secret:
            sanitized = sanitized.replace(secret, "***")
    return sanitized


def run_ups_battery_test(
    config: UpsConfig,
    action: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    nut_command = _BATTERY_TEST_COMMANDS.get(action)
    if nut_command is None:
        raise ValueError(f"Неподдерживаемое действие теста UPS: {action}")
    if not config.command_username or not config.command_password:
        raise NutControlError("Не настроены учётные данные NUT для команд UPS")

    command = [
        "upscmd",
        "-u",
        config.command_username,
        "-p",
        config.command_password,
        f"{config.name}@{config.host}:{config.port}",
        nut_command,
    ]
    try:
        runner(
            command,
            capture_output=True,
            text=True,
            timeout=config.command_timeout_seconds,
            check=True,
        )
    except FileNotFoundError as exc:
        raise NutControlError("Команда upscmd не найдена") from exc
    except subprocess.TimeoutExpired as exc:
        raise NutControlError("Истекло время ожидания команды NUT") from exc
    except subprocess.CalledProcessError as exc:
        detail = _sanitize_detail((exc.stderr or "").strip(), config)
        raise NutControlError(detail or "NUT отклонил команду теста UPS") from exc
    except OSError as exc:
        raise NutControlError(f"Не удалось запустить upscmd: {exc}") from exc
