from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from .config import UpsConfig
from .ups_policy import (
    GuestShutdownTask,
    PolicySafetyFacts,
    PolicyValidationError,
    calculate_guest_shutdown_budget,
)
from .ups_shutdown_policy import UpsShutdownPolicy, read_shutdown_policy


DEFAULT_QEMU_DIR = Path("/etc/pve/qemu-server")
DEFAULT_LXC_DIR = Path("/etc/pve/lxc")
DEFAULT_DATACENTER_PATH = Path("/etc/pve/datacenter.cfg")


def _read_key_values(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    result: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip()
    return result


def _startup_values(text: str | None) -> tuple[int | None, int]:
    order: int | None = None
    timeout = 180
    if not text:
        return order, timeout
    for item in text.split(","):
        key, separator, value = item.strip().partition("=")
        if not separator:
            continue
        try:
            number = int(value.strip())
        except ValueError:
            continue
        if key.strip() == "order":
            order = number
        elif key.strip() == "down" and number >= 0:
            timeout = number
    return order, timeout


def _running_ids(output: str) -> set[int]:
    running: set[int] = set()
    for raw in output.splitlines():
        parts = raw.split()
        if not parts or not parts[0].isdigit():
            continue
        if any(part.casefold() == "running" for part in parts[1:4]):
            running.add(int(parts[0]))
    return running


def _run_text(
    runner: Callable[..., subprocess.CompletedProcess[str]],
    command: list[str],
    *,
    timeout: float = 5.0,
) -> str:
    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PolicyValidationError(
            f"Не удалось получить данные Proxmox/NUT: {command[0]}."
        ) from exc
    if completed.returncode != 0:
        raise PolicyValidationError(
            f"Не удалось получить данные Proxmox/NUT: {command[0]}."
        )
    return completed.stdout or ""


def _guest_tasks(directory: Path, running_ids: set[int]) -> list[GuestShutdownTask]:
    tasks: list[GuestShutdownTask] = []
    try:
        paths = sorted(directory.glob("*.conf"))
    except OSError as exc:
        raise PolicyValidationError(
            f"Не удалось прочитать конфигурацию Proxmox: {directory}."
        ) from exc

    for path in paths:
        try:
            vmid = int(path.stem)
        except ValueError:
            continue
        config = _read_key_values(path)
        if config.get("template", "0") == "1":
            continue
        onboot = config.get("onboot", "0") == "1"
        if not onboot and vmid not in running_ids:
            continue
        order, timeout = _startup_values(config.get("startup"))
        tasks.append(
            GuestShutdownTask(
                vmid=vmid,
                order=order,
                timeout_seconds=timeout,
            )
        )
    return tasks


def _max_workers(
    datacenter_path: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> int:
    config = _read_key_values(datacenter_path)
    raw = config.get("max_workers")
    if raw is not None:
        try:
            workers = int(raw)
        except ValueError as exc:
            raise PolicyValidationError(
                "Некорректный max_workers в datacenter.cfg."
            ) from exc
        if workers < 1:
            raise PolicyValidationError(
                "Некорректный max_workers в datacenter.cfg."
            )
        return workers

    output = _run_text(runner, ["nproc"], timeout=3.0).strip()
    try:
        workers = int(output)
    except ValueError as exc:
        raise PolicyValidationError("Не удалось определить число CPU Proxmox.") from exc
    if workers < 1:
        raise PolicyValidationError("Не удалось определить число CPU Proxmox.")
    return workers


def _ups_poweroff_delay(
    config: UpsConfig,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> int:
    target = f"{config.name}@{config.host}:{config.port}"
    output = _run_text(
        runner,
        ["upsc", target, "ups.delay.shutdown"],
        timeout=config.command_timeout_seconds,
    ).strip()
    try:
        delay = int(float(output))
    except ValueError as exc:
        raise PolicyValidationError(
            "NUT не сообщил задержку выключения выхода UPS."
        ) from exc
    if delay < 0:
        raise PolicyValidationError(
            "NUT сообщил некорректную задержку выключения выхода UPS."
        )
    return delay


def read_policy_safety_facts(
    config: UpsConfig,
    *,
    qemu_dir: Path = DEFAULT_QEMU_DIR,
    lxc_dir: Path = DEFAULT_LXC_DIR,
    datacenter_path: Path = DEFAULT_DATACENTER_PATH,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    shutdown_policy_reader: Callable[[], UpsShutdownPolicy] = read_shutdown_policy,
) -> PolicySafetyFacts:
    qemu_running = _running_ids(_run_text(runner, ["qm", "list"]))
    lxc_running = _running_ids(_run_text(runner, ["pct", "list"]))

    tasks = _guest_tasks(qemu_dir, qemu_running)
    tasks.extend(_guest_tasks(lxc_dir, lxc_running))
    workers = _max_workers(datacenter_path, runner)
    guest_budget = calculate_guest_shutdown_budget(tasks, max_workers=workers)

    shutdown_policy = shutdown_policy_reader()
    hostsync = shutdown_policy.hostsync_seconds
    finaldelay = shutdown_policy.finaldelay_seconds
    if hostsync is None or hostsync < 0:
        raise PolicyValidationError("В NUT не определен корректный HOSTSYNC.")
    if finaldelay is None or finaldelay < 0:
        raise PolicyValidationError("В NUT не определен корректный FINALDELAY.")

    return PolicySafetyFacts(
        guest_shutdown_budget_seconds=guest_budget,
        hostsync_seconds=hostsync,
        finaldelay_seconds=finaldelay,
        ups_poweroff_delay_seconds=_ups_poweroff_delay(config, runner),
    )
