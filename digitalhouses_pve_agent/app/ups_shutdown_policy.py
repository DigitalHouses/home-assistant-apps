from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class UpsShutdownPolicy:
    state: str
    role: str
    nut_monitor: str
    shutdown_enabled: bool
    shutdown_command: str | None
    min_supplies: int | None
    pollfreq_seconds: int | None
    pollfreqalert_seconds: int | None
    deadtime_seconds: int | None
    hostsync_seconds: int | None
    finaldelay_seconds: int | None
    upssched_present: bool
    upssched_rules: int
    upssched_active: bool
    guest_shutdown_budget_seconds: int | None
    power_restore_behavior: str
    on_battery_delay_minutes: int | None = None
    power_restore_delay_seconds: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "role": self.role,
            "nut_monitor": self.nut_monitor,
            "shutdown_enabled": self.shutdown_enabled,
            "shutdown_command": self.shutdown_command,
            "min_supplies": self.min_supplies,
            "pollfreq_seconds": self.pollfreq_seconds,
            "pollfreqalert_seconds": self.pollfreqalert_seconds,
            "deadtime_seconds": self.deadtime_seconds,
            "hostsync_seconds": self.hostsync_seconds,
            "finaldelay_seconds": self.finaldelay_seconds,
            "upssched_present": self.upssched_present,
            "upssched_rules": self.upssched_rules,
            "upssched_active": self.upssched_active,
            "guest_shutdown_budget_seconds": self.guest_shutdown_budget_seconds,
            "power_restore_behavior": self.power_restore_behavior,
            "on_battery_delay_minutes": self.on_battery_delay_minutes,
            "power_restore_delay_seconds": self.power_restore_delay_seconds,
        }


def _active_lines(text: str | None) -> list[str]:
    if text is None:
        return []
    lines: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return lines


def _directive_map(text: str) -> dict[str, list[list[str]]]:
    result: dict[str, list[list[str]]] = {}
    for line in _active_lines(text):
        try:
            parts = shlex.split(line, comments=True, posix=True)
        except ValueError:
            continue
        if not parts:
            continue
        result.setdefault(parts[0].upper(), []).append(parts[1:])
    return result


def _first_int(directives: dict[str, list[list[str]]], key: str) -> int | None:
    values = directives.get(key, [])
    if not values or not values[0]:
        return None
    try:
        return int(values[0][0])
    except ValueError:
        return None


def _on_battery_delay_minutes(upssched_text: str | None) -> int | None:
    for line in _active_lines(upssched_text):
        try:
            parts = shlex.split(line, comments=True, posix=True)
        except ValueError:
            continue
        if len(parts) < 6:
            continue
        if (
            parts[0].upper() != "AT"
            or parts[1].upper() != "ONBATT"
            or parts[3].upper() != "START-TIMER"
            or parts[4] != "dh-pve-ups-shutdown"
        ):
            continue
        try:
            seconds = int(parts[5])
        except ValueError:
            continue
        if seconds >= 0 and seconds % 60 == 0:
            return seconds // 60
    return None


