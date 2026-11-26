"""Read-only provisioning diagnostics for a locally connected USB UPS.

Unlike the normal UPS runtime, this collector works *before* NUT is installed.
No udev writes, service restarts or USB polling loops are performed here.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from .config import AppConfig, UpsConfig
from .state_store import StateStore
from .ups_nut import read_ups
from .ups_policy_preflight import read_policy_preflight

USB_VENDOR_IDS = frozenset({"0764", "051d", "0463", "09ae", "0d9f", "0665", "06da"})
USB_HINT = re.compile(
    r"ups|uninterruptible|cyberpower|cyber power|apc|eaton|mge|"
    r"powerwalker|powercom|tripp.lite|riello|voltronic|ippon",
    re.IGNORECASE,
)
DRIVER_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,40}$")
DEFAULT_DRIVERS = ("usbhid-ups", "nutdrv_qx", "blazer_usb")
VALID_STAGES = ("install", "driver", "server", "primary", "monitor", "activate")


def usb_ups_devices(root: Path = Path("/sys/bus/usb/devices")) -> list[dict[str, str]]:
    devices: list[dict[str, str]] = []
    if not root.is_dir():
        return devices
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        try:
            def field(name: str) -> str:
                item = path / name
                return item.read_text(encoding="utf-8").strip() if item.is_file() else ""
            vid, pid = field("idVendor").lower(), field("idProduct").lower()
            if not re.fullmatch(r"[0-9a-f]{4}", vid) or not re.fullmatch(r"[0-9a-f]{4}", pid):
                continue
            maker, model = field("manufacturer"), field("product")
            if vid not in USB_VENDOR_IDS and not USB_HINT.search(f"{maker} {model}"):
                continue
            bus, dev = field("busnum"), field("devnum")
            devices.append({
                "vendor": maker[:80], "model": model[:100], "serial": field("serial")[:100],
                "vid": vid, "pid": pid,
                "bus": f"{int(bus):03d}" if bus.isdecimal() else "",
                "device": f"{int(dev):03d}" if dev.isdecimal() else "",
                "sysfs": path.name,
            })
        except (OSError, ValueError):
            continue
    return devices[:8]


def driver_options(root: Path = Path("/lib/nut")) -> list[str]:
    available: set[str] = set()
    for directory in (root, Path("/usr/lib/nut") if root == Path("/lib/nut") else root):
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if path.is_file() and path.name not in {"upsdrvctl", "upssched", "upsmon", "upsd"}:
                if DRIVER_PATTERN.fullmatch(path.name) and path.stat().st_mode & 0o111:
                    available.add(path.name)
    return sorted(available)[:128] if available else list(DEFAULT_DRIVERS)


def service_status(unit: str, *, runner: Callable = subprocess.run) -> str:
    try:
        result = runner(["systemctl", "is-active", unit], capture_output=True,
                        text=True, check=False, timeout=3)
        value = (result.stdout or "").strip().lower()
        return value if value in {"active", "inactive", "failed", "activating"} else "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def _has_nut(*, which: Callable = shutil.which) -> bool:
    return bool(which("upsc") and which("upsd"))


def _managed_source(config: AppConfig, nut_dir: Path) -> bool:
    """Never rewrite an SNMP, remote, or another host's managed NUT."""
    if config.ups.host not in ("127.0.0.1", "localhost"):
        return False
    path = nut_dir / "ups.conf"
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return True
    except OSError:
        return False
    active = "\n".join(line.split("#", 1)[0] for line in content.splitlines())
    if re.search(r"^\s*driver\s*=\s*(?:snmp-ups|netxml-ups|powerman-pdu)\b", active, re.I | re.M):
        return False
    return True


def _configured_name(config: AppConfig, state_dir: Path, nut_dir: Path) -> str:
    selected = StateStore(state_dir / "ups_selection.json").load().get("selected_name")
    if isinstance(selected, str) and DRIVER_PATTERN.fullmatch(selected):
        return selected
    try:
        text = (nut_dir / "ups.conf").read_text(encoding="utf-8")
    except OSError:
        return config.ups.name
    names = re.findall(r"^\s*\[([a-zA-Z0-9_.-]+)\]", text, re.M)
    return names[0] if len(names) == 1 else config.ups.name


