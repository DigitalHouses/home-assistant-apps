"""Read-only Proxmox vzdump run history. No backup jobs or guests are modified."""
from __future__ import annotations

import json
import re
import subprocess
import threading
from datetime import datetime, timezone
from typing import Callable

from .machine_event_outbox import MachineEventOutbox
from .state_store import StateStore

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 50
POLL_SECONDS = 60.0

_START = re.compile(r"Starting Backup of VM (\d+) \((qemu|lxc)\)", re.I)
_END = re.compile(r"Finished Backup of VM (\d+)", re.I)
_FAILURE = re.compile(r"Backup of VM (\d+) failed\s*-\s*(.*)", re.I)
_SKIP = re.compile(r"skip external VMs:\s*([\d, ]+)", re.I)
_JOB = re.compile(r"Job '([^'\n]{1,128})' triggered by schedule", re.I)
_JOB_ARG = re.compile(r"--job-id\s+(?:'([^']+)'|\"([^\"]+)\"|([^\s]+))")
_NAME = re.compile(r"(?:VM|CT) Name:\s*(.+)", re.I)
_ARCHIVE_SIZE = re.compile(r"archive file size:\s*([\d.]+)\s*(B|KB|MB|GB|TB|KiB|MiB|GiB|TiB)\b", re.I)
_PROCESSED_SIZE = re.compile(r"transferred\s+([\d.]+)\s*(B|KB|MB|GB|TB|KiB|MiB|GiB|TiB)\b", re.I)
# PBS LXC logs report how much was newly copied, the logical total and
# compressed bytes separately. Only the second number is comparable to VM's
# logical "transferred" value; it is NOT extra physical PBS usage.
_PXAR_TOTAL = re.compile(
    r"[^\s:]+\.pxar:\s*had to backup\s+[\d.]+\s+"
    r"(?:B|KB|MB|GB|TB|KiB|MiB|GiB|TiB)\s+of\s+"
    r"([\d.]+)\s*(B|KB|MB|GB|TB|KiB|MiB|GiB|TiB)\b", re.I
)
_STORAGE_ARG = re.compile(r"--storage\s+(?:'([^']+)'|\"([^\"]+)\"|([^\s]+))", re.I)

_VALID_NODE = re.compile(r"^[A-Za-z0-9_.-]+$")
_UNITS = {"b": 1, "kb": 1000, "mb": 1000**2, "gb": 1000**3, "tb": 1000**4,
          "kib": 1024, "mib": 1024**2, "gib": 1024**3, "tib": 1024**4}


def _size(match: re.Match[str] | None) -> float | None:
    if match is None:
        return None
    try:
        value = float(match.group(1)) * _UNITS[match.group(2).lower()] / 1024**3
    except (ValueError, OverflowError, KeyError):
        return None
    return round(value, 2) if 0 <= value < 1e9 else None


