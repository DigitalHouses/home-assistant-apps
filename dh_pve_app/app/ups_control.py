from __future__ import annotations

import socket
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


def verify_nut_credentials(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    timeout_seconds: float,
    connector: Callable[..., object] = socket.create_connection,
) -> None:
    """Verify NUT credentials without executing a UPS instant command."""
    if not username or not password:
        raise NutControlError("Не настроены учётные данные NUT для команд UPS")

    def sanitize(text: str) -> str:
        return text.replace(password, "***").replace(username, "***")

    try:
        with connector((host, port), timeout_seconds) as connection:
            stream = connection.makefile("rwb")
            exchanges = (
                (f"USERNAME {username}\n", "USERNAME"),
                (f"PASSWORD {password}\n", "PASSWORD"),
                ("SET TRACKING OFF\n", "TRACKING"),
            )
            for request, stage in exchanges:
                stream.write(request.encode("utf-8"))
                stream.flush()
                response = stream.readline().decode("utf-8", errors="replace").strip()
                if not response.upper().startswith("OK"):
                    detail = sanitize(response or "нет ответа")
                    raise NutControlError(
                        f"NUT credential probe {stage} отклонен: {detail}"
                    )

            stream.write(b"LOGOUT\n")
            stream.flush()
            stream.readline()
    except NutControlError:
        raise
    except (OSError, TimeoutError, socket.timeout) as exc:
        detail = sanitize(str(exc))
        raise NutControlError(
            f"Не удалось проверить учётные данные NUT: {detail}"
        ) from exc


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

    def beeper_command(self, enabled: bool) -> str | None:
        candidates = ("beeper.enable", "beeper.on") if enabled else ("beeper.disable", "beeper.off")
        return next((command for command in candidates if command in self.commands), None)

    def supports_beeper_switch(self) -> bool:
        return (
            self.controls_enabled
            and self.beeper_command(True) is not None
            and self.beeper_command(False) is not None
        )

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


_BEEPER_COMMANDS = {
    "beeper.on",
    "beeper.off",
    "beeper.enable",
    "beeper.disable",
}


def run_ups_beeper_command(
    config: UpsConfig,
    command_name: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    if command_name not in _BEEPER_COMMANDS:
        raise ValueError(f"Неподдерживаемая команда пищалки UPS: {command_name}")
    if not config.command_username or not config.command_password:
        raise NutControlError("Не настроены учётные данные NUT для команд UPS")

    command = [
        "upscmd",
        "-u",
        config.command_username,
        "-p",
        config.command_password,
        f"{config.name}@{config.host}:{config.port}",
        command_name,
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
        raise NutControlError(detail or "NUT отклонил команду пищалки UPS") from exc
    except OSError as exc:
        raise NutControlError(f"Не удалось запустить upscmd: {exc}") from exc