def _ups_section_int(
    ups_conf_text: str | None,
    ups_name: str,
    key: str,
) -> int | None:
    if not ups_conf_text:
        return None
    section_re = re.compile(r"^\s*\[([^]]+)\]\s*(?:#.*)?$")
    in_section = False
    wanted = key.casefold()
    for raw in ups_conf_text.splitlines():
        match = section_re.match(raw)
        if match:
            in_section = match.group(1).strip() == ups_name
            continue
        if not in_section:
            continue
        stripped = raw.split("#", 1)[0].strip()
        if not stripped:
            continue
        if "=" in stripped:
            current_key, value = stripped.split("=", 1)
        else:
            parts = stripped.split(None, 1)
            if len(parts) != 2:
                continue
            current_key, value = parts
        if current_key.strip().casefold() != wanted:
            continue
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def parse_shutdown_policy(
    upsmon_text: str,
    upssched_text: str | None,
    *,
    ups_conf_text: str | None = None,
    ups_name: str = "ups",
    monitor_active: bool | None,
    guest_shutdown_budget_seconds: int | None = None,
    power_restore_behavior: str = "Not configured",
) -> UpsShutdownPolicy:
    directives = _directive_map(upsmon_text)

    role = "unknown"
    monitor_entries = directives.get("MONITOR", [])
    if monitor_entries and monitor_entries[0]:
        candidate = monitor_entries[0][-1].lower()
        if candidate in {"primary", "secondary"}:
            role = candidate

    shutdown_command: str | None = None
    shutdown_entries = directives.get("SHUTDOWNCMD", [])
    if shutdown_entries:
        shutdown_command = " ".join(shutdown_entries[0]).strip() or None

    if monitor_active is True:
        monitor_state = "active"
    elif monitor_active is False:
        monitor_state = "inactive"
    else:
        monitor_state = "unknown"

    shutdown_enabled = bool(
        monitor_active is True
        and shutdown_command
        and shutdown_command != "/bin/true"
    )
    if monitor_active is False or shutdown_command == "/bin/true":
        state = "Commissioning"
    elif shutdown_enabled:
        state = "Enabled"
    else:
        state = "Unknown"

    upssched_present = upssched_text is not None
    upssched_rules = sum(
        1
        for line in _active_lines(upssched_text)
        if line.upper().startswith("AT ")
    )

    return UpsShutdownPolicy(
        state=state,
        role=role,
        nut_monitor=monitor_state,
        shutdown_enabled=shutdown_enabled,
        shutdown_command=shutdown_command,
        min_supplies=_first_int(directives, "MINSUPPLIES"),
        pollfreq_seconds=_first_int(directives, "POLLFREQ"),
        pollfreqalert_seconds=_first_int(directives, "POLLFREQALERT"),
        deadtime_seconds=_first_int(directives, "DEADTIME"),
        hostsync_seconds=_first_int(directives, "HOSTSYNC"),
        finaldelay_seconds=_first_int(directives, "FINALDELAY"),
        upssched_present=upssched_present,
        upssched_rules=upssched_rules,
        upssched_active=upssched_rules > 0,
        guest_shutdown_budget_seconds=guest_shutdown_budget_seconds,
        power_restore_behavior=power_restore_behavior,
        on_battery_delay_minutes=_on_battery_delay_minutes(upssched_text),
        power_restore_delay_seconds=_ups_section_int(
            ups_conf_text,
            ups_name,
            "ondelay",
        ),
    )


def _read_optional(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        return None


def read_shutdown_policy(
    *,
    upsmon_path: Path = Path("/etc/nut/upsmon.conf"),
    upssched_path: Path = Path("/etc/nut/upssched.conf"),
    ups_conf_path: Path = Path("/etc/nut/ups.conf"),
    ups_name: str = "ups",
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    guest_shutdown_budget_seconds: int | None = None,
    power_restore_behavior: str = "Not configured",
) -> UpsShutdownPolicy:
    upsmon_text = _read_optional(upsmon_path) or ""
    upssched_text = _read_optional(upssched_path)
    ups_conf_text = _read_optional(ups_conf_path)

    monitor_active: bool | None
    try:
        completed = runner(
            ["systemctl", "is-active", "nut-monitor.service"],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
        state = (completed.stdout or "").strip().lower()
        if state == "active":
            monitor_active = True
        elif state:
            monitor_active = False
        else:
            monitor_active = None
    except (OSError, subprocess.TimeoutExpired):
        monitor_active = None

    return parse_shutdown_policy(
        upsmon_text,
        upssched_text,
        ups_conf_text=ups_conf_text,
        ups_name=ups_name,
        monitor_active=monitor_active,
        guest_shutdown_budget_seconds=guest_shutdown_budget_seconds,
        power_restore_behavior=power_restore_behavior,
    )