def _utc(epoch: int | None) -> str | None:
    if type(epoch) is not int or epoch <= 0:
        return None
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def parse_log(lines: list[str], configured_jobs: dict[str, str]) -> dict:
    """Only trust explicit Proxmox guest completion/failure and size log lines."""
    guests: dict[str, dict] = {}
    current: str | None = None
    job_id: str | None = None
    storage: str | None = None
    for line in lines:
        match = _STORAGE_ARG.search(line)
        if match and storage is None:
            storage = next((value for value in match.groups() if value), None)
        match = _JOB.search(line)
        if match:
            job_id = match.group(1)
        if job_id is None:
            match = _JOB_ARG.search(line)
            if match:
                job_id = next((v for v in match.groups() if v), None)
        match = _SKIP.search(line)
        if match:
            for vmid in re.findall(r"\d+", match.group(1)):
                guests.setdefault(vmid, {"id": vmid, "kind": "?", "status": "skipped"})
        match = _START.search(line)
        if match:
            vmid, kind = match.groups()
            current = vmid
            guests[vmid] = {"id": vmid, "kind": "CT" if kind.lower() == "lxc" else "VM",
                            "status": "running"}
            continue
        match = _FAILURE.search(line)
        if match:
            vmid, error = match.groups()
            guest = guests.setdefault(vmid, {"id": vmid, "kind": "?", "status": "unknown"})
            guest["status"] = "failed"
            guest["error"] = error.strip()[:180] or "Ошибка резервного копирования"
            current = None
            continue
        match = _END.search(line)
        if match:
            vmid = match.group(1)
            guest = guests.setdefault(vmid, {"id": vmid, "kind": "?", "status": "unknown"})
            if guest["status"] != "failed":
                guest["status"] = "success"
            current = None
            continue
        if current is not None and current in guests:
            match = _NAME.search(line)
            if match:
                guests[current]["name"] = match.group(1).strip()[:80]
            match = _ARCHIVE_SIZE.search(line)
            if match:
                value = _size(match)
                if value is not None:
                    guests[current]["size_gib"] = value
                    guests[current]["size_kind"] = "archive"
            else:
                match = _PROCESSED_SIZE.search(line)
                if match and guests[current].get("size_kind") != "archive":
                    value = _size(match)
                    if value is not None:
                        guests[current]["size_gib"] = value
                        guests[current]["size_kind"] = "processed"
                match = _PXAR_TOTAL.search(line)
                if match and guests[current].get("size_kind") != "archive":
                    value = _size(match)
                    if value is not None:
                        guests[current]["size_gib"] = round(
                            guests[current].get("size_gib", 0) + value, 2
                        )
                        guests[current]["size_kind"] = "processed"
    label = configured_jobs.get(job_id, job_id) if job_id else (
        f"vzdump · {storage}" if storage else "vzdump"
    )
    return {"job_id": job_id, "label": label, "guests": list(guests.values())}


def _status(row: dict, parsed: dict) -> str:
    raw = str(row.get("exitstatus") or row.get("status") or "").strip()
    endtime = row.get("endtime")
    if raw.upper() == "RUNNING":
        return "running"
    if any(g["status"] == "failed" for g in parsed["guests"]):
        return "failed"
    if raw.upper() == "OK":
        return "success"
    if raw and raw.lower() not in {"running", "stopped", "unknown", "none"}:
        return "failed"
    return "unknown"


def build_run(row: dict, parsed: dict) -> dict:
    started = row.get("starttime")
    finished = row.get("endtime")
    duration = (finished - started if type(finished) is int and type(started) is int
                and 0 <= finished-started < 31536000 else None)
    status = _status(row, parsed)
    guests = parsed["guests"]
    if status != "running":
        for guest in guests:
            if guest["status"] == "running":
                guest["status"] = "unknown"
    sizes = [g["size_gib"] for g in guests if g.get("status") == "success"
             and type(g.get("size_gib")) in {float, int}]
    kinds = {g.get("size_kind") for g in guests if "size_gib" in g}
    # Only aggregate complete, consistently measured guest sizes.
    total = (round(sum(sizes), 2) if status == "success" and sizes
             and len(sizes) == len([g for g in guests if g["status"] == "success"])
             and len(kinds) == 1 else None)
    result = {"upid": str(row["upid"]), "started_at": _utc(started),
              "ended_at": _utc(finished), "duration_seconds": duration,
              "status": status, "label": parsed["label"], "job_id": parsed["job_id"],
              "size_gib": total, "size_kind": next(iter(kinds)) if total is not None else None,
              "guests": guests}
    if status == "failed":
        result["error"] = str(row.get("exitstatus") or row.get("status") or "Ошибка")[:180]
    return result


def run_api(argv: list[str]) -> object:
    """Use only pvesh GET with a fixed read-only command shape."""
    proc = subprocess.run(argv, check=True, capture_output=True, text=True, timeout=10)
    return json.loads(proc.stdout)


