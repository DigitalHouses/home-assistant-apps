"""Native offline management CLI for DigitalHouses PBS Agent."""
from __future__ import annotations

import argparse
import configparser
import fcntl
import getpass
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

from .config import DEFAULT_CONFIG, KEYS, SECRETS, load_config
from .mqtt import _read_version, host_ip

SERVICE = "digitalhouses_pbs_agent.service"
STATE_DIR = Path("/var/lib/digitalhouses_pbs_agent")
SOURCE = "https://github.com/DigitalHouses/home-assistant-apps/tree/main/digitalhouses_pbs_agent"
APP = Path("/opt/digitalhouses/digitalhouses_pbs_agent")


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


def change_config(path: Path, pairs: list[str], *, restart: bool = True) -> str:
    if not pairs:
        raise ValueError("set needs key=value")
    changes = {}
    for pair in pairs:
        key, separator, value = pair.partition("=")
        if key not in KEYS:
            raise ValueError("unknown config key; see help")
        target = KEYS[key]
        if target in changes:
            raise ValueError("duplicate configuration key")
        if target in SECRETS:
            if not separator:
                if not sys.stdin.isatty():
                    raise ValueError("secret requires hidden terminal or key=- with redirected stdin")
                value = getpass.getpass("MQTT password: ")
            elif value == "-":
                if sys.stdin.isatty():
                    raise ValueError("key=- requires redirected stdin")
                value = sys.stdin.readline().rstrip("\r\n")
            else:
                raise ValueError("MQTT password is not accepted in process arguments")
        elif not separator:
            raise ValueError("set needs key=value")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise ValueError("control characters are forbidden")
        changes[target] = value
    lock = path.with_suffix(path.suffix + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        if path.is_symlink():
            raise ValueError("refusing symlink configuration")
        old = path.read_text(encoding="utf-8")
        updated = _replace_in_ini(old, changes)
        fd2, tmpname = tempfile.mkstemp(prefix=".pbs.conf.", dir=path.parent)
        tmp = Path(tmpname)
        try:
            metadata = path.stat()
            with os.fdopen(fd2, "w", encoding="utf-8") as target:
                target.write(updated)
                target.flush()
                os.fsync(target.fileno())
                os.fchmod(target.fileno(), stat.S_IMODE(metadata.st_mode))
                if os.geteuid() == 0:
                    os.fchown(target.fileno(), metadata.st_uid, metadata.st_gid)
            try:
                old_cfg = load_config(path)
            except (ValueError, OSError, configparser.Error):
                old_cfg = None  # Initial staged installer INI may be incomplete.
            new_cfg = load_config(tmp)
            if old_cfg == new_cfg:
                return "UNCHANGED"
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
    if restart and _service_state() == "active":
        ret = subprocess.run(["systemctl", "restart", SERVICE], check=False, timeout=90)
        if ret.returncode:
            raise RuntimeError("config changed, service restart failed")
    return "CHANGED"


def status() -> int:
    try:
        config = load_config()
        mqtt = f"{config.mqtt_host}:{config.mqtt_port}"
        ip = host_ip(config.mqtt_host, config.mqtt_port) or "unknown"
    except Exception:
        mqtt, ip = "unknown", "unknown"
    try:
        runtime = json.loads((STATE_DIR / "runtime.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        runtime = {}
    observed = runtime.get("observed_at")
    stale = True
    if observed:
        try:
            stamp = datetime.fromisoformat(observed)
            stale = (datetime.now(timezone.utc) - stamp).total_seconds() > 900
        except ValueError:
            pass
    import socket
    print("DigitalHouses PBS Agent", _read_version())
    print("Hostname:", socket.gethostname())
    print("IP:", ip)
    print("Systemd:", _service_state())
    print("MQTT broker:", mqtt)
    print("MQTT runtime:", runtime.get("mqtt", "unknown"))
    print("Last MQTT PUBACK:", runtime.get("mqtt_last_ack", "unknown"))
    print("PBS status:", runtime.get("status", "UNKNOWN"))
    print("Last collection:", observed or "unknown", "(STALE)" if stale else "(current)")
    print("Build metadata:", (APP / "BUILD_INFO").read_text(encoding="utf-8").strip()
          if (APP / "BUILD_INFO").exists() else "development/unverified")
    if runtime.get("error"):
        print("Last error:", runtime["error"])
    return 0


def _release_update() -> int:
    import urllib.request
    url = "https://api.github.com/repos/DigitalHouses/home-assistant-apps/releases?per_page=100"
    req = urllib.request.Request(url, headers={"User-Agent": "digitalhouses_pbs_agent"})
    with urllib.request.urlopen(req, timeout=15) as response:
        releases = json.load(response)
    versions = []
    for item in releases:
        tag = str(item.get("tag_name") or "")
        match = re.fullmatch(r"digitalhouses_pbs_agent-v(\d+)\.(\d+)\.(\d+)", tag)
        if match and not item.get("draft") and not item.get("prerelease"):
            versions.append((tuple(map(int, match.groups())), tag))
    if not versions:
        raise ValueError("no stable PBS Agent GitHub Release found")
    version, tag = max(versions)
    installed = tuple(map(int, _read_version().split(".")[:3]))
    if version <= installed:
        print("UP_TO_DATE", _read_version())
        return 0
    env = dict(os.environ)
    env["DIGITALHOUSES_SOURCE_REF"] = tag
    ret = subprocess.run(["bash", str(APP / "install.sh"), "--non-interactive"],
                         env=env, check=False, timeout=300)
    if ret.returncode:
        raise RuntimeError("release update failed")
    print("UPDATED", tag)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="dh-pbs-agent")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("restart")
    sub.add_parser("update")
    sub.add_parser("help")
    setparser = sub.add_parser("set")
    setparser.add_argument("pairs", nargs="+")
    args = parser.parse_args()
    try:
        if args.command == "help":
            print("Usage: dh-pbs-agent status | restart | update | set key=value... | help")
            print("Native INI:", DEFAULT_CONFIG)
            print("Config keys:", ", ".join(sorted(KEYS)))
            print("Secrets: mqtt_password (hidden prompt or mqtt_password=- from stdin).")
            print("monitor_backup_rules format: datastore|namespace-or--|vm/VMID|hours;...")
            print("monitor_sync_rules format: job-id|hours;...")
            print("Reference:", SOURCE)
        elif args.command == "status":
            return status()
        elif args.command == "restart":
            if _service_state() != "active":
                raise RuntimeError("service is not running")
            subprocess.run(["systemctl", "restart", SERVICE], check=True, timeout=90)
            print("RESTARTED")
        elif args.command == "update":
            return _release_update()
        elif args.command == "set":
            print(change_config(DEFAULT_CONFIG, args.pairs))
        return 0
    except Exception as exc:
        # Error values must never contain a secret or the raw source config.
        print(f"ERROR: {type(exc).__name__}: {str(exc)[:120]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
