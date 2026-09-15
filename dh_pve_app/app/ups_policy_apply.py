from __future__ import annotations

import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
import time
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
    upsd_users: Path = Path("/etc/nut/upsd.users")
    app_config: Path = Path("/etc/dh_pve_app/dh_pve_app.conf")
    command_script: Path = Path(
        "/opt/digitalhouses/dh_pve_app/bin/dh-pve-ups-policy-cmd"
    )
    metadata: Path = Path("/var/lib/dh_pve_app/ups_policy_active.json")


@dataclass(frozen=True)
class ManagedPolicyTarget:
    upsmon_text: str
    upssched_text: str
    ups_conf_text: str
    upsd_users_text: str = ""
    app_config_text: str = ""


@dataclass(frozen=True)
class _FileSnapshot:
    existed: bool
    content: bytes
    mode: int | None
    uid: int | None
    gid: int | None


_OWNED_UPSMON_SINGLETONS = {"SHUTDOWNCMD", "POWERDOWNFLAG", "NOTIFYCMD"}
_FORBIDDEN_UPS_DIRECTIVES = {
    "ignorelb",
    "override.battery.runtime.low",
    "override.battery.charge.low",
}
_MANAGED_NUT_USER = "dh_primary_user"
_SECTION_RE = re.compile(r"^\s*\[([^]]+)\]\s*(?:#.*)?$")


