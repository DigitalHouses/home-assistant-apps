"""Read-only HOME PVE backup job and guest coverage monitor.

PVE owns job schedules and UPID/jobstate. PBS is deliberately not contacted.
If PVE cannot prove a per-guest result, the result is UNKNOWN, never OK.
"""
from __future__ import annotations

import json
import re
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .state_store import StateStore

POLL_SECONDS = 300
STATE_SCHEMA = 1
UPID_RE = re.compile(r"^UPID:([^:]+):(?:[^:]*:){3}([0-9A-Fa-f]+):vzdump:")
START_RE = re.compile(r"\bStarting Backup of VM (\d+)\b", re.I)
FINISH_RE = re.compile(r"\bFinished Backup of VM (\d+)\b", re.I)
FAIL_RE = re.compile(r"\bBackup of VM (\d+) failed\b(.*)", re.I)
SKIP_RE = re.compile(r"\b(?:Skip(?:ping|ped)? Backup of VM|Backup of VM) (\d+)\b.*\bskip", re.I)


def _utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _vmids(value: object) -> set[int]:
    if value is None or value == "":
        return set()
    if isinstance(value, int):
        return {value}
    if not isinstance(value, str):
        raise ValueError("invalid PVE vmid selection")
    values: set[int] = set()
    for part in value.split(","):
        token = part.strip()
        if not token.isdecimal() or int(token) <= 0:
            raise ValueError("invalid PVE vmid selection")
        values.add(int(token))
    return values


def _bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if value in (True, 1, "1", "true", "yes"):
        return True
    if value in (False, 0, "0", "false", "no"):
        return False
    raise ValueError("invalid PVE backup flag")


def select_members(
    job: dict[str, Any],
    guests: dict[int, dict[str, Any]],
    pool_members: set[int] | None = None,
) -> list[int]:
    """Resolve supported PVE selection modes, failing closed for ambiguity."""
    excluded = _vmids(job.get("exclude"))
    all_mode = _bool(job.get("all"))
    pool = str(job.get("pool") or "").strip()
    explicit = _vmids(job.get("vmid"))
    if pool and pool_members is None:
        raise ValueError("PVE pool inventory unavailable")
    if pool and (all_mode or explicit):
        raise ValueError("ambiguous PVE pool selection")
    if pool:
        selected = set(pool_members or set())
    elif all_mode:
        selected = set(guests)
    elif explicit:
        selected = explicit
    else:
        # A job with no recognizable selector must not imply empty coverage.
        raise ValueError("PVE job has no supported guest selection")
    return sorted((selected - excluded) & guests.keys())


def parse_guest_log(lines: list[str]) -> dict[int, dict[str, str]]:
    """Only explicit per-guest log evidence establishes success or failure."""
    results: dict[int, dict[str, str]] = {}
    for raw in lines:
        failed = FAIL_RE.search(raw)
        if failed:
            vmid = int(failed.group(1))
            results[vmid] = {
                "status": "FAILED",
                "reason": failed.group(2).strip(" :-")[:300],
            }
            continue
        skipped = SKIP_RE.search(raw)
        if skipped:
            vmid = int(skipped.group(1))
            if results.get(vmid, {}).get("status") != "FAILED":
                results[vmid] = {"status": "SKIPPED", "reason": raw[-200:]}
            continue
        finished = FINISH_RE.search(raw)
        if finished:
            vmid = int(finished.group(1))
            if results.get(vmid, {}).get("status") != "FAILED":
                results[vmid] = {"status": "OK", "reason": ""}
            continue
        started = START_RE.search(raw)
        if started:
            vmid = int(started.group(1))
            results.setdefault(vmid, {"status": "RUNNING", "reason": ""})
    return results


