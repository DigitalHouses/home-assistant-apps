"""Fixed, one-step-at-a-time NUT commissioning operations.

Invoked only by the installed root-owned systemd oneshot. The monitoring daemon
cannot write /etc/nut under ProtectSystem=full. All actions are fail-closed:
an existing external or multi-UPS installation is deliberately not rewritten.
No action issues FSD, ups output commands, guest shutdown or reboot.
"""
from __future__ import annotations

import argparse
import fcntl
import grp
import os
import re
import secrets
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .cli import set_config
from .config import load_config
from .restart_safety import guard_restart
from .state_store import StateStore
from .ups_setup import (
    DRIVER_PATTERN, VALID_STAGES, driver_options, service_status,
    setup_snapshot, usb_ups_devices,
)

DEFAULT_CONFIG = Path("/etc/digitalhouses_pve_agent/digitalhouses_pve_agent.conf")
DEFAULT_STATE = Path("/var/lib/digitalhouses_pve_agent")
DEFAULT_NUT = Path("/etc/nut")
DEFAULT_HELPER = Path("/opt/digitalhouses/digitalhouses_pve_agent/bin/digitalhouses-pve-agent-ups-policy-cmd")


class UpsSetupError(RuntimeError):
    pass


def run_checked(args: list[str], *, timeout: float = 30, runner: Callable = subprocess.run) -> None:
    try:
        completed = runner(args, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UpsSetupError(f"Не удалось выполнить {args[0]}") from exc
    if completed.returncode != 0:
        raise UpsSetupError(f"Не удалось выполнить {args[0]} (код {completed.returncode})")


def live_ol(name: str, *, runner: Callable = subprocess.run) -> bool:
    try:
        result = runner(["upsc", f"{name}@127.0.0.1:3493", "ups.status"],
                        capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    flags = set((result.stdout or "").strip().split())
    return result.returncode == 0 and "OL" in flags and not flags.intersection(
        {"OB", "LB", "FSD", "OVER", "DISCHRG", "RB"}
    )


def _read(path: Path) -> str:
    try:
        if path.is_symlink():
            raise UpsSetupError(f"Символическая ссылка вместо конфигурации: {path.name}")
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _sections(text: str) -> list[str]:
    return re.findall(r"^\s*\[([A-Za-z0-9_.-]+)\]\s*$", text, re.M)


def _backup_and_write(updates: dict[Path, str], *, state_dir: Path) -> dict[Path, tuple[bytes | None, int, int, int]]:
    """Backup every target before the first write; restore all on write failure."""
    changed = {path: data for path, data in updates.items() if _read(path) != data}
    if not changed:
        return {}
    if any(path.is_symlink() for path in changed):
        raise UpsSetupError("Обнаружена ссылка на конфигурационный файл")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = state_dir / "nut_setup_backups" / stamp
    backup.mkdir(parents=True, exist_ok=False, mode=0o700)
    restore: dict[Path, tuple[bytes | None, int, int, int]] = {}
    for path in changed:
        if path.exists():
            info = path.stat()
            restore[path] = (path.read_bytes(), info.st_mode & 0o777, info.st_uid, info.st_gid)
            shutil.copy2(path, backup / (path.parent.name + "-" + path.name))
        else:
            restore[path] = (None, 0o640, os.getuid(), _nut_gid())
    try:
        for path, new_data in changed.items():
            prev, mode, uid, gid = restore[path]
            if path.name in {"upsmon.conf", "upsd.users"}:
                mode = 0o640
                gid = _nut_gid()
            _atomic_replace(path, new_data.encode("utf-8"), mode, uid, gid)
    except Exception:
        _restore_changes(restore)
        raise
    return restore


def _restore_changes(restore: dict[Path, tuple[bytes | None, int, int, int]]) -> None:
    for path, (previous, mode, uid, gid) in restore.items():
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            _atomic_replace(path, previous, mode, uid, gid)


def _nut_gid() -> int:
    try:
        return grp.getgrnam("nut").gr_gid
    except KeyError:
        return 0


def _atomic_replace(path: Path, content: bytes, mode: int, uid: int, gid: int) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=".dh-ups-", dir=path.parent)
    tmp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), mode)
            os.fchown(handle.fileno(), uid, gid)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _single_ups(config, state_dir: Path, nut_dir: Path) -> str:
    # Fully managed local USB-only site. Protect all remote or multi-UPS setups.
    from .ups_setup import _configured_name, _managed_source
    if not _managed_source(config, nut_dir):
        raise UpsSetupError("Существующий сетевой/SNMP NUT не изменяется автоматически")
    name = _configured_name(config, state_dir, nut_dir)
    if not DRIVER_PATTERN.fullmatch(name):
        raise UpsSetupError("Недопустимое имя UPS")
    names = _sections(_read(nut_dir / "ups.conf"))
    if len(names) > 1 or names and names != [name]:
        raise UpsSetupError("Обнаружена нестандартная конфигурация нескольких UPS")
    return name


