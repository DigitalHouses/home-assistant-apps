from __future__ import annotations

import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import UpsConfig
from .ups_nut import read_ups
from .ups_policy import PolicySafetyFacts
from .ups_policy_host import read_policy_safety_facts
from .ups_shutdown_policy import UpsShutdownPolicy, read_shutdown_policy


_FORBIDDEN_LB_DIRECTIVES = {
    "ignorelb",
    "override.battery.runtime.low",
    "override.battery.charge.low",
}


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
    section_re = re.compile(r"^\s*\[([^]]+)\]\s*(?:#.*)?$")
    selected: list[str] | None = None
    for raw in text.splitlines():
        match = section_re.match(raw)
        if match:
            if match.group(1).strip() == ups_name:
                selected = []
            elif selected is not None:
                break
            continue
        if selected is not None:
            selected.append(raw)
    return selected


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


def _helper_check(path: Path) -> tuple[bool, str]:
    try:
        info = path.stat()
    except OSError as exc:
        return False, f"Helper недоступен: {path}: {type(exc).__name__}."
    mode = stat.S_IMODE(info.st_mode)
    if not path.is_file():
        return False, f"Helper не является обычным файлом: {path}."
    if mode & 0o111 == 0:
        return False, f"Helper не исполняемый: {path}."
    if mode & 0o022:
        return False, f"Helper доступен на запись группе/остальным: {path}."
    return True, f"Helper безопасен: {path}, mode {mode:04o}."


def read_policy_preflight(
    config: UpsConfig,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ups_reader: Callable[[UpsConfig], object] = read_ups,
    shutdown_policy_reader: Callable[[], UpsShutdownPolicy] = read_shutdown_policy,
    facts_reader: Callable[[UpsConfig], PolicySafetyFacts] = read_policy_safety_facts,
    ups_conf_path: Path = Path("/etc/nut/ups.conf"),
    helper_path: Path = Path(
        "/opt/digitalhouses/dh_pve_app/bin/dh-pve-ups-policy-cmd"
    ),
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
                "monitor_inactive",
                policy.nut_monitor == "inactive",
                f"nut-monitor: {policy.nut_monitor}; до commissioning ожидается inactive.",
            )
        )
        shutdown_noop = (
            not policy.shutdown_enabled and policy.shutdown_command == "/bin/true"
        )
        checks.append(
            PreflightCheck(
                "shutdown_noop",
                shutdown_noop,
                f"SHUTDOWNCMD: {policy.shutdown_command or 'не задан'}.",
            )
        )

    checks.append(
        PreflightCheck(
            "killpower_absent",
            not killpower_path.exists(),
            (
                f"POWERDOWNFLAG отсутствует: {killpower_path}."
                if not killpower_path.exists()
                else f"Обнаружен POWERDOWNFLAG: {killpower_path}."
            ),
        )
    )

    helper_ok, helper_detail = _helper_check(helper_path)
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