class BackupReader:
    def __init__(self, node: str, api: Callable[[list[str]], object] = run_api):
        if not _VALID_NODE.fullmatch(node) or node in {".", ".."}:
            raise ValueError("Invalid PVE node")
        self.node = node
        self.api = api
        self._cancel = threading.Event()
        self._logs: dict[str, dict] = {}

    def cancel(self) -> None:
        self._cancel.set()

    def _get(self, path: str, *args: str) -> object:
        return self.api(["pvesh", "get", path, *args, "--output-format", "json"])

    def read(self, limit: int) -> dict:
        if type(limit) is not int or not MIN_LIMIT <= limit <= MAX_LIMIT:
            raise ValueError("invalid history limit")
        jobs: dict[str, str] = {}
        job_coverage = "available"
        try:
            configured = self._get("/cluster/backup")
            if not isinstance(configured, list):
                raise ValueError("invalid backup jobs API response")
            for raw in configured:
                if isinstance(raw, dict) and raw.get("id"):
                    ident = str(raw["id"])
                    jobs[ident] = str(raw.get("comment") or ident)[:100]
        except (OSError, subprocess.SubprocessError, ValueError, TypeError):
            job_coverage = "unavailable"
        tasks = self._get(f"/nodes/{self.node}/tasks", "--typefilter", "vzdump",
                          "--source", "all", "--limit", str(max(100, limit * 2)))
        if not isinstance(tasks, list):
            raise ValueError("invalid vzdump task API response")
        rows = [x for x in tasks if isinstance(x, dict) and x.get("type") == "vzdump"
                and isinstance(x.get("upid"), str)
                and type(x.get("starttime")) is int]
        rows.sort(key=lambda x: x["starttime"], reverse=True)
        runs = []
        for row in rows[:limit]:
            if self._cancel.is_set():
                raise InterruptedError("PVE backup history scanner is stopping")
            upid = row["upid"]
            # Completed logs do not change; refresh only running tasks.
            cached = self._logs.get(upid)
            if cached is None or cached["status"] == "running" or not cached.get("log_available", False):
                try:
                    response = self._get(f"/nodes/{self.node}/tasks/{upid}/log", "--limit", "5000")
                    if not isinstance(response, list):
                        raise ValueError("invalid task log")
                    lines = [str(x.get("t")) for x in response if isinstance(x, dict)
                             and isinstance(x.get("t"), str)]
                    parsed = parse_log(lines, jobs)
                    cached = build_run(row, parsed)
                    cached["log_available"] = True
                    self._logs[upid] = cached
                except (OSError, subprocess.SubprocessError, ValueError, TypeError):
                    cached = build_run(row, {"job_id": None, "label": "vzdump", "guests": []})
                    cached["log_available"] = False
            else:
                cached = dict(cached)
                if cached.get("job_id") in jobs:
                    cached["label"] = jobs[cached["job_id"]]
            runs.append(cached)
        # Bound the cache even when the limit is reduced.
        keep = {r["upid"] for r in runs}
        self._logs = {key: item for key, item in self._logs.items() if key in keep}
        return {"coverage": "available", "jobs_coverage": job_coverage,
                "runs": runs, "observed_at": datetime.now(timezone.utc).isoformat()}