def summarize_task(
    expected: list[int],
    task: dict[str, Any],
    log_lines: list[str] | None,
) -> tuple[str, list[dict[str, object]]]:
    status = str(task.get("status", "")).lower()
    running = status in ("running", "active")
    exitstatus = task.get("exitstatus")
    if not running and status not in ("stopped", "finished") and exitstatus is None:
        return "UNKNOWN", [{"vmid": vmid, "status": "UNKNOWN", "reason": ""} for vmid in expected]
    evidence = parse_guest_log(log_lines) if log_lines is not None else {}
    complete = not running
    # A completed, readable task log containing per-guest markers is evidence
    # that absent expected participants were not processed. No log => UNKNOWN.
    has_evidence = bool(evidence)
    details: list[dict[str, object]] = []
    for vmid in expected:
        item = evidence.get(vmid)
        if item is None:
            result = "MISSING" if complete and has_evidence else ("RUNNING" if running else "UNKNOWN")
            details.append({"vmid": vmid, "status": result, "reason": ""})
        else:
            result = item["status"]
            if complete and result == "RUNNING":
                result = "UNKNOWN"
            details.append({"vmid": vmid, "status": result, "reason": item["reason"]})
    if running:
        return "RUNNING", details
    successes = sum(item["status"] == "OK" for item in details)
    failures = sum(item["status"] in ("FAILED", "MISSING") for item in details)
    unknowns = sum(item["status"] in ("UNKNOWN", "RUNNING") for item in details)
    if failures:
        return ("PARTIAL" if successes else "FAILED"), details
    if unknowns or not expected or any(item["status"] == "SKIPPED" for item in details):
        return "UNKNOWN", details
    if exitstatus != "OK":
        return "FAILED", details
    return "OK", details


