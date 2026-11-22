"""Native offline management CLI for DigitalHouses PBS Agent."""
from __future__ import annotations

import configparser
import fcntl
import getpass
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import warnings
from typing import Sequence
from datetime import datetime, timezone

from .config import DEFAULT_CONFIG, KEYS, SECRETS, load_config
from .mqtt import _read_version, host_ip
from .state import StateStore
from .telemetry import TelemetryClient

SERVICE = "digitalhouses_pbs_agent.service"
STATE_DIR = Path("/var/lib/digitalhouses_pbs_agent")
SOURCE = "https://github.com/DigitalHouses/home-assistant-apps/tree/main/digitalhouses_pbs_agent"
APP = Path("/opt/digitalhouses/digitalhouses_pbs_agent")


class CliError(ValueError):
    """Only trusted, non-secret administrator-facing errors."""


def service_info() -> dict[str, str]:
    """Same local systemd status source as PVE Agent."""
    result = subprocess.run(
        ["systemctl", "show", SERVICE,
         "--property=ActiveState,SubState,MainPID,ActiveEnterTimestampMonotonic,ExecMainStartTimestampMonotonic"],
        text=True, capture_output=True, timeout=2, check=True,
    )
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def _service_state() -> str:
    try:
        run = subprocess.run(["systemctl", "is-active", SERVICE], capture_output=True,
                             text=True, timeout=4, check=False)
        return run.stdout.strip() if run.returncode == 0 else "inactive"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _replace_in_ini(source: str, changes: dict[tuple[str, str], str]) -> str:
    """Preserve unrelated lines and comments, changing only requested options."""
    lines = source.splitlines(keepends=True)
    remaining = dict(changes)
    out: list[str] = []
    section = None
    skipping_continuation = False
    def add_missing(sec: str | None) -> None:
        for (s, key), val in list(remaining.items()):
            if s == sec:
                if out and not out[-1].endswith("\n"):
                    out[-1] += "\n"
                out.append(f"{key} = {val}\n")
                del remaining[(s, key)]
    for line in lines:
        match = re.match(r"^\s*\[([^\]]+)\]\s*$", line)
        if match:
            add_missing(section)
            section = match.group(1)
            skipping_continuation = False
            out.append(line)
            continue
        if skipping_continuation and line[:1].isspace() and line.strip():
            continue
        skipping_continuation = False
        match = re.match(r"^\s*([a-zA-Z0-9_-]+)\s*[:=]", line)
        if match and (section, match.group(1)) in changes:
            key = (section, match.group(1))
            out.append(f"{key[1]} = {changes[key]}\n")
            remaining.pop(key, None)
            skipping_continuation = True
            continue
        out.append(line)
    add_missing(section)
    for section in sorted({s for s, _ in remaining}):
        out.append(f"\n[{section}]\n")
        add_missing(section)
    return "".join(out)


def _atomic_write(path: Path, content: bytes, metadata: os.stat_result) -> None:
    """PVE-style atomic file replacement with original permissions and owner."""
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    candidate = Path(name)
    try:
        with os.fdopen(fd, "wb") as out:
            if os.geteuid() == 0:
                os.fchown(out.fileno(), metadata.st_uid, metadata.st_gid)
            elif (metadata.st_uid, metadata.st_gid) != (os.geteuid(), os.getegid()):
                raise CliError("configuration owner requires root")
            os.fchmod(out.fileno(), stat.S_IMODE(metadata.st_mode))
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.replace(candidate, path)
        folder_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(folder_fd)
        finally:
            os.close(folder_fd)
    finally:
        candidate.unlink(missing_ok=True)


