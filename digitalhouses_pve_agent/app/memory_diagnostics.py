from __future__ import annotations

"""Passive, low-frequency host/LXC OOM and PSI memory diagnostics.

No guest commands, kernel writes, memory-limit changes or automatic recovery.
"""

import json
import logging
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping

from .state_store import StateStore

LOG = logging.getLogger(__name__)
RETENTION_DAYS = 30
# Home Assistant's state attributes have a finite size; keep the complete
# 30-day history locally and publish only a bounded newest-first window.
PUBLISHED_EVENTS = 60
JOURNAL_LIMIT_BYTES = 1_000_000
OOM_GREP = r"Out of memory|oom-kill:|Killed process|oom killer"
_LXC_IDS = (
    re.compile(r"(?:^|/)lxc\.payload\.(\d+)(?:/|$)"),
    re.compile(r"(?:^|/)lxc/(\d+)(?:/|$)"),
    re.compile(r"(?:^|/)pve-container@(\d+)\.service(?:/|$)"),
)
_VM_IDS = (
    re.compile(r"(?:^|/)qemu/(\d+)(?:/|$)"),
    re.compile(r"(?:^|/)qemu\.slice/(\d+)\.scope(?:/|$)"),
    re.compile(r"\bkvm\b.*?\s-id\s+(\d+)\b"),
)


def _as_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        date = datetime.fromisoformat(value)
    except ValueError:
        return None
    if date.tzinfo is None or date.utcoffset() is None:
        return None
    return date.astimezone(timezone.utc)


def _read_counters(path: Path, keys: tuple[str, ...]) -> dict[str, int] | None:
    try:
        raw = path.read_text(encoding="ascii")
    except (OSError, UnicodeError):
        return None
    values: dict[str, int] = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] in keys:
            try:
                values[parts[0]] = int(parts[1])
            except ValueError:
                return None
    if not all(key in values and values[key] >= 0 for key in keys):
        return None
    return values


def read_psi(path: Path) -> dict[str, int] | None:
    try:
        raw = path.read_text(encoding="ascii")
    except (OSError, UnicodeError):
        return None
    result: dict[str, int] = {}
    for line in raw.splitlines():
        parts = line.split()
        if not parts or parts[0] not in ("some", "full"):
            continue
        total = next((x[6:] for x in parts[1:] if x.startswith("total=")), None)
        if total is None:
            return None
        try:
            result[parts[0]] = int(total)
        except ValueError:
            return None
    return result if "some" in result and "full" in result and min(result.values()) >= 0 else None


def _guest_for_message(message: str) -> tuple[str, str]:
    for pattern in _LXC_IDS:
        match = pattern.search(message)
        if match:
            return "LXC", match.group(1)
    for pattern in _VM_IDS:
        match = pattern.search(message)
        if match:
            return "VM", match.group(1)
    return "PVE", "PVE"


def _lxc_cgroups(root: Path, ids: set[str]) -> dict[str, Path]:
    """Find only payload cgroups; avoid counting monitor/systemd ancestors."""
    result: dict[str, tuple[int, Path]] = {}
    if not ids:
        return {}
    try:
        paths = root.rglob("memory.events")
        for events_path in paths:
            folder = events_path.parent
            relative = folder.relative_to(root).as_posix()
            for pattern in _LXC_IDS:
                match = pattern.search("/" + relative)
                if match and match.group(1) in ids:
                    guest_id = match.group(1)
                    # Prefer explicit lxc.payload.N over a hierarchical parent.
                    preference = 2 if "lxc.payload." in relative else 1
                    depth = len(folder.relative_to(root).parts)
                    rank = preference * 100 - depth
                    if guest_id not in result or rank > result[guest_id][0]:
                        result[guest_id] = (rank, folder)
                    break
    except OSError:
        return {}
    return {guest_id: item[1] for guest_id, item in result.items()}


def _guest_names(inventory: Mapping[str, object] | None) -> dict[tuple[str, str], str]:
    names: dict[tuple[str, str], str] = {}
    if not isinstance(inventory, Mapping):
        return names
    for plural, kind in (("lxcs", "LXC"), ("vms", "VM")):
        guests = inventory.get(plural)
        if not isinstance(guests, Mapping):
            continue
        for guest_id, data in guests.items():
            if isinstance(data, Mapping):
                names[(kind, str(guest_id))] = str(data.get("name") or "")
    return names


