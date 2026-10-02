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
# 30 seconds of PSI FULL per 10 minutes, scaled to the actual observation window.
PRESSURE_THRESHOLD_PERCENT = 5
PRESSURE_EVENT_POLICY = "full-5pct-v1"
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
_LXC_PAYLOAD_IDS = _LXC_IDS[:2]  # Never sample the host-side pve-container monitor unit.
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
            for pattern in _LXC_PAYLOAD_IDS:
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
            LOG.warning("Недоступно сохранённое состояние диагностики памяти: %s", exc)
            state = {}
        self.events = [e for e in state.get("events", []) if isinstance(e, dict)] if isinstance(state.get("events"), list) else []
        # Full sampled deltas are local-only, including zero and subthreshold samples.
        self.psi_samples = (
            [s for s in state["psi_samples"] if isinstance(s, dict)]
            if isinstance(state.get("psi_samples"), list) else []
        )
        self.baselines = state.get("baselines", {}) if isinstance(state.get("baselines"), dict) else {}
        self.next_id = max(1, int(state.get("next_id", 1)))
        self.last_scan = _as_datetime(state.get("last_scan"))
        self.checked_at = _as_datetime(state.get("checked_at"))
        self.seen_journal = set(str(x) for x in state.get("seen_journal", []) if isinstance(x, str))
        self.boot_id = state.get("boot_id") if isinstance(state.get("boot_id"), str) else None
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

    def _observe_psi(
        self,
        *,
        guest: str,
        now: datetime,
        psi: Mapping[str, int],
        previous: Mapping[str, object] | None,
        counters: dict[str, object],
    ) -> None:
        """Save every valid interval locally; emit only actionable FULL episodes."""
        if not isinstance(previous, Mapping):
            return
        observed_at = _as_datetime(previous.get("observed_at")) or self.checked_at
        if observed_at is None:
            return
        elapsed_us = int((now - observed_at).total_seconds() * 1_000_000)
        if elapsed_us <= 0:
            # Wall clock moved backward or an immediate duplicate sample.
            return
        some_delta = psi["some"] - int(previous["some"])
        full_delta = psi["full"] - int(previous["full"])
        if some_delta < 0 or full_delta < 0:
            return
        self.psi_samples.append({
            "at": now.isoformat(), "guest": guest,
            "elapsed_us": elapsed_us, "some_us": some_delta, "full_us": full_delta,
        })
        if not full_delta:
            return  # Zero FULL ends the previously active or pending episode.

        active_id = previous.get("pressure_event")
        active = next(
            (e for e in self.events if
             e.get("id") == active_id and e.get("kind") == "pressure"
             and e.get("policy") == PRESSURE_EVENT_POLICY),
            None,
        )
        if active is None:
            # Judge each sampling window by its real elapsed time. This also
            # handles a 10-60 minute setting change and longer collection gaps.
            if full_delta * 100 < elapsed_us * PRESSURE_THRESHOLD_PERCENT:
                counters["pressure_pending_us"] = (
                    max(0, int(previous.get("pressure_pending_us") or 0)) + full_delta
                )
                return
            # Subthreshold intervals preceding the first qualifying interval
            # remain part of the same contiguous episode, not new HA events.
            full_delta += max(0, int(previous.get("pressure_pending_us") or 0))
            active = self._event(
                at=now, guest=guest, kind="pressure", level="yellow",
                description="Memory Pressure FULL", amount=0,
            )
            active["policy"] = PRESSURE_EVENT_POLICY
        active["amount"] = int(active.get("amount", 0)) + full_delta
        active["description"] = (
            f"Memory Pressure FULL · задержки {active['amount'] / 1_000_000:.2f} с"
        )
        counters["pressure_event"] = active["id"]

    def _journal(self, now: datetime, guest_names: Mapping[tuple[str, str], str]) -> set[tuple[str, str]]:
        # Revisit a small overlap to tolerate clock/race boundaries. Dedup by
        # journald cursor; never rescan the whole journal on each 10m tick.
        since = (self.last_scan or (now - timedelta(minutes=10))) - timedelta(seconds=5)
        args = [
            "journalctl", "--no-pager", "--quiet", "--output=json",
            # journalctl on Proxmox does not parse ISO-8601 timestamps with
            # microseconds and a timezone offset. @epoch is timezone-safe.
            "_TRANSPORT=kernel", "--since", f"@{int(since.timestamp())}",
            "--until", f"@{int(now.timestamp())}", "--grep", OOM_GREP,
        ]
        try:
            proc = self.journal_run(args, capture_output=True, text=True, timeout=8, check=False)
            if proc.returncode not in (0, 1) or (proc.returncode and proc.stderr.strip()):
                raise RuntimeError(proc.stderr.strip() or f"journalctl rc={proc.returncode}")
            if len(proc.stdout.encode("utf-8")) > JOURNAL_LIMIT_BYTES:
                raise RuntimeError("journal window too large; data not complete")
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            LOG.warning("Недоступен журнал ядра для диагностики памяти: %s", exc)
            self.journal_status = "unknown"
            return set()

        self.journal_status = "ok"
        found: set[tuple[str, str]] = set()
        attempted_events: dict[tuple[str, str], datetime] = {}
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
            if killed and kind == "PVE":
                # Kernel sometimes omits the cgroup from the kill line. Link
                # it only to ONE unambiguous, immediately preceding header.
                candidates = [
                    key for key, header_at in attempted_events.items()
                    if key[0] != "PVE"
                    and 0 <= (at - header_at).total_seconds() <= 3
                ]
                if len(candidates) == 1:
                    kind, guest = candidates[0]
            key = (kind, guest)
            if killed:
                process = re.search(r"Killed process\s+\d+\s+\(([^)]+)\)", message)
                description = "OOM Killer: " + (
                    f"процесс {process.group(1)} уничтожен" if process
                    else "процесс уничтожен"
                )
                self._event(at=at, guest=guest, kind="oom", level="red", description=description)
                found.add(key)
            else:
                # Kernel logs a separate oom-kill header before "Killed
                # process". Do not count the header as a second incident.
                attempted_events.setdefault(key, at)
            self.seen_journal.add(cursor)
        for key, at in attempted_events.items():
            if key not in found:
                self._event(
                    at=at, guest=key[1], kind="oom", level="orange",
                    description="Обнаружен OOM (kill не подтверждён)",
                )
                found.add(key)
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
                self._observe_psi(
                    guest=guest, now=now, psi=psi, previous=previous, counters=counters,
                )
        if psi is not None:
            counters["observed_at"] = now.isoformat()
        counters["identity"] = identity
        self.baselines[name] = counters
        return psi is not None and ev is not None

    def scan(self, now: datetime, inventory: Mapping[str, object] | None) -> dict[str, object]:
        now = now.astimezone(timezone.utc)
        try:
            current_boot_id = (self.proc_root / "sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        except (OSError, UnicodeError):
            current_boot_id = ""
        if current_boot_id:
            if current_boot_id != self.boot_id:
                # Host and cgroup totals restart at zero on every boot, and
                # comparing them across boots can invent pressure/OOM events.
                self.baselines.clear()
            self.boot_id = current_boot_id
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
                self._observe_psi(
                    guest="PVE", now=now, psi=host_psi,
                    previous=host_previous, counters=host_psi,
                )
            host_psi["observed_at"] = now.isoformat()
            self.baselines["PVE"] = host_psi
        else:
            self.baselines.pop("PVE", None)

        raw_lxcs = inventory.get("lxcs", {}) if isinstance(inventory, Mapping) else {}
        lxc_ids = {
            str(guest_id)
            for guest_id, raw in raw_lxcs.items()
            if isinstance(raw, Mapping)
            and str(raw.get("status")) in ("running", "paused")
            and str(guest_id).isdigit()
        } if isinstance(raw_lxcs, Mapping) else set()
        discovered = _lxc_cgroups(self.cgroup_root, lxc_ids)
        for guest_id, path in discovered.items():
            total += 1
            try:
                stat = path.stat()
            except OSError:
                continue
            # cgroup inode changes after LXC restart; reset baseline.
            identity = f"{path}:{stat.st_dev}:{stat.st_ino}"
            if self._sample(f"LXC:{guest_id}", path, now, guest=guest_id, journal_seen=seen, identity=identity):
                ok += 1
        for key in tuple(self.baselines):
            if key.startswith("LXC:") and key[4:] not in discovered:
                self.baselines.pop(key, None)

        cutoff = now - timedelta(days=RETENTION_DAYS)
        self.events = [event for event in self.events if (date := _as_datetime(event.get("at"))) is not None and date >= cutoff]
        self.events.sort(key=lambda event: (str(event.get("at")), int(event.get("id", 0))), reverse=True)
        self.psi_samples = [
            sample for sample in self.psi_samples
            if (date := _as_datetime(sample.get("at"))) is not None and date >= cutoff
        ]
        # Bound the in-memory cursor set as well as the on-disk form.
        if len(self.seen_journal) > 2000:
            self.seen_journal = set(sorted(self.seen_journal)[-2000:])
        # Don't record journal watermark on failure, so the next pass retries
        # the same interval. Persist seen cursors to deduplicate overlap.
        if self.journal_status == "ok":
            self.last_scan = now
        self.pressure_status = (
            "ok" if ok == total and set(discovered) == lxc_ids
            else "unknown"
        )
        self.checked_at = now
        # The retained publisher and local state are deliberately separate.
        self.store.save({
            "events": self.events, "next_id": self.next_id,
            "psi_samples": self.psi_samples,
            "boot_id": self.boot_id,
            "baselines": self.baselines,
            "last_scan": self.last_scan.isoformat() if self.last_scan else None,
            "checked_at": self.checked_at.isoformat(),
            "seen_journal": sorted(self.seen_journal)[-2000:],
        })
        return self.payload()

    def payload(self) -> dict[str, object]:
        # Old releases recorded every nonzero FULL delta. Preserve those
        # legacy events locally, but do not present unverified noise in HA.
        visible = [
            e for e in self.events
            if e.get("kind") != "pressure"
            or e.get("policy") == PRESSURE_EVENT_POLICY
        ]
        return {
            "count": len(visible),
            "events": visible[:PUBLISHED_EVENTS],
            "truncated": len(visible) > PUBLISHED_EVENTS,
            "retention_days": RETENTION_DAYS,
            "journal_status": self.journal_status,
            "pressure_status": self.pressure_status,
            "last_checked": self.checked_at.isoformat() if self.checked_at else None,
        }