def _line_key(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return ""
    return stripped.split(None, 1)[0].upper()


def _monitor_ups_name(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    parts = stripped.split()
    if len(parts) < 2 or parts[0].upper() != "MONITOR":
        return None
    return parts[1].split("@", 1)[0]


def _render_upsmon(
    existing: str,
    *,
    ups_name: str | None = None,
    managed_password: str | None = None,
) -> str:
    output: list[str] = []
    selected_monitor_seen = False
    for line in existing.splitlines():
        stripped = line.strip()
        key = _line_key(line)
        if key in _OWNED_UPSMON_SINGLETONS:
            continue
        if key == "NOTIFYFLAG":
            parts = stripped.split()
            if len(parts) >= 2 and parts[1].upper() in {"ONBATT", "ONLINE"}:
                continue
        if (
            key == "MONITOR"
            and ups_name is not None
            and managed_password is not None
            and _monitor_ups_name(line) == ups_name
        ):
            if selected_monitor_seen:
                raise PolicyApplyError(
                    f"В upsmon.conf найдено несколько MONITOR для UPS {ups_name}."
                )
            output.append(
                f"MONITOR {ups_name}@127.0.0.1 1 {_MANAGED_NUT_USER} "
                f"{managed_password} primary"
            )
            selected_monitor_seen = True
            continue
        output.append(line)

    if not any(_line_key(line) == "MONITOR" for line in output):
        raise PolicyApplyError("В upsmon.conf не найден MONITOR для UPS.")
    if ups_name is not None and managed_password is not None and not selected_monitor_seen:
        raise PolicyApplyError(
            f"В upsmon.conf не найден MONITOR для выбранного UPS {ups_name}."
        )

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
    start: int | None = None
    end = len(lines)
    for index, line in enumerate(lines):
        match = _SECTION_RE.match(line)
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
        if not stripped or stripped.startswith("#"):
            kept.append(line)
            continue

        key_text = (
            stripped.split("=", 1)[0].strip()
            if "=" in stripped
            else stripped.split(None, 1)[0].strip()
        )
        normalized = key_text.casefold()
        if normalized in _FORBIDDEN_UPS_DIRECTIVES:
            raise PolicyApplyError(
                f"В [{ups_name}] найден несовместимый параметр {normalized}; "
                "аппаратный Low Battery должен оставаться нативным."
            )

        if "=" not in stripped:
            kept.append(line)
            continue

        _, value = stripped.split("=", 1)
        raw_value = value.strip().strip('"').strip("'")
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


def _find_section_ranges(lines: list[str], section_name: str) -> list[tuple[int, int]]:
    starts: list[int] = []
    for index, line in enumerate(lines):
        match = _SECTION_RE.match(line)
        if match and match.group(1).strip() == section_name:
            starts.append(index)
    ranges: list[tuple[int, int]] = []
    for start in starts:
        end = len(lines)
        for index in range(start + 1, len(lines)):
            if _SECTION_RE.match(lines[index]):
                end = index
                break
        ranges.append((start, end))
    return ranges


def _extract_managed_password(existing: str) -> str | None:
    lines = existing.splitlines()
    ranges = _find_section_ranges(lines, _MANAGED_NUT_USER)
    if len(ranges) > 1:
        raise PolicyApplyError(
            f"В upsd.users найдено несколько секций [{_MANAGED_NUT_USER}]."
        )
    if not ranges:
        return None
    start, end = ranges[0]
    for raw in lines[start + 1 : end]:
        stripped = raw.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        if "=" in stripped:
            key, value = stripped.split("=", 1)
        else:
            parts = stripped.split(None, 1)
            if len(parts) != 2:
                continue
            key, value = parts
        if key.strip().casefold() == "password":
            password = value.strip().strip('"').strip("'")
            return password or None
    return None


def _render_upsd_users(existing: str, managed_password: str) -> str:
    lines = existing.splitlines()
    ranges = _find_section_ranges(lines, _MANAGED_NUT_USER)
    if len(ranges) > 1:
        raise PolicyApplyError(
            f"В upsd.users найдено несколько секций [{_MANAGED_NUT_USER}]."
        )

    managed = [
        f"[{_MANAGED_NUT_USER}]",
        f"    password = {managed_password}",
        "    upsmon primary",
        "    instcmds = ALL",
    ]

    if ranges:
        start, end = ranges[0]
        rendered = lines[:start] + managed + lines[end:]
    else:
        rendered = list(lines)
        while rendered and not rendered[-1].strip():
            rendered.pop()
        if rendered:
            rendered.append("")
        rendered.extend(managed)

    return "\n".join(rendered).rstrip() + "\n"


def _render_app_config(existing: str, ups_name: str, managed_password: str) -> str:
    lines = existing.splitlines()
    ranges = _find_section_ranges(lines, "ups")
    if len(ranges) > 1:
        raise PolicyApplyError("В dh_pve_app.conf найдено несколько секций [ups].")

    managed_values = {
        "enabled": "true",
        "name": ups_name,
        "command_username": _MANAGED_NUT_USER,
        "command_password": managed_password,
    }

    if ranges:
        start, end = ranges[0]
        body = lines[start + 1 : end]
        rendered_body: list[str] = []
        seen: set[str] = set()
        for line in body:
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", ";")) or "=" not in line:
                rendered_body.append(line)
                continue
            key = line.split("=", 1)[0].strip().casefold()
            if key in managed_values:
                rendered_body.append(f"{key} = {managed_values[key]}")
                seen.add(key)
            else:
                rendered_body.append(line)
        for key, value in managed_values.items():
            if key not in seen:
                rendered_body.append(f"{key} = {value}")
        rendered = lines[: start + 1] + rendered_body + lines[end:]
    else:
        rendered = list(lines)
        while rendered and not rendered[-1].strip():
            rendered.pop()
        if rendered:
            rendered.append("")
        rendered.extend(
            [
                "[ups]",
                "enabled = true",
                f"name = {ups_name}",
                f"command_username = {_MANAGED_NUT_USER}",
                f"command_password = {managed_password}",
            ]
        )

    return "\n".join(rendered).rstrip() + "\n"


def render_managed_policy(
    draft: UpsPolicyDraft,
    upsmon_text: str,
    ups_conf_text: str,
    *,
    command_script_path: Path,
    ups_name: str = "ups",
    upsd_users_text: str | None = None,
    app_config_text: str | None = None,
    managed_password: str | None = None,
) -> ManagedPolicyTarget:
    identity_args = (upsd_users_text, app_config_text, managed_password)
    identity_requested = any(value is not None for value in identity_args)
    if identity_requested and not all(value is not None for value in identity_args):
        raise PolicyApplyError(
            "Для managed NUT identity требуются upsd.users, App config и password."
        )

    validation = validate_policy(draft)
    return ManagedPolicyTarget(
        upsmon_text=_render_upsmon(
            upsmon_text,
            ups_name=ups_name if identity_requested else None,
            managed_password=managed_password if identity_requested else None,
        ),
        upssched_text=_render_upssched(
            validation.on_battery_delay_seconds, command_script_path
        ),
        ups_conf_text=_render_ups_conf(
            ups_conf_text,
            ups_name,
            validation.power_restore_delay_seconds,
        ),
        upsd_users_text=(
            _render_upsd_users(upsd_users_text or "", managed_password or "")
            if identity_requested
            else ""
        ),
        app_config_text=(
            _render_app_config(app_config_text or "", ups_name, managed_password or "")
            if identity_requested
            else ""
        ),
    )


def _snapshot(path: Path) -> _FileSnapshot:
    try:
        info = path.stat()
        return _FileSnapshot(
            existed=True,
            content=path.read_bytes(),
            mode=stat.S_IMODE(info.st_mode),
            uid=info.st_uid,
            gid=info.st_gid,
        )
    except FileNotFoundError:
        return _FileSnapshot(
            existed=False,
            content=b"",
            mode=None,
            uid=None,
            gid=None,
        )
    except OSError as exc:
        raise PolicyApplyError(f"Не удалось прочитать {path}.") from exc


def _atomic_write(
    path: Path,
    content: bytes,
    mode: int,
    *,
    uid: int | None = None,
    gid: int | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    parent_info = path.parent.stat()
    target_uid = parent_info.st_uid if uid is None else uid
    target_gid = parent_info.st_gid if gid is None else gid

    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.chown(temp, target_uid, target_gid)
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
            uid=snapshot.uid,
            gid=snapshot.gid,
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
    service: str = "nut-monitor.service",
) -> str:
    try:
        result = runner(
            ["systemctl", verb, service],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    text = (result.stdout or "").strip().casefold()
    return text or "unknown"


def _validate_static_helper(
    path: Path,
    *,
    expected_uid: int,
    expected_gid: int,
) -> None:
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
    if info.st_uid != expected_uid or info.st_gid != expected_gid:
        raise PolicyApplyError(
            "Статический helper политики UPS имеет недоверенного владельца: "
            f"uid={info.st_uid}, gid={info.st_gid}; "
            f"ожидается uid={expected_uid}, gid={expected_gid}."
        )
    mode = stat.S_IMODE(info.st_mode)
    if mode & 0o022:
        raise PolicyApplyError(
            f"Статический helper политики UPS доступен на запись группе/остальным: {path}."
        )


def _redact_secret(text: str, secret: str) -> str:
    return text.replace(secret, "***") if secret else text


class UpsPolicyApplier:
    """Transactional writer used only by explicit UPS commissioning."""

    def __init__(
        self,
        *,
        paths: ManagedNutPaths,
        ups_name: str,
        runner: Callable[..., subprocess.CompletedProcess[str]],
        effective_restart_delay_reader: Callable[[], int],
        helper_expected_uid: int = 0,
        helper_expected_gid: int = 0,
        effective_delay_timeout_seconds: float = 10.0,
        effective_delay_retry_interval_seconds: float = 0.5,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        secret_generator: Callable[[], str] | None = None,
        credential_verifier: Callable[[str, str], None] | None = None,
    ) -> None:
        self.paths = paths
        self.ups_name = ups_name
        self.runner = runner
        self.effective_restart_delay_reader = effective_restart_delay_reader
        self.helper_expected_uid = helper_expected_uid
        self.helper_expected_gid = helper_expected_gid
        self.effective_delay_timeout_seconds = effective_delay_timeout_seconds
        self.effective_delay_retry_interval_seconds = effective_delay_retry_interval_seconds
        self.monotonic = monotonic
        self.sleeper = sleeper
        self.secret_generator = secret_generator or (lambda: secrets.token_urlsafe(32))
        self.credential_verifier = credential_verifier

    def _wait_for_effective_restart_delay(self, expected_delay: int) -> None:
        deadline = self.monotonic() + self.effective_delay_timeout_seconds
        while True:
            try:
                effective_delay = self.effective_restart_delay_reader()
            except Exception:
                effective_delay = None

            if effective_delay == expected_delay:
                return

            now = self.monotonic()
            if now >= deadline:
                raise PolicyApplyError(
                    "UPS не подтвердил заданную задержку восстановления питания."
                )

            self.sleeper(
                min(self.effective_delay_retry_interval_seconds, deadline - now)
            )

    def _rollback(
        self,
        snapshots: dict[Path, _FileSnapshot],
        *,
        monitor_active_before: str,
        monitor_enabled_before: str,
        server_active_before: str = "unknown",
        server_enabled_before: str = "unknown",
    ) -> None:
        modes = {
            self.paths.upsmon: 0o640,
            self.paths.upssched: 0o640,
            self.paths.ups_conf: 0o640,
            self.paths.upsd_users: 0o640,
            self.paths.app_config: 0o600,
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
            server_command = (
                ["systemctl", "restart", "nut-server.service"]
                if server_active_before == "active"
                else ["systemctl", "stop", "nut-server.service"]
            )
            self.runner(
                server_command,
                capture_output=True,
                text=True,
                timeout=15.0,
                check=False,
            )
            if server_enabled_before not in {"enabled", "enabled-runtime"}:
                self.runner(
                    ["systemctl", "disable", "nut-server.service"],
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
        managed_password = ""
        identity_mode = self.paths.app_config.exists() or self.paths.upsd_users.exists()
        try:
            validate_policy(draft, facts)
            _validate_static_helper(
                self.paths.command_script,
                expected_uid=self.helper_expected_uid,
                expected_gid=self.helper_expected_gid,
            )
            mutable_paths = [
                self.paths.upsmon,
                self.paths.upssched,
                self.paths.ups_conf,
            ]
            if identity_mode:
                mutable_paths.extend((self.paths.upsd_users, self.paths.app_config))
            mutable_paths.append(self.paths.metadata)
            snapshots = {path: _snapshot(path) for path in mutable_paths}

            upsmon_text = snapshots[self.paths.upsmon].content.decode("utf-8")
            ups_conf_text = snapshots[self.paths.ups_conf].content.decode("utf-8")
            render_kwargs: dict[str, str] = {}
            if identity_mode:
                if not snapshots[self.paths.app_config].existed:
                    raise PolicyApplyError("App config отсутствует; commissioning остановлен.")
                upsd_users_text = snapshots[self.paths.upsd_users].content.decode("utf-8")
                app_config_text = snapshots[self.paths.app_config].content.decode("utf-8")
                managed_password = _extract_managed_password(upsd_users_text) or self.secret_generator()
                if not managed_password or any(char.isspace() for char in managed_password):
                    raise PolicyApplyError("Не удалось получить безопасный password для NUT user.")
                render_kwargs = {
                    "upsd_users_text": upsd_users_text,
                    "app_config_text": app_config_text,
                    "managed_password": managed_password,
                }

            target = render_managed_policy(
                draft,
                upsmon_text,
                ups_conf_text,
                command_script_path=self.paths.command_script,
                ups_name=self.ups_name,
                **render_kwargs,
            )
            monitor_active_before = _service_state(self.runner, "is-active")
            monitor_enabled_before = _service_state(self.runner, "is-enabled")
            server_active_before = _service_state(
                self.runner, "is-active", "nut-server.service"
            )
            server_enabled_before = _service_state(
                self.runner, "is-enabled", "nut-server.service"
            )
        except Exception as exc:
            detail = _redact_secret(str(exc), managed_password)
            return PolicyApplyResult(False, f"Не удалось подготовить политику UPS: {detail}")

        try:
            _atomic_write(self.paths.upsmon, target.upsmon_text.encode("utf-8"), 0o640)
            _atomic_write(self.paths.upssched, target.upssched_text.encode("utf-8"), 0o640)
            _atomic_write(self.paths.ups_conf, target.ups_conf_text.encode("utf-8"), 0o640)
            if identity_mode:
                _atomic_write(
                    self.paths.upsd_users,
                    target.upsd_users_text.encode("utf-8"),
                    0o640,
                )
                _atomic_write(
                    self.paths.app_config,
                    target.app_config_text.encode("utf-8"),
                    0o600,
                )

            if self.paths.upsmon.read_text(encoding="utf-8") != target.upsmon_text:
                raise PolicyApplyError("Проверка upsmon.conf после записи не прошла.")
            if self.paths.upssched.read_text(encoding="utf-8") != target.upssched_text:
                raise PolicyApplyError("Проверка upssched.conf после записи не прошла.")
            if self.paths.ups_conf.read_text(encoding="utf-8") != target.ups_conf_text:
                raise PolicyApplyError("Проверка ups.conf после записи не прошла.")
            if identity_mode:
                if self.paths.upsd_users.read_text(encoding="utf-8") != target.upsd_users_text:
                    raise PolicyApplyError("Проверка upsd.users после записи не прошла.")
                if self.paths.app_config.read_text(encoding="utf-8") != target.app_config_text:
                    raise PolicyApplyError("Проверка App config после записи не прошла.")

            _run(
                self.runner,
                ["systemctl", "restart", f"nut-driver@{self.ups_name}.service"],
            )
            if identity_mode:
                _run(self.runner, ["systemctl", "restart", "nut-server.service"])
                if self.credential_verifier is not None:
                    self.credential_verifier(_MANAGED_NUT_USER, managed_password)

            self._wait_for_effective_restart_delay(
                draft.power_restore_delay_seconds
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
                server_active_before=server_active_before,
                server_enabled_before=server_enabled_before,
            )
            detail = _redact_secret(str(exc), managed_password)
            return PolicyApplyResult(False, f"Применение политики UPS отменено: {detail}")
