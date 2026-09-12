from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .ups_policy import (
    PolicyApplyResult,
    PolicySafetyFacts,
    UpsPolicyDraft,
    policy_hash,
    validate_policy,
)


class PolicyApplyError(RuntimeError):
    """Raised when a managed NUT policy cannot be rendered or applied safely."""


@dataclass(frozen=True)
class ManagedNutPaths:
    upsmon: Path = Path("/etc/nut/upsmon.conf")
    upssched: Path = Path("/etc/nut/upssched.conf")
    ups_conf: Path = Path("/etc/nut/ups.conf")
    command_script: Path = Path(
        "/opt/digitalhouses/dh_pve_app/bin/dh-pve-ups-policy-cmd"
    )
    metadata: Path = Path("/var/lib/dh_pve_app/ups_policy_active.json")


@dataclass(frozen=True)
class ManagedPolicyTarget:
    upsmon_text: str
    upssched_text: str
    ups_conf_text: str


@dataclass(frozen=True)
class _FileSnapshot:
    existed: bool
    content: bytes
    mode: int | None


_OWNED_UPSMON_SINGLETONS = {"SHUTDOWNCMD", "POWERDOWNFLAG", "NOTIFYCMD"}
_FORBIDDEN_UPS_DIRECTIVES = {
    "ignorelb",
    "override.battery.runtime.low",
    "override.battery.charge.low",
}