class PveBackupMonitor:
    """Periodic scanner with a compact persisted transition baseline."""

    def __init__(
        self,
        store: StateStore,
        *,
        excluded_vmids: tuple[int, ...] = (),
        grace_seconds: int = 900,
        runner: Callable[[list[str]], str] | None = None,
        now: Callable[[], float] = time.time,
        jobstate_dir: Path = Path("/var/lib/pve-manager/jobs"),
        node: str | None = None,
    ) -> None:
        self.store = store
        self.excluded_vmids = set(excluded_vmids)
        self.grace_seconds = grace_seconds
        self.runner = runner or self._run
        self.now = now
        self.jobstate_dir = jobstate_dir
        self.node = node or socket.gethostname().split(".")[0]

    @staticmethod
    def _run(argv: list[str]) -> str:
        result = subprocess.run(
            argv, capture_output=True, text=True, check=True, timeout=18,
        )
        return result.stdout

    def _api(self, path: str, **params: object) -> Any:
        argv = ["pvesh", "get", path]
        for key, value in params.items():
            argv.extend(["--" + key.replace("_", "-"), str(value)])
        argv.extend(["--output-format", "json"])
        return json.loads(self.runner(argv))

    def _job_state(self, job_id: str) -> dict[str, object]:
        # This is PVE's native scheduler state, not a second agent database.
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", job_id):
            raise ValueError("invalid job id")
        path = self.jobstate_dir / ("vzdump-" + job_id + ".json")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _task(self, upid: str) -> tuple[dict[str, Any], list[str] | None]:
        parts = upid.split(":")
        if len(parts) < 8 or parts[0] != "UPID" or parts[5] != "vzdump":
            raise ValueError("unexpected PVE vzdump UPID")
        node = parts[1]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", node):
            raise ValueError("invalid PVE node in UPID")
        status = self._api(f"/nodes/{node}/tasks/{upid}/status")
        if not isinstance(status, dict):
            raise ValueError("invalid PVE task status")
        if str(status.get("status", "")).lower() == "running":
            return status, None
        log = self._api(f"/nodes/{node}/tasks/{upid}/log", limit=5000)
        if not isinstance(log, list) or any(not isinstance(item, dict) for item in log):
            raise ValueError("invalid PVE task log")
        return status, [str(item.get("t", "")) for item in log]

    @staticmethod
    def _task_started_at(upid: str) -> int | None:
        parts = upid.split(":")
        try:
            return int(parts[4], 16) if len(parts) >= 8 else None
        except ValueError:
            return None

    def _members(self, job: dict[str, Any], guests: dict[int, dict[str, Any]]) -> list[int]:
        pool_members = None
        if job.get("pool"):
            pool = str(job["pool"])
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", pool):
                raise ValueError("invalid PVE pool")
            data = self._api(f"/pools/{pool}")
            if not isinstance(data, dict) or not isinstance(data.get("members"), list):
                raise ValueError("PVE pool inventory unavailable")
            pool_members = set()
            for item in data["members"]:
                if not isinstance(item, dict):
                    raise ValueError("invalid PVE pool member")
                vmid = item.get("vmid")
                if vmid is not None and str(vmid).isdigit():
                    pool_members.add(int(vmid))
        return select_members(job, guests, pool_members)

    def scan(self) -> tuple[dict[str, object], list[dict[str, object]]]:
        observed = self.now()
        stamp = _utc(observed)
        prior = self.store.load()
        try:
            guest_rows = self._api("/cluster/resources", type="vm")
            job_rows = self._api("/cluster/backup")
            if not isinstance(guest_rows, list) or not isinstance(job_rows, list):
                raise ValueError("PVE inventory must be a list")
            guests: dict[int, dict[str, Any]] = {}
            for row in guest_rows:
                if not isinstance(row, dict) or not str(row.get("vmid", "")).isdigit():
                    raise ValueError("invalid PVE guest row")
                vmid = int(row["vmid"])
                if row.get("node") and str(row["node"]) != self.node:
                    continue
                guests[vmid] = {
                    "vmid": vmid, "name": str(row.get("name") or f"VM {vmid}"),
                    "type": str(row.get("type") or "unknown"),
                    "status": str(row.get("status") or "unknown"),
                    "job_ids": [], "coverage": "UNCOVERED",
                }
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return ({
                "schema_version": STATE_SCHEMA, "status": "UNAVAILABLE",
                "observed_at": stamp, "last_success_at": prior.get("last_success_at"),
                "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                "guests": [], "jobs": [], "summary": None,
            }, [])

        previous_jobs = prior.get("jobs", {}) if isinstance(prior.get("jobs"), dict) else {}
        previous_guests = prior.get("guests", {}) if isinstance(prior.get("guests"), dict) else {}
        job_next: dict[str, Any] = {}
        events: list[dict[str, object]] = []
        jobs: list[dict[str, object]] = []
        unknown_selection = False

        def emit(kind: str, **fields: object) -> None:
            events.append({"schema_version": 1, "event_type": kind, "observed_at": stamp, **fields})

        for source in job_rows:
            if not isinstance(source, dict) or not source.get("id"):
                unknown_selection = True
                continue
            job_id = str(source["id"])
            if source.get("node") and str(source["node"]) != self.node:
                continue
            enabled = _bool(source.get("enabled"), True)
            record: dict[str, Any] = {
                "job_id": job_id,
                "name": str(source.get("comment") or job_id),
                "enabled": enabled,
                "schedule": str(source.get("schedule") or ""),
                "storage": str(source.get("storage") or ""),
                "members": [],
                "status": "UNKNOWN",
                "upid": None,
                "started_at": None,
                "finished_at": None,
            }
            old = previous_jobs.get(job_id, {}) if isinstance(previous_jobs.get(job_id), dict) else {}
            try:
                members = self._members(source, guests)
                record["members"] = [
                    {"vmid": vmid, "name": guests[vmid]["name"], "type": guests[vmid]["type"],
                     "status": "UNKNOWN", "reason": ""}
                    for vmid in members
                ]
                if enabled:
                    for vmid in members:
                        guests[vmid]["job_ids"].append(job_id)
                if not enabled:
                    record["status"] = "DISABLED"
                    job_next[job_id] = {"status": "DISABLED", "upid": None}
                    jobs.append(record)
                    continue
                jobstate = self._job_state(job_id)
                upid = source.get("last-run-upid") or jobstate.get("upid")
                if upid is not None:
                    upid = str(upid)
                record["upid"] = upid
                record["started_at"] = _utc(self._task_started_at(upid)) if upid and self._task_started_at(upid) else None
                next_run_raw = source.get("next-run")
                next_run = int(next_run_raw) if next_run_raw is not None else None
                record["next_run"] = _utc(next_run) if next_run else None
                due = old.get("due") if old.get("schedule") == record["schedule"] else None
                if not isinstance(due, int):
                    due = next_run
                previous_upid = old.get("upid")
                missed = (
                    isinstance(due, int) and observed > due + self.grace_seconds
                    and (not upid or self._task_started_at(upid) is None
                         or self._task_started_at(upid) < due - self.grace_seconds)
                    and old.get("schedule") == record["schedule"]
                )
                if upid:
                    task, logs = self._task(upid)
                    state, members_state = summarize_task(members, task, logs)
                    for member in members_state:
                        vmid = int(member["vmid"])
                        member["name"] = guests[vmid]["name"]
                        member["type"] = guests[vmid]["type"]
                    record["members"] = members_state
                    record["status"] = state
                    if task.get("endtime"):
                        record["finished_at"] = _utc(float(task["endtime"]))
                if missed and record["status"] != "RUNNING":
                    record["status"] = "MISSED"
                if next_run is not None and (due is None or next_run > due and (missed or self._task_started_at(upid or "") is not None and self._task_started_at(upid or "") >= due - self.grace_seconds)):
                    due = next_run
                job_next[job_id] = {
                    "status": record["status"], "upid": upid, "due": due,
                    "schedule": record["schedule"],
                    "member_statuses": {str(x["vmid"]): x["status"] for x in record["members"]},
                }
                if record["status"] in ("FAILED", "PARTIAL") and (
                    old.get("upid"), old.get("status")
                ) != (upid, record["status"]):
                    emit("backup_job_failed", job_id=job_id, job_name=record["name"],
                         task_id=upid, result=record["status"])
                elif record["status"] == "MISSED" and old.get("status") != "MISSED":
                    emit("backup_job_missed", job_id=job_id, job_name=record["name"],
                         expected_at=_utc(due) if due else stamp)
                elif record["status"] == "OK" and old.get("status") in ("FAILED", "PARTIAL", "MISSED"):
                    emit("backup_job_recovered", job_id=job_id, job_name=record["name"], task_id=upid)
                old_members = old.get("member_statuses", {}) if isinstance(old.get("member_statuses"), dict) else {}
                for member in record["members"]:
                    status = str(member["status"])
                    vmid = int(member["vmid"])
                    old_status = old_members.get(str(vmid))
                    if status in ("FAILED", "MISSING") and (
                        old.get("upid") != upid or old_status != status
                    ):
                        emit("backup_guest_failed" if status == "FAILED" else "backup_guest_missing",
                             job_id=job_id, job_name=record["name"], task_id=upid,
                             vmid=vmid, guest_name=str(member["name"]),
                             guest_type=str(member["type"]), result=status,
                             reason=str(member.get("reason") or ""))
                    elif status == "OK" and old_status in ("FAILED", "MISSING"):
                        emit("backup_guest_recovered", job_id=job_id, job_name=record["name"],
                             task_id=upid, vmid=vmid, guest_name=str(member["name"]),
                             guest_type=str(member["type"]), recovery_reason="backup_succeeded")
            except (OSError, subprocess.SubprocessError, ValueError, TypeError) as exc:
                record["status"] = "UNKNOWN"
                record["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
                unknown_selection = True
                job_next[job_id] = old
            jobs.append(record)

        next_guest: dict[str, str] = {}
        for guest in sorted(guests.values(), key=lambda item: item["vmid"]):
            vmid = int(guest["vmid"])
            if guest["job_ids"]:
                guest["coverage"] = "COVERED"
            elif vmid in self.excluded_vmids:
                guest["coverage"] = "EXCLUDED"
            elif unknown_selection:
                guest["coverage"] = "UNKNOWN"
            else:
                guest["coverage"] = "UNCOVERED"
            next_guest[str(vmid)] = str(guest["coverage"])
            previous = previous_guests.get(str(vmid))
            if guest["coverage"] == "UNCOVERED" and previous != "UNCOVERED":
                emit("backup_guest_uncovered", vmid=vmid, guest_name=str(guest["name"]),
                     guest_type=str(guest["type"]))
            elif guest["coverage"] == "COVERED" and previous == "UNCOVERED":
                emit("backup_guest_recovered", vmid=vmid, guest_name=str(guest["name"]),
                     guest_type=str(guest["type"]), recovery_reason="coverage_restored")
        job_counts = {status: sum(item["status"] == status for item in jobs)
                      for status in ("OK", "PARTIAL", "FAILED", "MISSED", "RUNNING", "DISABLED", "UNKNOWN")}
        coverage_counts = {status.lower(): sum(g["coverage"] == status for g in guests.values())
                           for status in ("COVERED", "EXCLUDED", "UNCOVERED", "UNKNOWN")}
        status = "UNKNOWN" if unknown_selection or job_counts["UNKNOWN"] else (
            "PROBLEM" if coverage_counts["uncovered"] or any(job_counts[s] for s in ("PARTIAL", "FAILED", "MISSED"))
            else "OK"
        )
        payload: dict[str, object] = {
            "schema_version": STATE_SCHEMA, "status": status,
            "observed_at": stamp, "last_success_at": stamp,
            "guests": sorted(guests.values(), key=lambda x: x["vmid"]),
            "jobs": sorted(jobs, key=lambda x: str(x["job_id"])),
            "summary": {
                "total_guests": len(guests), **coverage_counts,
                "total_jobs": len(jobs), "job_statuses": job_counts,
            },
        }
        self.store.save({
            "last_success_at": stamp, "jobs": job_next, "guests": next_guest,
        })
        return payload, events