def execute(
    stage: str,
    *,
    state_dir: Path = DEFAULT_STATE,
    nut_dir: Path = DEFAULT_NUT,
    app_conf: Path = DEFAULT_CONFIG,
    sysfs_root: Path = Path("/sys/bus/usb/devices"),
    runner: Callable = subprocess.run,
) -> str:
    if stage not in VALID_STAGES:
        raise UpsSetupError("Неизвестное действие настройки")
    if os.geteuid() != 0:
        raise UpsSetupError("Настройка NUT выполняется только системной службой root")
    devices = usb_ups_devices(sysfs_root)
    if len(devices) != 1:
        raise UpsSetupError("Нужен ровно один однозначно обнаруженный USB UPS")
    config = load_config(app_conf)
    name = _single_ups(config, state_dir, nut_dir)
    guard_restart(config, state_dir=state_dir, allow_nut_unavailable=(stage in {"install","driver"}))
    if stage == "install":
        from .ups_setup import _has_nut
        if _has_nut():
            return "NUT уже установлен"
        run_checked(["apt-get", "install", "-y", "--no-install-recommends",
                     "nut-server", "nut-client"], timeout=240, runner=runner)
        if not _has_nut():
            raise UpsSetupError("APT завершился, но утилиты NUT не найдены")
        return "NUT установлен"

    if not shutil.which("upsc") or not shutil.which("upsd"):
        raise UpsSetupError("Сначала установите NUT")

    if stage == "server":
        if service_status(f"nut-driver@{name}.service", runner=runner) != "active":
            raise UpsSetupError("Сначала запустите NUT driver")
        run_checked(["systemctl", "start", "nut-server.service"], runner=runner)
        if not live_ol(name, runner=runner):
            raise UpsSetupError("NUT Server не подтвердил питание от сети")
        return "NUT Server работает"

    if stage == "driver":
        state = StateStore(state_dir / "ups_setup_driver.json").load()
        driver = state.get("driver")
        if not isinstance(driver, str) or driver not in driver_options():
            raise UpsSetupError("Сначала выберите установленный драйвер NUT")
        paths = {nut_dir / name for name in ("ups.conf","nut.conf","upsd.conf")}
        values = {path.name: _read(path) for path in paths}
        if _sections(values["ups.conf"]):
            existing = re.search(r"^\s*driver\s*=\s*([a-zA-Z0-9_-]+)", values["ups.conf"], re.M)
            if not existing or existing.group(1) != driver:
                raise UpsSetupError("Рабочая конфигурация драйвера отличается; ручной аудит")
        else:
            values["ups.conf"] = f"[{name}]\n    driver = {driver}\n    port = auto\n"
        if values["nut.conf"].strip() and re.search(r"^\s*MODE\s*=\s*(?!standalone)\w+", values["nut.conf"], re.M):
            raise UpsSetupError("NUT MODE уже настроен для другой топологии")
        if not values["nut.conf"].strip() or not re.search(r"^\s*MODE\s*=\s*standalone\b", values["nut.conf"], re.M):
            values["nut.conf"] = "MODE=standalone\n"
        if not re.search(r"^\s*LISTEN\s+", values["upsd.conf"], re.M):
            values["upsd.conf"] = "LISTEN 127.0.0.1 3493\n"
        elif not re.fullmatch(r"\s*LISTEN\s+127\.0\.0\.1\s+3493\s*", values["upsd.conf"].strip()):
            raise UpsSetupError("NUT Server использует другую сеть; конфигурация не меняется")
        previous_driver = service_status(f"nut-driver@{name}.service", runner=runner)
        restore = _backup_and_write({nut_dir / key: value for key,value in values.items()}, state_dir=state_dir)
        try:
            run_checked(["systemctl", "daemon-reload"], runner=runner)
            run_checked(["systemctl", "start", f"nut-driver@{name}.service"], runner=runner)
            run_checked(["systemctl", "start", "nut-server.service"], runner=runner)
            if not live_ol(name, runner=runner):
                raise UpsSetupError("Драйвер не подтвердил безопасное питание OL; проверьте USB и драйвер")
        except Exception:
            _restore_changes(restore)
            if previous_driver != "active":
                try:
                    run_checked(["systemctl", "stop", f"nut-driver@{name}.service"], runner=runner)
                except Exception:
                    pass
            try:
                run_checked(["systemctl", "restart", "nut-server.service"], runner=runner)
            except Exception:
                pass
            raise
        return f"NUT driver {driver} подключён"

    if not live_ol(name, runner=runner):
        raise UpsSetupError("UPS не подтвердил питание от сети (OL); изменения запрещены")

    if stage == "primary":
        if service_status("nut-monitor.service", runner=runner) == "active":
            raise UpsSetupError("Активный nut-monitor нельзя перенастраивать автоматически")
        users_path = nut_dir / "upsd.users"
        monitor_path = nut_dir / "upsmon.conf"
        existing_users, existing_mon = _read(users_path), _read(monitor_path)
        if re.search(r"^\s*\[dh_primary_user\]", existing_users, re.M):
            raise UpsSetupError("Учётная запись PRIMARY уже существует; проверьте конфигурацию вручную")
        if re.search(r"^\s*MONITOR\s+", existing_mon, re.M):
            raise UpsSetupError("NUT MONITOR уже задан; существующую топологию не перезаписываем")
        password = secrets.token_hex(24)
        users = existing_users.rstrip() + (
            f"\n\n[dh_primary_user]\n    password = {password}\n"
            "    upsmon primary\n    instcmds = ALL\n"
        )
        monitors = (
            f"MONITOR {name}@127.0.0.1 1 dh_primary_user {password} primary\n"
            "MINSUPPLIES 1\nPOLLFREQ 5\nPOLLFREQALERT 5\nDEADTIME 15\n"
            "HOSTSYNC 120\nFINALDELAY 5\nSHUTDOWNCMD \"/bin/true\"\n"
        )
        backups = {users_path: users, monitor_path: monitors}
        restore = _backup_and_write(backups, state_dir=state_dir)
        try:
            run_checked(["systemctl", "restart", "nut-server.service"], runner=runner)
            if not live_ol(name, runner=runner):
                raise UpsSetupError("После настройки PRIMARY UPS перестал отвечать")
            # Existing CLI atomic edit preserves all unrelated App settings.
            set_config(app_conf, [
                "ups_enabled=true", "ups_host=127.0.0.1", "ups_port=3493",
                f"ups_name={name}", "ups_command_username=dh_primary_user",
                "ups_command_password",
            ], prepare=True, hidden_values={("ups", "command_password"): password})
        except Exception:
            _restore_changes(restore)
            try:
                run_checked(["systemctl", "restart", "nut-server.service"], runner=runner)
            except Exception:
                pass
            raise
        selection = StateStore(state_dir / "ups_selection.json")
        existing = selection.load()
        if existing.get("selected_name") != name:
            selection.save({**existing, "selected_name": name})
        return "NUT PRIMARY подготовлен; требуется перезапуск агента"

    if stage == "monitor":
        if service_status("nut-monitor.service", runner=runner) == "active":
            return "NUT Monitor уже работает"
        if "primary" not in _read(nut_dir / "upsmon.conf").lower():
            raise UpsSetupError("Сначала настройте NUT PRIMARY")
        if 'SHUTDOWNCMD "/bin/true"' not in _read(nut_dir / "upsmon.conf"):
            raise UpsSetupError("Монитор запускается только в безопасном commissioning-режиме")
        try:
            run_checked(["systemctl", "enable", "--now", "nut-monitor.service"], runner=runner)
            if service_status("nut-monitor.service", runner=runner) != "active":
                raise UpsSetupError("NUT Monitor не запустился")
        except Exception:
            try:
                run_checked(["systemctl", "disable", "--now", "nut-monitor.service"], runner=runner)
            except Exception:
                pass
            raise
        return "NUT Monitor работает"

    # Stage activate changes the shutdown authority, never initiates shutdown.
    if service_status("nut-monitor.service", runner=runner) != "active":
        raise UpsSetupError("Для активации shutdown нужен работающий NUT Monitor")
    original = _read(nut_dir / "upsmon.conf")
    if 'SHUTDOWNCMD "/sbin/shutdown -h now"' in original:
        return "Shutdown PVE уже активирован"
    if original.count('SHUTDOWNCMD "/bin/true"') != 1:
        raise UpsSetupError("Неизвестная команда shutdown; требуется ручной аудит")
    if not live_ol(name, runner=runner):
        raise UpsSetupError("UPS уже не в безопасном состоянии")
    from .ups_policy_preflight import read_policy_preflight
    from .config import UpsConfig
    report = read_policy_preflight(UpsConfig(enabled=True,name=name))
    ignored = {"shutdown_enabled"}
    blocking = [check.key for check in report.checks if not check.ok and check.key not in ignored]
    if blocking:
        raise UpsSetupError("Preflight блокирует включение shutdown: " + ", ".join(blocking))
    restore = _backup_and_write({nut_dir / "upsmon.conf": original.replace(
        'SHUTDOWNCMD "/bin/true"', 'SHUTDOWNCMD "/sbin/shutdown -h now"'
    )}, state_dir=state_dir)
    try:
        run_checked(["systemctl", "restart", "nut-monitor.service"], runner=runner)
        if service_status("nut-monitor.service", runner=runner) != "active":
            raise UpsSetupError("NUT Monitor не подтвердил активацию")
    except Exception:
        _restore_changes(restore)
        try:
            run_checked(["systemctl", "restart", "nut-monitor.service"], runner=runner)
        except Exception:
            pass
        raise
    return "Shutdown PVE активирован"


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=VALID_STAGES)
    args = parser.parse_args(argv)
    state = StateStore(DEFAULT_STATE / "ups_setup_operation.json")
    lock = DEFAULT_STATE / "ups_setup.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            outcome = execute(args.stage)
            state.save({"stage": args.stage, "state": "success", "message": outcome})
            return 0
        except Exception as exc:
            # Never persist traceback, credentials or file contents in MQTT status.
            state.save({"stage": args.stage, "state": "error",
                        "message": f"{type(exc).__name__}: {str(exc)[:160]}"})
            return 1


if __name__ == "__main__":
    raise SystemExit(cli())