def change_config(path: Path, pairs: list[str], *, restart: bool = True) -> str:
    if not pairs:
        raise CliError("set requires key=value arguments")
    changes = {}
    for pair in pairs:
        key, separator, value = pair.partition("=")
        if key not in KEYS:
            raise CliError("unknown configuration key (see help)")
        target = KEYS[key]
        if target in changes:
            raise CliError("duplicate configuration key or alias in batch")
        if target in SECRETS:
            if not separator:
                if not sys.stdin.isatty():
                    raise CliError("hidden password entry requires a terminal; use key=- with stdin")
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("error", getpass.GetPassWarning)
                        value = getpass.getpass("Password: ")
                except (getpass.GetPassWarning, EOFError) as exc:
                    raise CliError("hidden password entry unavailable; use key=- with stdin") from exc
            elif value == "-":
                if sys.stdin.isatty():
                    raise CliError("stdin password mode requires redirected input; use bare password key for a hidden terminal prompt")
                value = sys.stdin.readline()
                if value == "":
                    raise CliError("password stdin is empty; supply a newline for an empty password")
                value = value.removesuffix("\n").removesuffix("\r")
            else:
                raise CliError("password requires hidden entry or key=- with redirected stdin")
        elif not separator:
            raise CliError("set requires key=value arguments")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise CliError("configuration values must be single-line text without control characters")
        changes[target] = value
    lock = path.with_suffix(path.suffix + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        if path.is_symlink():
            raise CliError("refusing to replace a symlink configuration")
        metadata = path.stat()
        original = path.read_bytes()
        updated = _replace_in_ini(original.decode("utf-8"), changes).encode("utf-8")
        fd2, tmpname = tempfile.mkstemp(prefix=".pbs.conf.", dir=path.parent)
        tmp = Path(tmpname)
        try:
            with os.fdopen(fd2, "wb") as target:
                target.write(updated)
            try:
                old_cfg = load_config(path)
            except (ValueError, OSError, configparser.Error):
                old_cfg = None  # Initial installer config can be incomplete.
            new_cfg = load_config(tmp)
            if old_cfg == new_cfg:
                return "UNCHANGED"
        finally:
            tmp.unlink(missing_ok=True)
        active = restart and _service_state() == "active"
        try:
            _atomic_write(path, updated, metadata)
            if active:
                result = subprocess.run(
                    ["systemctl", "restart", SERVICE],
                    capture_output=True, timeout=90, check=False,
                )
                if result.returncode:
                    raise RuntimeError("systemctl restart failed")
        except Exception as exc:
            try:
                if path.read_bytes() != original:
                    _atomic_write(path, original, metadata)
            except Exception as rollback:
                raise RuntimeError(
                    "configuration transaction and rollback failed; administrator intervention required"
                ) from rollback
            raise RuntimeError(
                "configuration transaction failed; rolled back; service recovery may be required"
            ) from exc
    return "CHANGED"


def _safe_state(path: Path) -> dict:
    """Small cached local state only. Never run PBS, MQTT or GitHub probes."""
    try:
        with path.open("rb") as stream:
            raw = stream.read(128 * 1024 + 1)
        if len(raw) > 128 * 1024:
            return {}
        result = json.loads(raw)
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _observed_time(value: object) -> float:
    if not isinstance(value, str):
        return 0.0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo else 0.0
    except (ValueError, TypeError, OverflowError):
        return 0.0


def _build_commit(path: Path) -> str:
    try:
        source = path.read_text(encoding="utf-8")
        for line in source.splitlines():
            name, eq, value = line.partition("=")
            if eq and name.strip() == "commit" and re.fullmatch(r"[0-9a-f]{40}", value.strip()):
                return value.strip()
    except OSError:
        pass
    return "unknown"


def status(config_path: Path = DEFAULT_CONFIG, state_dir: Path = STATE_DIR,
           app_dir: Path = APP) -> int:
    """PVE-style offline summary, using cached PBS facts and real service state."""
    import socket

    config = load_config(config_path)
    try:
        service = service_info()
    except (OSError, subprocess.SubprocessError):
        service = {}
    active = service.get("ActiveState", "unknown")
    substate = service.get("SubState", "unknown")
    uptime = "unknown"
    try:
        entered = int(service.get("ActiveEnterTimestampMonotonic", "0")) / 1_000_000
        if entered > 0 and active == "active":
            uptime = f"{max(0, int(time.monotonic() - entered))}s"
    except (TypeError, ValueError):
        pass
    ip = host_ip(config.mqtt_host, config.mqtt_port) or "unknown"
    runtime = _safe_state(state_dir / "runtime.json")
    mqtt_runtime = _safe_state(state_dir / "mqtt.json")
    control = _safe_state(state_dir / "control.json")
    telemetry = _safe_state(state_dir / "telemetry.json")
    preference = _safe_state(state_dir / "auto_update.json")
    stamp = _observed_time(runtime.get("observed_at"))
    age = time.time() - stamp if stamp else None
    try:
        pid = int(service.get("MainPID", "0"))
        owner = runtime.get("pid") == pid and pid > 0
    except (ValueError, TypeError):
        owner = False
    live = (active == "active" and owner and age is not None
            and 0 <= age <= max(360, 2 * config.poll_seconds + 60))
    connected = (mqtt_runtime.get("status") if live else None)
    if connected not in {"CONNECTED", "DISCONNECTED", "CONNECTING"}:
        connected = "UNKNOWN"

    def line(key: str, value: object) -> None:
        print(f"  {key + ':':<11}{value}")

    print(f"DigitalHouses PBS Agent {_read_version()} | commit {_build_commit(app_dir / 'BUILD_INFO')}")
    print("SYSTEM")
    line("Service", f"{active}/{substate} | uptime {uptime}")
    line("Hostname", socket.gethostname() or "unknown")
    line("IP", ip)

    print("MQTT")
    line("Broker", f"{config.mqtt_host}:{config.mqtt_port}")
    line("State", f"{connected} | retry 60s, connect timeout 5s")
    line("Connected", mqtt_runtime.get("last_connected") or "unknown")
    line("PUBACK", runtime.get("mqtt_last_ack") if live else "unknown")
    line("Publish", ("ACKNOWLEDGED" if runtime.get("mqtt_publish_state") is True
                    else "FAILED" if runtime.get("mqtt_publish_state") is False
                    else "unknown") if live else "STALE/UNAVAILABLE")
    line("Error", (mqtt_runtime.get("reason") or runtime.get("mqtt_connect_error")
                   or "none known") if active == "active" else "unknown")

    print("PBS")
    line("Status", runtime.get("status", "UNKNOWN") if live else "STALE/UNAVAILABLE")
    if live:
        line("Version", runtime.get("pbs_version") or "unknown")
        for item in runtime.get("datastores", []):
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str):
                continue
            used = item.get("used_percent")
            percent = f"{used:.1f}%" if type(used) in (int, float) else "unavailable"
            line("Datastore", f"{name} | {item.get('health') or 'UNKNOWN'} | used {percent}")
        for item in runtime.get("pbs_errors", [])[:4]:
            if isinstance(item, str):
                line("Error", " ".join(item.split())[:120])
    else:
        line("Datastores", "STALE/UNAVAILABLE")

    print("MONITORING")
    line("Data", f"LIVE, {age:.0f}s old" if live and age is not None else "STALE/UNAVAILABLE")
    if live:
        summary = runtime.get("summary")
        if isinstance(summary, dict):
            line("Groups", summary.get("backup_groups", "unknown"))
            line("Jobs", summary.get("maintenance_jobs", "unknown"))
            line("Problems", summary.get("active_problems") if
                 summary.get("active_problems") is not None else "unknown")
            line("Sync", summary.get("sync_overall") or "unknown")
    print("UPDATES")
    line("Auto", "ON" if preference.get("enabled") is True else "OFF")
    line("Latest", control.get("latest_version") or "unknown")
    line("Checked", control.get("checked_at") or "never")
    card = control.get("card")
    if active == "active" and isinstance(card, dict):
        line("Operation", f"{card.get('operation') or 'none'} {card.get('state') or 'idle'}")
        if card.get("state") == "error" and isinstance(card.get("error"), str):
            line("Error", " ".join(card["error"].split())[:120])
    print("TELEMETRY")
    line("Enabled", "ON" if config.telemetry_enabled else "OFF")
    epoch = telemetry.get("last_success_epoch")
    try:
        last = (datetime.fromtimestamp(epoch, timezone.utc).isoformat()
                if type(epoch) in (int, float) and epoch > 0 else "never")
    except (ValueError, OSError, OverflowError):
        last = "unknown"
    line("Last", last)
    return 0