def setup_snapshot(
    config: AppConfig,
    *,
    state_dir: Path,
    sysfs_root: Path = Path("/sys/bus/usb/devices"),
    nut_dir: Path = Path("/etc/nut"),
    which: Callable = shutil.which,
    runner: Callable = subprocess.run,
    preflight: Callable = read_policy_preflight,
    ups_reader: Callable = read_ups,
) -> dict[str, object]:
    usb = usb_ups_devices(sysfs_root)
    name = _configured_name(config, state_dir, nut_dir)
    installed = _has_nut(which=which)
    can_manage = _managed_source(config, nut_dir)
    preferred = StateStore(state_dir / "ups_setup_driver.json").load().get("driver")
    driver_selected = preferred if isinstance(preferred, str) and DRIVER_PATTERN.fullmatch(preferred) else ""
    driver_reported = ""
    ups_online = False
    if installed:
        try:
            observed = ups_reader(UpsConfig(
                enabled=True, name=name, host=config.ups.host, port=config.ups.port,
                command_username=config.ups.command_username,
                command_password=config.ups.command_password,
            ))
            driver_reported = observed.driver_name or ""
            ups_online = bool(observed.line_power)
        except Exception:
            pass
    options = driver_options()
    if not driver_selected:
        driver_selected = (driver_reported if driver_reported in options else
                           "Выберите драйвер")
    unit_driver = service_status(f"nut-driver@{name}.service", runner=runner) if installed else "missing"
    unit_server = service_status("nut-server.service", runner=runner) if installed else "missing"
    unit_monitor = service_status("nut-monitor.service", runner=runner) if installed else "missing"
    checks: dict[str, bool] = {}
    issues: list[str] = []
    if installed:
        try:
            report = preflight(UpsConfig(
                enabled=True, name=name, host=config.ups.host, port=config.ups.port,
                command_username=config.ups.command_username,
                command_password=config.ups.command_password,
            ))
            checks = {c.key: c.ok for c in report.checks}
            issues = [c.detail for c in report.checks if not c.ok]
        except Exception:
            issues = ["Preflight UPS/NUT недоступен"]
    role_ok = (checks.get("primary_role", False)
               and checks.get("nut_primary_role", False)
               and checks.get("credentials_consistent", False))
    monitor_ok = checks.get("monitor_active", False)
    shutdown_ok = checks.get("shutdown_enabled", False) and checks.get("helper_secure", False)
    # No USB requirement for existing external UPS. It remains read-only to this wizard.
    ready = installed and ups_online and all(checks.values()) and bool(checks)
    status = {
        "ready": bool(ready), "state": "ready" if ready else "blocked",
        "transport": "usb" if can_manage else "external",
        "usb": {"detected": len(usb) == 1, "count": len(usb), "devices": usb,
                "selected": usb[0] if len(usb) == 1 else None},
        "nut": {"installed": installed, "server": unit_server},
        "driver": {"selected": driver_selected, "reported": driver_reported,
                   "service": unit_driver, "responding": bool(driver_reported)},
        "primary": {"ready": role_ok},
        "monitor": {"ready": monitor_ok, "service": unit_monitor},
        "shutdown": {"ready": shutdown_ok},
        "ups": {"name": name, "on_line": ups_online},
        "checks": checks, "issues": issues[:30],
        "can_manage": can_manage,
    }
    candidates = len(usb) == 1 and can_manage
    can_activate = bool(checks) and all(
        ok for key, ok in checks.items() if key != "shutdown_enabled"
    )
    status["actions"] = {
        "install": candidates and not installed,
        "driver": candidates and installed and not driver_reported,
        "server": candidates and installed and unit_driver == "active" and
                  unit_server != "active",
        "primary": candidates and installed and bool(driver_reported) and ups_online and not role_ok,
        "monitor": candidates and role_ok and ups_online and not monitor_ok,
        "activate": candidates and can_activate and monitor_ok and role_ok and ups_online and not shutdown_ok,
    }
    return status