class MemoryDiagnostics:
    def __init__(
        self,
        store: StateStore,
        *,
        proc_root: Path = Path("/proc"),
        cgroup_root: Path = Path("/sys/fs/cgroup"),
        journal_run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.store = store
        self.proc_root = proc_root
        self.cgroup_root = cgroup_root
        self.journal_run = journal_run
        try:
            state = store.load()
        except Exception as exc:
            LOG.warning("Memory diagnostics: persisted state unavailable: %s", exc)
            state = {}
        self.events = [e for e in state.get("events", []) if isinstance(e, dict)] if isinstance(state.get("events"), list) else []
        self.baselines = state.get("baselines", {}) if isinstance(state.get("baselines"), dict) else {}
        self.next_id = max(1, int(state.get("next_id", 1)))
        self.last_scan = _as_datetime(state.get("last_scan"))
        self.seen_journal = set(str(x) for x in state.get("seen_journal", []) if isinstance(x, str))
        self.journal_status = "unknown"
        self.pressure_status = "unknown"

    def _event(self, *, at: datetime, guest: str, kind: str, level: str, description: str, amount: int = 0) -> dict[str, object]:
        event = {
            "id": self.next_id,
            "at": at.isoformat(),
            "guest": guest,
            "kind": kind,
            "level": level,
            "description": description,
            "amount": amount,
        }
        self.next_id += 1
        self.events.append(event)
        return event

    def _journal(self, now: datetime, guest_names: Mapping[tuple[str, str], str]) -> set[tuple[str, str]]:
        # Revisit a small overlap to tolerate clock/race boundaries. Dedup by
        # journald cursor; never rescan the whole journal on each 10m tick.
        since = (self.last_scan or (now - timedelta(minutes=10))) - timedelta(seconds=5)
        args = [
            "journalctl", "--no-pager", "--quiet", "--output=json",
            "_TRANSPORT=kernel", "--since", since.isoformat(),
            "--until", now.isoformat(), "--grep", OOM_GREP,
        ]
        try:
            proc = self.journal_run(args, capture_output=True, text=True, timeout=8, check=False)
            if proc.returncode not in (0, 1) or (proc.returncode and proc.stderr.strip()):
                raise RuntimeError(proc.stderr.strip() or f"journalctl rc={proc.returncode}")
            if len(proc.stdout.encode("utf-8")) > JOURNAL_LIMIT_BYTES:
                raise RuntimeError("journal window too large; data not complete")
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            LOG.warning("Memory diagnostics: kernel journal unavailable: %s", exc)
            self.journal_status = "unknown"
            return set()

        self.journal_status = "ok"
        found: set[tuple[str, str]] = set()
        for line in proc.stdout.splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            cursor = entry.get("__CURSOR")
            if not isinstance(cursor, str) or not cursor or cursor in self.seen_journal:
                continue
            message = entry.get("MESSAGE")
            if not isinstance(message, str):
                continue
            killed = bool(re.search(r"\bKilled process\s+\d+", message, re.IGNORECASE))
            attempted = "out of memory" in message.lower() or "oom-kill:" in message.lower()
            if not (killed or attempted) or "invoked oom-killer" in message.lower():
                continue
            try:
                at = datetime.fromtimestamp(
                    int(entry["__REALTIME_TIMESTAMP"]) / 1_000_000,
                    tz=timezone.utc,
                )
            except (KeyError, ValueError, TypeError, OverflowError):
                at = now
            kind, guest = _guest_for_message(message)
            name = guest_names.get((kind, guest), "")
            subject = f"{kind} {guest}" + (f" {name}" if name else "") if kind != "PVE" else "PVE"
            process = re.search(r"Killed process\s+\d+\s+\(([^)]+)\)", message)
            if killed:
                description = "OOM Killer: " + (f"процесс {process.group(1)} уничтожен" if process else "процесс уничтожен")
                severity = "red"
            else:
                description, severity = "Обнаружен OOM (kill не подтверждён)", "orange"
            self._event(at=at, guest=guest, kind="oom", level=severity, description=description)
            found.add((kind, guest))
            self.seen_journal.add(cursor)
        return found

    def _sample(
        self,
        name: str,
        path: Path,
        now: datetime,
        *,
        guest: str,
        journal_seen: set[tuple[str, str]],
        identity: str,
    ) -> bool:
        psi = read_psi(path / "memory.pressure")
        # There is no memory.events at /proc; only LXC uses these counters.
        ev_path = path / "memory.events"
        ev = _read_counters(ev_path, ("oom", "oom_kill")) if guest != "PVE" else None
        if psi is None and (guest == "PVE" or ev is None):
            self.baselines.pop(name, None)
            return False

        counters = {**(psi or {}), **(ev or {})}
        previous = self.baselines.get(name)
        valid_prev = (
            isinstance(previous, dict)
            and previous.get("identity") == identity
            and all(
                isinstance(previous.get(key), int) and counters[key] >= previous[key]
                for key in counters
            )
        )
        if valid_prev:
            if ev is not None:
                kills = ev["oom_kill"] - previous["oom_kill"]
                oom = ev["oom"] - previous["oom"]
                # The same OOM may have appeared in both journal and cgroup.
                if (kills > 0 or oom > 0) and ("LXC", guest) not in journal_seen:
                    self._event(
                        at=now, guest=guest, kind="oom",
                        level="red" if kills else "orange",
                        description=(
                            f"OOM Killer: уничтожено процессов {kills}"
                            if kills else f"Обнаружен OOM: {oom} срабатываний, kill не подтверждён"
                        ),
                        amount=kills or oom,
                    )
            if psi is not None:
                full_delta = psi["full"] - previous["full"]
                # full total is microseconds, not a percentage. Consecutive
                # sampled windows are merged, not logged every 10 minutes.
                active_id = previous.get("pressure_event")
                if full_delta > 0:
                    active = next((e for e in self.events if e.get("id") == active_id), None)
                    if active is None:
                        active = self._event(
                            at=now, guest=guest, kind="pressure", level="yellow",
                            description="Memory Pressure FULL",
                            amount=0,
                        )
                    active["amount"] = int(active.get("amount", 0)) + full_delta
                    active["description"] = f"Memory Pressure FULL · задержки {active['amount'] / 1_000_000:.2f} с"
                    counters["pressure_event"] = active["id"]
        counters["identity"] = identity
        self.baselines[name] = counters
        return True

    def scan(self, now: datetime, inventory: Mapping[str, object] | None) -> dict[str, object]:
        now = now.astimezone(timezone.utc)
        names = _guest_names(inventory)
        seen = self._journal(now, names)
        ok = 0
        total = 1
        host = self.proc_root / "pressure"
        # _sample expects memory.pressure in the given folder.
        # /proc/pressure/memory has a different filename, handled separately.
        host_psi = read_psi(host / "memory")
        host_previous = self.baselines.get("PVE")
        if host_psi is not None:
            ok += 1
            if isinstance(host_previous, dict) and all(
                isinstance(host_previous.get(k), int) and v >= host_previous[k]
                for k, v in host_psi.items()
            ):
                delta = host_psi["full"] - host_previous["full"]
                active_id = host_previous.get("pressure_event")
                if delta:
                    active = next((e for e in self.events if e.get("id") == active_id), None)
                    if active is None:
                        active = self._event(
                            at=now, guest="PVE", kind="pressure", level="yellow",
                            description="Memory Pressure FULL", amount=0,
                        )
                    active["amount"] = int(active.get("amount", 0)) + delta
                    active["description"] = f"Memory Pressure FULL · задержки {active['amount'] / 1_000_000:.2f} с"
                    host_psi["pressure_event"] = active["id"]
            self.baselines["PVE"] = host_psi
        else:
            self.baselines.pop("PVE", None)

        lxc_ids = {guest for kind, guest in names if kind == "LXC" and guest.isdigit()}
        discovered = _lxc_cgroups(self.cgroup_root, lxc_ids)
        for guest_id, path in discovered.items():
            total += 1
            try:
                stat = path.stat()
            except OSError:
                continue
            # cgroup inode changes after LXC restart; reset baseline.
            identity = f"{path}:{stat.st_ino}:{stat.st_ctime_ns}"
            if self._sample(f"LXC:{guest_id}", path, now, guest=guest_id, journal_seen=seen, identity=identity):
                ok += 1
        for key in tuple(self.baselines):
            if key.startswith("LXC:") and key[4:] not in discovered:
                self.baselines.pop(key, None)

        cutoff = now - timedelta(days=RETENTION_DAYS)
        self.events = [event for event in self.events if (date := _as_datetime(event.get("at"))) is not None and date >= cutoff]
        self.events.sort(key=lambda event: (str(event.get("at")), int(event.get("id", 0))), reverse=True)
        # Don't record journal watermark on failure, so the next pass retries
        # the same interval. Persist seen cursors to deduplicate overlap.
        if self.journal_status == "ok":
            self.last_scan = now
        self.pressure_status = "ok" if ok == total else "unknown"
        # The retained publisher and local state are deliberately separate.
        self.store.save({
            "events": self.events, "next_id": self.next_id,
            "baselines": self.baselines,
            "last_scan": self.last_scan.isoformat() if self.last_scan else None,
            "seen_journal": sorted(self.seen_journal)[-2000:],
        })
        return self.payload()

    def payload(self) -> dict[str, object]:
        return {
            "count": len(self.events),
            "events": self.events[:PUBLISHED_EVENTS],
            "truncated": len(self.events) > PUBLISHED_EVENTS,
            "retention_days": RETENTION_DAYS,
            "journal_status": self.journal_status,
            "pressure_status": self.pressure_status,
            "last_checked": self.last_scan.isoformat() if self.last_scan else None,
        }
