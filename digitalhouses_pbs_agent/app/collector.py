"""Read-only Proxmox Backup Server 4.x HTTPS API and native ZFS observations."""
from __future__ import annotations

import json
import os
import ssl
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .config import Config


class SourceError(RuntimeError):
    pass


def utc(value: int | float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def age_hours(now: float, timestamp: int | float | None) -> float | None:
    return round(max(0, (now - timestamp) / 3600), 2) if timestamp is not None else None


def last_run(row: dict) -> dict:
    """PBS admin job rows expose last-run-state/upids; never infer success."""
    raw = row.get("last-run-state")
    if raw is None:
        status = "UNKNOWN" if row.get("last-run-upid") else "NEVER_RUN"
    elif isinstance(raw, str):
        status = "OK" if raw.lower() == "ok" else "FAILED"
    elif isinstance(raw, dict):
        kind = raw.get("status") or raw.get("state")
        status = "OK" if isinstance(kind, str) and kind.lower() == "ok" else (
            "FAILED" if isinstance(kind, str) and kind.lower() in ("error", "failed") else "UNKNOWN"
        )
    else:
        status = "UNKNOWN"
    when = row.get("last-run-endtime")
    try:
        timestamp = int(when) if when is not None else None
    except (TypeError, ValueError):
        timestamp = None
    return {
        "status": status,
        "last_run_at": utc(timestamp) if timestamp is not None else None,
        "last_run_timestamp": timestamp,
        "upid": row.get("last-run-upid"),
        "schedule": row.get("schedule"),
        "next_run_timestamp": row.get("next-run"),
    }


class PBSClient:
    def __init__(self, config: Config):
        self.config = config
        self._context = (
            ssl._create_unverified_context()
            if config.pbs_insecure_localhost
            else ssl.create_default_context(cafile=config.pbs_ca_file or None)
        )

    def get(self, path: str, **params: object):
        if not self.config.pbs_token_id:
            raise SourceError("pbs.token_id is not configured")
        try:
            secret = self.config.pbs_token_secret_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise SourceError("PBS token secret file cannot be read") from exc
        if not secret or "\n" in secret or "\r" in secret:
            raise SourceError("PBS token secret file is empty or invalid")
        url = f"{self.config.pbs_url}/api2/json/{path.lstrip('/')}"
        if params:
            url += "?" + urlencode({k: v for k, v in params.items() if v is not None})
        req = Request(url, headers={"Authorization": f"PBSAPIToken {self.config.pbs_token_id}:{secret}"})
        try:
            with urlopen(req, timeout=12, context=self._context) as resp:
                body = json.load(resp)
        except HTTPError as exc:
            raise SourceError(f"PBS API HTTP {exc.code} on {path}") from exc
        except (URLError, TimeoutError, ValueError, OSError) as exc:
            raise SourceError(f"PBS API unavailable on {path}: {type(exc).__name__}") from exc
        if not isinstance(body, dict) or "data" not in body:
            raise SourceError(f"invalid PBS API response at {path}")
        return body["data"]


def zfs_pools() -> dict:
    try:
        proc = subprocess.run(
            ["zpool", "list", "-Hp", "-o", "name,health"],
            capture_output=True, text=True, check=False, timeout=7,
        )
    except FileNotFoundError:
        return {"status": "NOT_APPLICABLE", "pools": []}
    except (OSError, subprocess.SubprocessError):
        return {"status": "UNKNOWN", "pools": []}
    if proc.returncode:
        return {"status": "UNKNOWN", "pools": []}
    pools = []
    for line in proc.stdout.splitlines():
        split = line.split("\t")
        if len(split) != 2:
            return {"status": "UNKNOWN", "pools": []}
        pools.append({"pool": split[0], "health": split[1]})
    state = "NOT_APPLICABLE" if not pools else (
        "HEALTHY" if all(x["health"] == "ONLINE" for x in pools) else "DEGRADED"
    )
    return {"status": state, "pools": pools}


def root_filesystem() -> dict:
    try:
        v = os.statvfs("/")
        return {
            "mountpoint": "/", "total_bytes": v.f_blocks * v.f_frsize,
            "available_bytes": v.f_bavail * v.f_frsize,
            "used_bytes": (v.f_blocks - v.f_bfree) * v.f_frsize,
        }
    except OSError:
        return {"mountpoint": "/", "status": "UNAVAILABLE"}


def _job_id(row: dict) -> str:
    return str(row.get("id") or row.get("job-id") or "")


def _store_status(pbs: PBSClient, store: str, now: float) -> dict:
    encoded = quote(store, safe="")
    status = pbs.get(f"admin/datastore/{encoded}/status")
    if not isinstance(status, dict):
        raise SourceError("PBS datastore status response is not an object")
    total, used, available = (status.get(key) for key in ("total", "used", "avail"))
    if not all(isinstance(val, (int, float)) and not isinstance(val, bool) for val in (total, used, available)):
        raise SourceError("PBS datastore capacity fields are absent")
    if total <= 0 or min(used, available) < 0:
        raise SourceError("PBS datastore capacity values are invalid")
    return {
        "name": store, "status": "AVAILABLE",
        "total_bytes": int(total), "used_bytes": int(used),
        "available_bytes": int(available),
        "used_percent": round(100 * used / total, 2),
    }


def _snapshots(pbs: PBSClient, store: str, ns: str) -> list[dict]:
    encoded = quote(store, safe="")
    result = pbs.get(f"admin/datastore/{encoded}/snapshots", ns=ns if ns else None)
    if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
        raise SourceError("PBS snapshots response is invalid")
    return result


def collect(config: Config, pbs: PBSClient | None = None, now: float | None = None) -> dict:
    """Each missing source yields UNKNOWN/UNAVAILABLE, never healthy zeroes."""
    pbs = pbs or PBSClient(config)
    now = time.time() if now is None else now
    stamp = utc(now)
    result: dict = {
        "observed_at": stamp, "status": "UNAVAILABLE", "pbs_version": None,
        "datastores": [], "backups": [], "backup_sessions": {"active": None, "failed_tasks": [], "last_error": None}, "sync_jobs": [], "verify_jobs": [],
        "prune_jobs": [], "gc": [], "zfs": zfs_pools(),
        "root_fs": root_filesystem(), "errors": [], "problems": [],
        "summary": {},
    }
    problems = result["problems"]
    try:
        version = pbs.get("version")
        if not isinstance(version, dict):
            raise SourceError("PBS version response is invalid")
        result["pbs_version"] = str(version.get("version") or "unknown")
    except SourceError as exc:
        result["errors"].append(str(exc))
        problems.append({"key": "pbs:service", "type": "service_unavailable",
                         "category": "backup", "facts": {"source": "pbs_api"}})
        return result

    statuses: list[str] = []
    for store in config.datastores:
        try:
            info = _store_status(pbs, store, now)
            pct = info["used_percent"]
            severity = "CRITICAL" if pct >= config.critical_percent else (
                "DEGRADED" if pct >= config.warning_percent else "HEALTHY"
            )
            info["health"] = severity
            statuses.append(severity)
            if severity != "HEALTHY":
                problems.append({
                    "key": f"capacity:{store}", "type": "disk_space_low",
                    "category": "storage", "facts": {
                        "datastore": store, "used_percent": pct,
                        "available_bytes": info["available_bytes"],
                        "threshold_percent": (
                            config.critical_percent if severity == "CRITICAL"
                            else config.warning_percent
                        ),
                    },
                })
        except SourceError as exc:
            info = {"name": store, "status": "UNAVAILABLE", "health": "UNAVAILABLE"}
            statuses.append("UNAVAILABLE")
            result["errors"].append(f"{store}: {exc}")
        result["datastores"].append(info)

    snapshot_cache: dict[tuple[str, str], list[dict] | None] = {}
    for rule in config.backup_rules:
        key = (rule.datastore, rule.namespace)
        if key not in snapshot_cache:
            try:
                snapshot_cache[key] = _snapshots(pbs, *key)
            except SourceError as exc:
                result["errors"].append(f"snapshots {key}: {exc}")
                snapshot_cache[key] = None
        snapshots = snapshot_cache[key]
        item = {"datastore": rule.datastore, "namespace": rule.namespace,
                "group": rule.group, "max_age_hours": rule.max_age_hours}
        if snapshots is None:
            item.update(status="UNAVAILABLE", last_success_at=None, age_hours=None)
            statuses.append("UNAVAILABLE")
        else:
            typ, identity = rule.group.split("/", 1)
            candidates = []
            for s in snapshots:
                if s.get("backup-type") == typ and str(s.get("backup-id")) == identity:
                    val = s.get("backup-time")
                    if isinstance(val, int) and val > 0 and val <= now + 300:
                        candidates.append(val)
            last = max(candidates) if candidates else None
            age = age_hours(now, last)
            stale = age is None or age > rule.max_age_hours
            item.update(status="NO_SNAPSHOT" if last is None else (
                "OVERDUE" if stale else "OK"),
                last_success_at=utc(last) if last else None, age_hours=age)
            if stale:
                statuses.append("CRITICAL")
                problems.append({
                    "key": f"backup:{rule.datastore}:{rule.namespace}:{rule.group}",
                    "type": "backup_overdue", "category": "backup",
                    "facts": {"datastore": rule.datastore, "namespace": rule.namespace,
                              "backup_group": rule.group, "age_hours": age,
                              "threshold_hours": rule.max_age_hours,
                              "reason_code": "no_snapshot" if last is None else "overdue"},
                })
        result["backups"].append(item)

    # PBS owns backup receive sessions, not the PVE vzdump schedule.
    # Report an actual failed server-side backup task only with a real UPID.
    try:
        task_rows = pbs.get("nodes/localhost/tasks", limit=100, typefilter="backup")
        if not isinstance(task_rows, list) or any(not isinstance(x, dict) for x in task_rows):
            raise SourceError("PBS task list is invalid")
        active = 0
        failed_tasks = []
        for task in task_rows:
            worker_type = str(task.get("worker_type") or task.get("worker-type") or "")
            if not worker_type.startswith("backup"):
                continue
            upid = task.get("upid")
            if not isinstance(upid, str) or not upid.startswith("UPID:"):
                continue
            status_text = task.get("status")
            if not task.get("endtime"):
                active += 1
                continue
            if isinstance(status_text, str) and status_text.strip() and status_text.upper() != "OK":
                failed_tasks.append({
                    "task_id": upid, "worker_type": worker_type, "result": "FAILED",
                })
                if len(failed_tasks) <= 15:
                    problems.append({
                        "key": f"backup_failed:{upid}", "type": "backup_failed",
                        "category": "backup",
                        "facts": {"task_id": upid, "worker_type": worker_type, "result": "FAILED"},
                    })
        result["backup_sessions"] = {
            "active": active, "failed_tasks": failed_tasks[:15],
            "last_error": failed_tasks[0]["task_id"] if failed_tasks else None,
        }
        if failed_tasks:
            statuses.append("DEGRADED")
    except SourceError as exc:
        result["backup_sessions"] = {"active": None, "failed_tasks": [], "last_error": None}
        result["errors"].append(f"backup tasks: {exc}")
        statuses.append("UNAVAILABLE")

    for kind, endpoint in (("sync_jobs", "admin/sync"), ("verify_jobs", "admin/verify"),
                           ("prune_jobs", "admin/prune")):
        try:
            rows = pbs.get(endpoint)
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise SourceError(f"PBS {kind} response is invalid")
            if kind == "sync_jobs":
                rows = [row for row in rows if str(row.get("sync-direction") or row.get("direction") or "pull") == "push"]
            for source in rows:
                run = last_run(source)
                record = {"id": _job_id(source), "store": source.get("store"), **run}
                result[kind].append(record)
                if run["status"] == "FAILED":
                    statuses.append("DEGRADED")
                    category = "sync" if kind == "sync_jobs" else "maintenance"
                    event_type = "sync_failed" if category == "sync" else "verify_failed"
                    if kind != "prune_jobs":
                        problems.append({
                            "key": f"{kind}:{record['id']}", "type": event_type,
                            "category": category,
                            "facts": {"job_id": record["id"], "task_id": run["upid"],
                                      "result": "FAILED"},
                        })
                elif run["status"] in ("UNKNOWN", "NEVER_RUN"):
                    statuses.append("UNKNOWN")
        except SourceError as exc:
            result["errors"].append(f"{kind}: {exc}")
            statuses.append("UNAVAILABLE")
    configured_sync = {item["id"]: item for item in result["sync_jobs"]}
    for rule in config.sync_rules:
        item = configured_sync.get(rule.job_id)
        if item is None:
            result["sync_jobs"].append({"id": rule.job_id, "status": "NOT_CONFIGURED",
                                        "max_age_hours": rule.max_age_hours})
            statuses.append("CRITICAL")
            continue
        item["max_age_hours"] = rule.max_age_hours
        ts = item.get("last_run_timestamp") if item["status"] == "OK" else None
        age = age_hours(now, ts)
        item["last_success_age_hours"] = age
        if age is None or age > rule.max_age_hours:
            statuses.append("CRITICAL")
            problems.append({
                "key": f"sync_overdue:{rule.job_id}",
                "type": "sync_overdue", "category": "sync",
                "facts": {"job_id": rule.job_id, "age_hours": age,
                          "threshold_hours": rule.max_age_hours,
                          "reason_code": "never_succeeded" if age is None else "overdue"},
            })

    for store in config.datastores:
        try:
            gc = pbs.get(f"admin/datastore/{quote(store, safe='')}/gc")
            if not isinstance(gc, dict):
                raise SourceError("PBS GC response is invalid")
            result["gc"].append({"datastore": store, "status": last_run(gc)})
        except SourceError as exc:
            result["gc"].append({"datastore": store, "status": "UNAVAILABLE"})
            result["errors"].append(f"GC {store}: {exc}")
            statuses.append("UNAVAILABLE")

    if result["zfs"]["status"] == "DEGRADED":
        statuses.append("CRITICAL")
        for pool in result["zfs"]["pools"]:
            if pool["health"] != "ONLINE":
                problems.append({
                    "key": f"zfs:{pool['pool']}", "type": "zfs_pool_degraded",
                    "category": "storage",
                    "facts": {"pool": pool["pool"], "zpool_state": pool["health"]},
                })
    elif result["zfs"]["status"] == "UNKNOWN":
        statuses.append("UNKNOWN")

    # No green status when mandatory evidence is incomplete.
    result["status"] = (
        "UNAVAILABLE" if "UNAVAILABLE" in statuses else
        "UNKNOWN" if "UNKNOWN" in statuses else
        "CRITICAL" if "CRITICAL" in statuses else
        "DEGRADED" if "DEGRADED" in statuses else
        "HEALTHY"
    )
    result["summary"] = {
        "datastore_count": len(result["datastores"]),
        "freshness_rules": len(result["backups"]),
        "push_jobs": len(result["sync_jobs"]),
        "verify_jobs": len(result["verify_jobs"]),
        "prune_jobs": len(result["prune_jobs"]),
        "active_problems": len(problems),
    }
    return result