def _telemetry_delete() -> int:
    """Erase server history using the stored secret; restart agent to reload rotated ID."""
    if not (STATE_DIR / "telemetry.json").exists():
        raise ValueError("no telemetry installation identity exists")
    active = _service_state() == "active"
    if active:
        subprocess.run(["systemctl", "stop", SERVICE], check=True, timeout=60)
    try:
        client = TelemetryClient(
            enabled=False,
            version=_read_version(),
            state_store=StateStore(STATE_DIR / "telemetry.json"),
            build_info_path=APP / "BUILD_INFO",
        )
        if not client.delete():
            raise RuntimeError("telemetry deletion failed; identity remains unchanged")
        print("DELETED installation history; local identity rotated")
    finally:
        if active:
            subprocess.run(["systemctl", "start", SERVICE], check=True, timeout=60)
    return 0


def _release_update() -> int:
    """PVE-compatible CLI lifecycle; PBS retains its shipped installer."""
    from .releases import latest_release, stable_version

    if _service_state() != "active":
        raise CliError("agent service is not running; update requires an active agent")
    try:
        tag, version = latest_release()
        current = _read_version()
        if stable_version(version) <= stable_version(current):
            print(f"UP_TO_DATE {current}")
            return 0
    except (OSError, ValueError) as exc:
        raise CliError("unable to verify latest stable GitHub Release") from exc
    print(f"UPDATING {current} -> {version}", flush=True)
    env = dict(os.environ)
    env["DIGITALHOUSES_SOURCE_REF"] = tag
    try:
        result = subprocess.run(
            ["bash", str(APP / "install.sh"), "--non-interactive"],
            env=env, capture_output=True, text=True, check=False, timeout=900,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("update is still running; check systemctl status " + SERVICE) from exc
    if result.returncode:
        raise RuntimeError("update failed or rolled back; inspect systemctl status " + SERVICE)
    try:
        actual = _read_version()
        correct = stable_version(actual) == stable_version(version)
    except (OSError, ValueError) as exc:
        raise RuntimeError("updater finished but installed version differs") from exc
    if not correct:
        raise RuntimeError("updater finished but installed version differs")
    print(f"UPDATED {actual}")
    return 0


def _release_check() -> int:
    from .releases import latest_release, stable_version
    tag, version = latest_release()
    available = stable_version(version) > stable_version(_read_version())
    print(("AVAILABLE" if available else "UP_TO_DATE"), version, tag)
    return 0


def _auto_update(value: str) -> int:
    store = StateStore(STATE_DIR / "auto_update.json")
    enabled = store.load().get("enabled") is True
    if value == "status":
        print("ON" if enabled else "OFF")
        return 0
    if value not in ("on", "off"):
        raise ValueError("auto-update requires on, off or status")
    new = value == "on"
    if new != enabled:
        store.save({"enabled": new})
    print(("CHANGED" if new != enabled else "UNCHANGED"), "ON" if new else "OFF")
    return 0


def print_help() -> None:
    """Same structure and command descriptions as the current PVE CLI."""
    print("Usage: /usr/local/bin/dh-pbs-agent status | update | auto-update on|off|status | restart | help | set key=value [key=value ...]")
    print("Run status/update/restart/set as root or through sudo. Config: " + str(DEFAULT_CONFIG))
    print("set validates the entire batch, updates atomically, and restarts once only when running.")
    print("auto-update changes the local persistent preference without restarting the agent; default OFF.")
    print("Keys (native INI mapping):")
    for key, (section, field) in KEYS.items():
        print(f"  {key}: [{section}] {field}")
    print("Constraints: instance_id empty or ^[a-z0-9][a-z0-9_-]{0,62}$;")
    print("log_level debug/info/warning/error; mqtt host required; ports 1..65535;")
    print("mqtt keepalive 10..3600s; poll interval 60..3600s;")
    print("unique PBS datastore names; warning/critical percentages 0..100 with warning < critical;")
    print("monitor_backup_rules: datastore|namespace-or--|vm/VMID|hours;... (0..8760h);")
    print("monitor_sync_rules: job-id|hours;... (0..8760h);")
    print("telemetry_enabled true/false; enabling telemetry is required for agent start.")
    print("Passwords: bare secret key uses hidden terminal entry; key=- reads one stdin line.")
    print("Literal secret arguments are rejected. Values must be single-line.")
    print("Use Ansible no_log: true for secret operations.")
    print("Product-specific commands: check-update | telemetry-delete")
    print("Privacy: https://github.com/DigitalHouses/home-assistant-apps/blob/main/docs/standards/PRODUCT_TELEMETRY_POLICY.md")
    print("Full reference: " + SOURCE)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if os.geteuid() != 0:
            raise CliError("run as root or through sudo")
        if args in ([], ["help"], ["--help"], ["-h"]):
            print_help()
            return 0
        if args == ["status"]:
            return status()
        if args == ["update"]:
            return _release_update()
        if len(args) == 2 and args[0] == "auto-update":
            return _auto_update(args[1])
        if args == ["restart"]:
            if _service_state() != "active":
                raise CliError("service is not running; restart never starts an inactive service")
            result = subprocess.run(
                ["systemctl", "restart", SERVICE], capture_output=True,
                timeout=90, check=False,
            )
            if result.returncode:
                raise RuntimeError("systemctl restart failed; inspect systemctl status " + SERVICE)
            print("Restarted " + SERVICE)
            return 0
        if args == ["check-update"]:
            return _release_check()
        if args == ["telemetry-delete"]:
            return _telemetry_delete()
        if args and args[0] == "set":
            print(change_config(DEFAULT_CONFIG, args[1:]))
            return 0
        raise CliError("unknown command or arguments; use help")
    except (CliError, RuntimeError) as exc:
        print("ERROR: " + str(exc))
        return 1
    except (OSError, ValueError, subprocess.SubprocessError, configparser.Error):
        # Configuration and OS exceptions can contain credentials or INI lines.
        print("ERROR: operation failed; check command values, native configuration, permissions and systemctl status " + SERVICE)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
