from __future__ import annotations

import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import UpsConfig
from .ups_legacy_timer import legacy_timer_present
from .ups_nut import read_ups
from .ups_policy import PolicySafetyFacts
from .ups_policy_host import read_policy_safety_facts
from .ups_shutdown_policy import UpsShutdownPolicy, read_shutdown_policy


_FORBIDDEN_LB_DIRECTIVES = {
    "ignorelb",
    "override.battery.runtime.low",
    "override.battery.charge.low",
}
_MANAGED_NUT_USER = "dh_primary_user"
_SECTION_RE = re.compile(r"^\s*\[([^]]+)\]\s*(?:#.*)?$")


@dataclass(frozen=True)
class PreflightCheck:
    key: str
    ok: bool
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {"key": self.key, "ok": self.ok, "detail": self.detail}


@dataclass(frozen=True)
class UpsPolicyPreflight:
    state: str
    ready: bool
    checks: tuple[PreflightCheck, ...]
    guest_shutdown_budget_seconds: int | None

    def as_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "ready": self.ready,
            "guest_shutdown_budget_seconds": self.guest_shutdown_budget_seconds,
            "checks": [check.as_dict() for check in self.checks],
        }


def _service_active(
    runner: Callable[..., subprocess.CompletedProcess[str]],
    service: str,
) -> tuple[bool, str]:
    try:
        result = runner(
            ["systemctl", "is-active", service],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Не удалось прочитать состояние {service}: {type(exc).__name__}."
    state = (result.stdout or "").strip().casefold() or "unknown"
    return state == "active", f"{service}: {state}."


def _selected_ups_lines(text: str, ups_name: str) -> list[str] | None:
    selected: list[str] | None = None
    for raw in text.splitlines():
        match = _SECTION_RE.match(raw)
        if match:
            if match.group(1).strip() == ups_name:
                selected = []
            elif selected is not None:
                break
            continue
        if selected is not None:
            selected.append(raw)
    return selected


def _named_sections(text: str, section_name: str) -> list[list[str]]:
    sections: list[list[str]] = []
    current: list[str] | None = None
    for raw in text.splitlines():
        match = _SECTION_RE.match(raw)
        if match:
            if current is not None:
                sections.append(current)
                current = None
            if match.group(1).strip() == section_name:
                current = []
            continue
        if current is not None:
            current.append(raw)
    if current is not None:
        sections.append(current)
    return sections


def _directive_value(lines: list[str], key: str) -> str | None:
    wanted = key.casefold()
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        if "#" in stripped:
            stripped = stripped.split("#", 1)[0].strip()
        if not stripped:
            continue
        if "=" in stripped:
            current_key, value = stripped.split("=", 1)
        else:
            parts = stripped.split(None, 1)
            if len(parts) != 2:
                continue
            current_key, value = parts
        if current_key.strip().casefold() == wanted:
            return value.strip().strip('"').strip("'")
    return None


def _identity_checks(
    *,
    config: UpsConfig,
    upsd_users_path: Path,
    upsmon_path: Path,
    app_config_path: Path,
) -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []

    try:
        users_text = upsd_users_path.read_text(encoding="utf-8")
    except OSError as exc:
        checks.extend(
            (
                PreflightCheck(
                    "nut_primary_user",
                    False,
                    f"Не удалось прочитать {upsd_users_path}: {type(exc).__name__}.",
                ),
                PreflightCheck("nut_primary_role", False, "NUT PRIMARY user не проверен."),
                PreflightCheck("nut_instcmds_all", False, "NUT command ACL не проверен."),
            )
        )
        user_password = None
    else:
        sections = _named_sections(users_text, _MANAGED_NUT_USER)
        user_ok = len(sections) == 1
        checks.append(
            PreflightCheck(
                "nut_primary_user",
                user_ok,
                (
                    f"NUT user {_MANAGED_NUT_USER} настроен."
                    if user_ok
                    else (
                        f"NUT user {_MANAGED_NUT_USER} отсутствует."
                        if not sections
                        else f"NUT user {_MANAGED_NUT_USER} определен несколько раз."
                    )
                ),
            )
        )
        user_lines = sections[0] if user_ok else []
        role = (_directive_value(user_lines, "upsmon") or "").casefold()
        checks.append(
            PreflightCheck(
                "nut_primary_role",
                user_ok and role == "primary",
                (
                    f"{_MANAGED_NUT_USER}: upsmon primary."
                    if user_ok and role == "primary"
                    else f"{_MANAGED_NUT_USER}: ожидается upsmon primary."
                ),
            )
        )
        instcmds = (_directive_value(user_lines, "instcmds") or "").casefold()
        checks.append(
            PreflightCheck(
                "nut_instcmds_all",
                user_ok and instcmds == "all",
                (
                    f"{_MANAGED_NUT_USER}: instcmds = ALL."
                    if user_ok and instcmds == "all"
                    else f"{_MANAGED_NUT_USER}: ожидается instcmds = ALL."
                ),
            )
        )
        user_password = _directive_value(user_lines, "password") if user_ok else None

    monitor_user: str | None = None
    monitor_password: str | None = None
    monitor_role: str | None = None
    try:
        upsmon_text = upsmon_path.read_text(encoding="utf-8")
    except OSError as exc:
        monitor_detail = f"Не удалось прочитать {upsmon_path}: {type(exc).__name__}."
        monitor_ok = False
    else:
        monitor_lines: list[list[str]] = []
        for raw in upsmon_text.splitlines():
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            if len(parts) >= 6 and parts[0].upper() == "MONITOR":
                if parts[1].split("@", 1)[0] == config.name:
                    monitor_lines.append(parts)
        if len(monitor_lines) == 1:
            parts = monitor_lines[0]
            monitor_user = parts[3]
            monitor_password = parts[4]
            monitor_role = parts[5].casefold()
            monitor_ok = (
                monitor_user == _MANAGED_NUT_USER and monitor_role == "primary"
            )
            monitor_detail = (
                f"MONITOR {config.name} использует {_MANAGED_NUT_USER} primary."
                if monitor_ok
                else f"MONITOR {config.name} должен использовать {_MANAGED_NUT_USER} primary."
            )
        else:
            monitor_ok = False
            monitor_detail = (
                f"Для UPS {config.name} ожидается ровно один MONITOR; найдено {len(monitor_lines)}."
            )
    checks.append(PreflightCheck("monitor_identity", monitor_ok, monitor_detail))

    app_user: str | None = None
    app_password: str | None = None
    try:
        app_text = app_config_path.read_text(encoding="utf-8")
    except OSError as exc:
        app_ok = False
        app_detail = f"Не удалось прочитать {app_config_path}: {type(exc).__name__}."
    else:
        app_sections = _named_sections(app_text, "ups")
        if len(app_sections) == 1:
            app_user = _directive_value(app_sections[0], "command_username")
            app_password = _directive_value(app_sections[0], "command_password")
            app_ok = app_user == _MANAGED_NUT_USER
            app_detail = (
                f"DigitalHouses PVE Agent использует {_MANAGED_NUT_USER}."
                if app_ok
                else f"DigitalHouses PVE Agent должен использовать {_MANAGED_NUT_USER}."
            )
        else:
            app_ok = False
            app_detail = (
                f"В App config ожидается ровно одна секция [ups]; найдено {len(app_sections)}."
            )
    checks.append(PreflightCheck("app_command_identity", app_ok, app_detail))

    credentials_ok = bool(
        user_password
        and monitor_password
        and app_password
        and user_password == monitor_password == app_password
    )
    checks.append(
        PreflightCheck(
            "credentials_consistent",
            credentials_ok,
            (
                "NUT credentials синхронизированы между upsd.users, upsmon и App."
                if credentials_ok
                else "NUT credentials не заданы или не совпадают между upsd.users, upsmon и App."
            ),
        )
    )
    return checks


def _hardware_lb_check(path: Path, ups_name: str) -> tuple[bool, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"Не удалось прочитать {path}: {type(exc).__name__}."
    lines = _selected_ups_lines(text, ups_name)
    if lines is None:
        return False, f"В {path} не найден выбранный UPS [{ups_name}]."

    found: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "#" in stripped:
            stripped = stripped.split("#", 1)[0].strip()
        if not stripped:
            continue
        key = (
            stripped.split("=", 1)[0].strip()
            if "=" in stripped
            else stripped.split(None, 1)[0].strip()
        ).casefold()
        if key in _FORBIDDEN_LB_DIRECTIVES:
            found.append(key)

    if found:
        values = ", ".join(sorted(set(found)))
        return False, f"Найдены запрещенные переопределения Low Battery: {values}."
    return True, "Hardware Low Battery остается нативным."


def _legacy_timer_check(path: Path) -> tuple[bool, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return True, "Legacy DH ONBATT timer отсутствует."
    except OSError as exc:
        return False, f"Не удалось прочитать {path}: {type(exc).__name__}."
    if legacy_timer_present(text):
        return False, "Legacy DH ONBATT upssched timer еще активен и должен быть retired."
    return True, "Legacy DH ONBATT upssched timer retired."


def _helper_check(
    path: Path,
    *,
    expected_uid: int,
    expected_gid: int,
) -> tuple[bool, str]:
    try:
        info = path.stat()
    except OSError as exc:
        return False, f"Helper недоступен: {path}: {type(exc).__name__}."
    mode = stat.S_IMODE(info.st_mode)
    if not path.is_file():
        return False, f"Helper не является обычным файлом: {path}."
    if mode & 0o111 == 0:
        return False, f"Helper не исполняемый: {path}."
    if info.st_uid != expected_uid or info.st_gid != expected_gid:
        return (
            False,
            "Helper имеет недоверенного владельца: "
            f"uid={info.st_uid}, gid={info.st_gid}; "
            f"ожидается uid={expected_uid}, gid={expected_gid}.",
        )
    if mode & 0o022:
        return False, f"Helper доступен на запись группе/остальным: {path}."
    return True, (
        f"Helper безопасен: {path}, uid={info.st_uid}, gid={info.st_gid}, "
        f"mode {mode:04o}."
    )


def read_policy_preflight(
    config: UpsConfig,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ups_reader: Callable[[UpsConfig], object] = read_ups,
    shutdown_policy_reader: Callable[[], UpsShutdownPolicy] = read_shutdown_policy,
    facts_reader: Callable[[UpsConfig], PolicySafetyFacts] = read_policy_safety_facts,
    ups_conf_path: Path = Path("/etc/nut/ups.conf"),
    upsd_users_path: Path = Path("/etc/nut/upsd.users"),
    upsmon_path: Path = Path("/etc/nut/upsmon.conf"),
    upssched_path: Path = Path("/etc/nut/upssched.conf"),
    app_config_path: Path = Path("/etc/digitalhouses_pve_agent/digitalhouses_pve_agent.conf"),
    helper_path: Path = Path(
        "/opt/digitalhouses/digitalhouses_pve_agent/bin/digitalhouses-pve-agent-ups-policy-cmd"
    ),
    helper_expected_uid: int = 0,
    helper_expected_gid: int = 0,
    killpower_path: Path = Path("/etc/killpower"),
) -> UpsPolicyPreflight:
    checks: list[PreflightCheck] = []

    try:
        ups_reader(config)
        checks.append(PreflightCheck("ups_available", True, "Выбранный UPS доступен через NUT."))
    except Exception as exc:
        checks.append(
            PreflightCheck(
                "ups_available",
                False,
                f"UPS недоступен через NUT: {type(exc).__name__}: {exc}",
            )
        )

    driver_ok, driver_detail = _service_active(
        runner, f"nut-driver@{config.name}.service"
    )
    checks.append(PreflightCheck("nut_driver_active", driver_ok, driver_detail))
    server_ok, server_detail = _service_active(runner, "nut-server.service")
    checks.append(PreflightCheck("nut_server_active", server_ok, server_detail))

    checks.extend(
        _identity_checks(
            config=config,
            upsd_users_path=upsd_users_path,
            upsmon_path=upsmon_path,
            app_config_path=app_config_path,
        )
    )

    policy: UpsShutdownPolicy | None
    try:
        policy = shutdown_policy_reader()
    except Exception as exc:
        policy = None
        checks.append(
            PreflightCheck(
                "shutdown_policy_readable",
                False,
                f"Не удалось прочитать upsmon policy: {type(exc).__name__}: {exc}",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                "shutdown_policy_readable",
                True,
                "upsmon policy прочитана.",
            )
        )
        checks.append(
            PreflightCheck(
                "primary_role",
                policy.role == "primary",
                f"Роль NUT upsmon: {policy.role}.",
            )
        )
        checks.append(
            PreflightCheck(
                "monitor_active",
                policy.nut_monitor == "active",
                f"nut-monitor: {policy.nut_monitor}; для native LB ожидается active.",
            )
        )
        checks.append(
            PreflightCheck(
                "shutdown_enabled",
                policy.shutdown_enabled,
                f"SHUTDOWNCMD: {policy.shutdown_command or 'не задан'}.",
            )
        )

    legacy_ok, legacy_detail = _legacy_timer_check(upssched_path)
    checks.append(PreflightCheck("legacy_upssched_retired", legacy_ok, legacy_detail))

    killpower_exists = killpower_path.exists()
    checks.append(
        PreflightCheck(
            "killpower_absent",
            not killpower_exists,
            (
                f"POWERDOWNFLAG отсутствует: {killpower_path}."
                if not killpower_exists
                else f"Обнаружен POWERDOWNFLAG: {killpower_path}."
            ),
        )
    )

    helper_ok, helper_detail = _helper_check(
        helper_path,
        expected_uid=helper_expected_uid,
        expected_gid=helper_expected_gid,
    )
    checks.append(PreflightCheck("helper_secure", helper_ok, helper_detail))

    lb_ok, lb_detail = _hardware_lb_check(ups_conf_path, config.name)
    checks.append(PreflightCheck("hardware_lb_native", lb_ok, lb_detail))

    facts: PolicySafetyFacts | None
    try:
        facts = facts_reader(config)
    except Exception as exc:
        facts = None
        checks.append(
            PreflightCheck(
                "shutdown_budget_readable",
                False,
                f"Не удалось рассчитать shutdown budget: {type(exc).__name__}: {exc}",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                "shutdown_budget_readable",
                facts.guest_shutdown_budget_seconds >= 0,
                f"Guest shutdown budget: {facts.guest_shutdown_budget_seconds} s.",
            )
        )

    ready = bool(checks) and all(check.ok for check in checks)
    return UpsPolicyPreflight(
        state="Ready" if ready else "Blocked",
        ready=ready,
        checks=tuple(checks),
        guest_shutdown_budget_seconds=(
            facts.guest_shutdown_budget_seconds if facts is not None else None
        ),
    )