class BackupHistory:
    """Persistent MQTT Number and restart-safe terminal event de-duplication."""

    def __init__(self, store: StateStore, outbox: MachineEventOutbox):
        self.store = store
        self.outbox = outbox
        state = self.store.load()
        value = state.get("limit", DEFAULT_LIMIT)
        self.limit = value if type(value) is int and MIN_LIMIT <= value <= MAX_LIMIT else DEFAULT_LIMIT
        self.baseline = state.get("baseline") is True
        self.observed = dict(state.get("observed") or {})
        self.last_scan = state.get("last_scan")
        self.snapshot = {"coverage": "unavailable", "runs": [], "observed_at": None}

    def _persist(self) -> None:
        self.store.save({"limit": self.limit, "baseline": self.baseline,
                         "observed": self.observed, "last_scan": self.last_scan})

    def set_limit(self, value: int) -> bool:
        if type(value) is not int or not MIN_LIMIT <= value <= MAX_LIMIT:
            return False
        if self.limit != value:
            self.limit = value
            self._persist()
        return True

    def process(self, snapshot: dict) -> None:
        self.snapshot = snapshot
        if snapshot.get("coverage") != "available":
            return
        last_scan = self.last_scan
        current: dict[str, str] = {}
        for run in snapshot["runs"]:
            upid, status = run["upid"], run["status"]
            current[upid] = status
            prev = self.observed.get(upid)
            should_emit = (
                self.baseline and status in {"success", "failed"}
                and prev != status
                and (prev == "running" or (
                    prev is None and isinstance(last_scan, int)
                    and run.get("ended_at") is not None
                    and datetime.fromisoformat(run["ended_at"]).timestamp() >= last_scan
                ))
            )
            if should_emit:
                kind = "backup_job_completed" if status == "success" else "backup_job_failed"
                self.outbox.enqueue(upid, {
                    "event_type": kind, "event_id": upid, "job_id": run["job_id"],
                    "job_name": run["label"], "started_at": run["started_at"],
                    "ended_at": run["ended_at"], "duration_seconds": run["duration_seconds"],
                    "guests": [{"id": g["id"], "kind": g["kind"], "status": g["status"]}
                               for g in run["guests"]],
                })
        self.observed = dict(list({**self.observed, **current}.items())[-200:])
        self.last_scan = int(datetime.now(timezone.utc).timestamp())
        self.baseline = True
        self._persist()

    def view(self) -> dict:
        """Bound sensor attributes to HA's 16 KiB attribute-size limit."""
        runs = []
        for item in self.snapshot.get("runs", []):
            guests = [{
                "id": g["id"], "k": g["kind"], "s": g["status"],
                **({"n": g["name"]} if g.get("name") else {}),
                **({"z": g["size_gib"], "t": g.get("size_kind")} if "size_gib" in g else {}),
                **({"e": g["error"]} if g.get("error") else {}),
            } for g in item.get("guests", [])]
            runs.append({
                "d": item.get("started_at"), "n": item.get("label"),
                "s": item.get("status"), "m": item.get("duration_seconds"),
                "z": item.get("size_gib"), "k": item.get("size_kind"),
                "g": guests,
                **({"e": item["error"]} if item.get("error") else {}),
            })
        limited = False
        # Preserve every run header first; guest lists are optional when 50
        # large jobs would exceed Home Assistant's entity attribute limit.
        headers = [{**run, "g": []} for run in runs]
        output = [dict(row) for row in headers]
        # Error details win over success details when the HA size cap is tight.
        order = sorted(range(len(runs)), key=lambda i: (runs[i]["s"] not in {"failed", "running", "unknown"}, i))
        for index in order:
            row = runs[index]
            candidate = dict(headers[index], g=row["g"])
            output[index] = candidate
            if len(json.dumps(output, ensure_ascii=True).encode("utf-8")) > 12500:
                output[index] = headers[index]
                if row["g"]:
                    limited = True
        return {
            "status": str(len(output)) if self.snapshot.get("coverage") == "available"
                      else "unavailable",
            "coverage": self.snapshot.get("coverage", "unavailable"),
            "jobs_coverage": self.snapshot.get("jobs_coverage", "unavailable"),
            "observed_at": self.snapshot.get("observed_at"),
            "details_limited": limited,
            "runs": output,
        }

    def flush_events(self, publisher: Callable[[dict], bool]) -> None:
        for item in self.outbox.pending():
            if not publisher(item.payload):
                break
            self.outbox.acknowledge(item.key)