def _line_key(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return ""
    return stripped.split(None, 1)[0].upper()


def _render_upsmon(existing: str) -> str:
    output: list[str] = []
    for line in existing.splitlines():
        stripped = line.strip()
        key = _line_key(line)
        if key in _OWNED_UPSMON_SINGLETONS:
            continue
        if key == "NOTIFYFLAG":
            parts = stripped.split()
            if len(parts) >= 2 and parts[1].upper() in {"ONBATT", "ONLINE"}:
                continue
        output.append(line)

    if not any(_line_key(line) == "MONITOR" for line in output):
        raise PolicyApplyError("В upsmon.conf не найден MONITOR для UPS.")

    while output and not output[-1].strip():
        output.pop()
    output.extend(
        [
            "",
            "# DigitalHouses managed UPS shutdown policy",
            'SHUTDOWNCMD "/sbin/shutdown -h now"',
            "POWERDOWNFLAG /etc/killpower",
            "NOTIFYCMD /usr/sbin/upssched",
            "NOTIFYFLAG ONBATT SYSLOG+EXEC",
            "NOTIFYFLAG ONLINE SYSLOG+EXEC",
        ]
    )
    return "\n".join(output) + "\n"


def _section_bounds(lines: list[str], section_name: str) -> tuple[int, int]:
    section_re = re.compile(r"^\s*\[([^]]+)\]\s*(?:#.*)?$")
    start: int | None = None
    end = len(lines)
    for index, line in enumerate(lines):
        match = section_re.match(line)
        if not match:
            continue
        current = match.group(1).strip()
        if start is None and current == section_name:
            start = index
            continue
        if start is not None:
            end = index
            break
    if start is None:
        raise PolicyApplyError(f"В ups.conf не найден выбранный UPS [{section_name}].")
    return start, end


def _render_ups_conf(existing: str, ups_name: str, restore_delay: int) -> str:
    lines = existing.splitlines()
    start, end = _section_bounds(lines, ups_name)
    body = lines[start + 1 : end]

    offdelay: int | None = None
    kept: list[str] = []
    for line in body:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            kept.append(line)
            continue
        key, value = stripped.split("=", 1)
        normalized = key.strip().casefold()
        raw_value = value.strip().strip('"').strip("'")
        if normalized in _FORBIDDEN_UPS_DIRECTIVES:
            raise PolicyApplyError(
                f"В [{ups_name}] найден несовместимый параметр {normalized}; "
                "аппаратный Low Battery должен оставаться нативным."
            )
        if normalized == "offdelay":
            try:
                offdelay = int(float(raw_value))
            except ValueError as exc:
                raise PolicyApplyError("Некорректный offdelay в ups.conf.") from exc
            continue
        if normalized == "ondelay":
            continue
        kept.append(line)

    safe_offdelay = max(60, offdelay if offdelay is not None else 60)
    while kept and not kept[-1].strip():
        kept.pop()
    kept.extend(
        [
            f"    offdelay = {safe_offdelay}",
            f"    ondelay = {restore_delay}",
        ]
    )

    rendered = lines[: start + 1] + kept + lines[end:]
    return "\n".join(rendered) + "\n"


def _render_upssched(delay_seconds: int, command_script_path: Path) -> str:
    return "\n".join(
        [
            "# DigitalHouses managed UPS shutdown schedule",
            f"CMDSCRIPT {command_script_path}",
            "PIPEFN /run/nut/upssched.pipe",
            "LOCKFN /run/nut/upssched.lock",
            f"AT ONBATT * START-TIMER dh-pve-ups-shutdown {delay_seconds}",
            "AT ONLINE * CANCEL-TIMER dh-pve-ups-shutdown",
            "",
        ]
    )


def render_managed_policy(
    draft: UpsPolicyDraft,
    upsmon_text: str,
    ups_conf_text: str,
    *,
    command_script_path: Path,
    ups_name: str = "ups",
) -> ManagedPolicyTarget:
    validation = validate_policy(draft)
    return ManagedPolicyTarget(
        upsmon_text=_render_upsmon(upsmon_text),
        upssched_text=_render_upssched(
            validation.on_battery_delay_seconds, command_script_path
        ),
        ups_conf_text=_render_ups_conf(
            ups_conf_text,
            ups_name,
            validation.power_restore_delay_seconds,
        ),
    )


def _snapshot(path: Path) -> _FileSnapshot:
    try:
        info = path.stat()
        return _FileSnapshot(
            existed=True,
            content=path.read_bytes(),
            mode=stat.S_IMODE(info.st_mode),
        )
    except FileNotFoundError:
        return _FileSnapshot(existed=False, content=b"", mode=None)
    except OSError as exc:
        raise PolicyApplyError(f"Не удалось прочитать {path}.") from exc


def _atomic_write(path: Path, content: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _restore(path: Path, snapshot: _FileSnapshot, default_mode: int) -> None:
    if snapshot.existed:
        _atomic_write(
            path,
            snapshot.content,
            snapshot.mode if snapshot.mode is not None else default_mode,
        )
    else:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _run(
    runner: Callable[..., subprocess.CompletedProcess[str]],
    command: list[str],
) -> subprocess.CompletedProcess[str]:
    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            timeout=15.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PolicyApplyError(f"Не удалось выполнить: {' '.join(command)}") from exc
    if result.returncode != 0:
        raise PolicyApplyError(f"Команда завершилась ошибкой: {' '.join(command)}")
    return result


def _service_state(
    runner: Callable[..., subprocess.CompletedProcess[str]],
    verb: str,
) -> str:
    try:
        result = runner(
            ["systemctl", verb, "nut-monitor.service"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    text = (result.stdout or "").strip().casefold()
    return text or "unknown"


def _validate_static_helper(path: Path) -> None:
    try:
        info = path.stat()
    except OSError as exc:
        raise PolicyApplyError(
            f"Статический helper политики UPS недоступен: {path}."
        ) from exc
    if not path.is_file() or not os.access(path, os.X_OK):
        raise PolicyApplyError(
            f"Статический helper политики UPS не является исполняемым: {path}."
        )
    mode = stat.S_IMODE(info.st_mode)
    if mode & 0o022:
        raise PolicyApplyError(
            f"Статический helper политики UPS доступен на запись группе/остальным: {path}."
        )


class UpsPolicyApplier:
    """Transactional writer for the approved DigitalHouses NUT policy surface."""

    def __init__(
        self,
        *,
        paths: ManagedNutPaths,
        ups_name: str,
        runner: Callable[..., subprocess.CompletedProcess[str]],
        effective_restart_delay_reader: Callable[[], int],
    ) -> None:
        self.paths = paths
        self.ups_name = ups_name
        self.runner = runner
        self.effective_restart_delay_reader = effective_restart_delay_reader

    def _rollback(
        self,
        snapshots: dict[Path, _FileSnapshot],
        *,
        monitor_active_before: str,
        monitor_enabled_before: str,
    ) -> None:
        modes = {
            self.paths.upsmon: 0o640,
            self.paths.upssched: 0o640,
            self.paths.ups_conf: 0o640,
            self.paths.metadata: 0o600,
        }
        for path, snapshot in snapshots.items():
            try:
                _restore(path, snapshot, modes[path])
            except Exception:
                pass

        try:
            self.runner(
                ["systemctl", "restart", f"nut-driver@{self.ups_name}.service"],
                capture_output=True,
                text=True,
                timeout=15.0,
                check=False,
            )
        except Exception:
            pass
        try:
            if monitor_active_before == "active":
                command = ["systemctl", "restart", "nut-monitor.service"]
            else:
                command = ["systemctl", "stop", "nut-monitor.service"]
            self.runner(
                command,
                capture_output=True,
                text=True,
                timeout=15.0,
                check=False,
            )
            if monitor_enabled_before not in {"enabled", "enabled-runtime"}:
                self.runner(
                    ["systemctl", "disable", "nut-monitor.service"],
                    capture_output=True,
                    text=True,
                    timeout=15.0,
                    check=False,
                )
        except Exception:
            pass

    def apply(
        self,
        draft: UpsPolicyDraft,
        facts: PolicySafetyFacts,
    ) -> PolicyApplyResult:
        try:
            validate_policy(draft, facts)
            _validate_static_helper(self.paths.command_script)
            snapshots = {
                path: _snapshot(path)
                for path in (
                    self.paths.upsmon,
                    self.paths.upssched,
                    self.paths.ups_conf,
                    self.paths.metadata,
                )
            }
            upsmon_text = snapshots[self.paths.upsmon].content.decode("utf-8")
            ups_conf_text = snapshots[self.paths.ups_conf].content.decode("utf-8")
            target = render_managed_policy(
                draft,
                upsmon_text,
                ups_conf_text,
                command_script_path=self.paths.command_script,
                ups_name=self.ups_name,
            )
            monitor_active_before = _service_state(self.runner, "is-active")
            monitor_enabled_before = _service_state(self.runner, "is-enabled")
        except Exception as exc:
            return PolicyApplyResult(False, f"Не удалось подготовить политику UPS: {exc}")

        try:
            _atomic_write(self.paths.upsmon, target.upsmon_text.encode("utf-8"), 0o640)
            _atomic_write(self.paths.upssched, target.upssched_text.encode("utf-8"), 0o640)
            _atomic_write(self.paths.ups_conf, target.ups_conf_text.encode("utf-8"), 0o640)

            if self.paths.upsmon.read_text(encoding="utf-8") != target.upsmon_text:
                raise PolicyApplyError("Проверка upsmon.conf после записи не прошла.")
            if self.paths.upssched.read_text(encoding="utf-8") != target.upssched_text:
                raise PolicyApplyError("Проверка upssched.conf после записи не прошла.")
            if self.paths.ups_conf.read_text(encoding="utf-8") != target.ups_conf_text:
                raise PolicyApplyError("Проверка ups.conf после записи не прошла.")

            _run(
                self.runner,
                ["systemctl", "restart", f"nut-driver@{self.ups_name}.service"],
            )

            effective_delay = int(self.effective_restart_delay_reader())
            if effective_delay != draft.power_restore_delay_seconds:
                raise PolicyApplyError(
                    "UPS не подтвердил заданную задержку восстановления питания."
                )

            if monitor_active_before == "active":
                _run(self.runner, ["systemctl", "restart", "nut-monitor.service"])
            else:
                _run(self.runner, ["systemctl", "enable", "--now", "nut-monitor.service"])

            metadata = {
                "policy": draft.as_dict(),
                "policy_hash": policy_hash(draft),
                "guest_shutdown_budget_seconds": facts.guest_shutdown_budget_seconds,
                "hardware_low_battery": "native",
            }
            _atomic_write(
                self.paths.metadata,
                (json.dumps(metadata, ensure_ascii=False, sort_keys=True) + "\n").encode(
                    "utf-8"
                ),
                0o600,
            )
            return PolicyApplyResult(True, "Политика UPS применена и проверена.")
        except Exception as exc:
            self._rollback(
                snapshots,
                monitor_active_before=monitor_active_before,
                monitor_enabled_before=monitor_enabled_before,
            )
            return PolicyApplyResult(False, f"Применение политики UPS отменено: {exc}")
