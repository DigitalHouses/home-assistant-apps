"""Read-only Proxmox Backup Server 4.x HTTPS API and native ZFS observations."""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

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
        lowered = raw.lower()
        status = "OK" if lowered == "ok" else (
            "FAILED" if lowered.startswith(("error", "failed")) else "UNKNOWN"
        )
    elif isinstance(raw, dict):
        kind = raw.get("status") or raw.get("state")
        status = "OK" if isinstance(kind, str) and kind.lower() == "ok" else (
            "FAILED" if isinstance(kind, str) and kind.lower().startswith(("error", "failed")) else "UNKNOWN"
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
    """Local PBS API reader using the root-owned built-in CLI.

    Analogous to the PVE Agent root subprocess pvesh get. No remote
    HTTP, stored PBS credentials, or additional service/process.
    PROXMOX_DEBUG_API_CODE=1 calls the installed PBS API implementation
    directly, without creating an implicit temporary API token.
    """

    def __init__(self, config: Config | None = None, runner=None):
        self.config = config
        self.runner = runner or self._run

    @staticmethod
    def _run(argv: list[str]) -> str:
        env = dict(os.environ)
        env["PROXMOX_DEBUG_API_CODE"] = "1"
        try:
            completed = subprocess.run(
                argv, capture_output=True, text=True, check=True,
                timeout=20, env=env,
            )
        except subprocess.CalledProcessError as exc:
            # Local GETs have no PBS credentials. Show a bounded, printable
            # diagnostic; never include stdout or the native configuration.
            detail = " ".join(str(exc.stderr or "").split())[:180]
            raise SourceError(
                f"PBS local CLI failed (exit {exc.returncode})"
                + (f": {detail}" if detail else "")
            ) from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise SourceError(f"PBS local CLI failed: {type(exc).__name__}") from exc
        return completed.stdout

    def task_list(self, limit: int = 100) -> list[dict]:
        """PBS 4.x supported root CLI, including completed tasks with --all.

        The direct debug API cannot initialize WorkerTask in a standalone
        process. The normal manager command can list historical tasks.
        """
        if not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise SourceError("invalid PBS task list limit")
        argv = [
            "proxmox-backup-manager", "task", "list",
            "--all", "true", "--limit", str(limit),
            "--output-format", "json",
        ]
        try:
            finished = subprocess.run(
                argv, capture_output=True, text=True, check=True, timeout=20,
            )
        except subprocess.CalledProcessError as exc:
            detail = " ".join(str(exc.stderr or "").split())[:180]
            raise SourceError(
                f"PBS native task list failed (exit {exc.returncode})"
                + (f": {detail}" if detail else "")
            ) from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise SourceError(f"PBS native task list unavailable: {type(exc).__name__}") from exc
        try:
            rows = json.loads(finished.stdout)
        except (ValueError, TypeError) as exc:
            raise SourceError("PBS native task list is not valid JSON") from exc
        if not isinstance(rows, list) or any(not isinstance(x, dict) for x in rows):
            raise SourceError("PBS native task list has invalid structure")
        return rows

    def get(self, path: str, **params: object):
        """Execute only API GET; never create/update/delete a PBS resource."""
        if not path or path.startswith("/") or any(x in path for x in ("..", "\n", "\r")):
            raise SourceError("invalid PBS API GET path")
        argv = ["proxmox-backup-debug", "api", "get", "/" + path]
        for key, value in params.items():
            if value is not None:
                if not key.replace("-", "").replace("_", "").isalnum():
                    raise SourceError("invalid PBS API parameter name")
                argv.extend(["--" + key.replace("_", "-"), str(value)])
        argv.extend(["--output-format", "json"])
        try:
            response = json.loads(self.runner(argv))
        except (TypeError, ValueError) as exc:
            raise SourceError(f"invalid local PBS JSON at {path}") from exc
        # Direct CLI ordinarily prints the data (rather than the HTTPS
        # transport envelope); support the one-key envelope if returned.
        if isinstance(response, dict) and set(response) == {"data"}:
            response = response["data"]
        if response is None:
            raise SourceError(f"PBS API returned no data at {path}")
        return response


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
        "root_fs": root_filesystem(), "filesystems": [], "errors": [], "problems": [],
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
    # Filesystem paths are from the official datastore configuration, not
    # inferred from snapshot names. Deduplicate by filesystem device ID.
    try:
        config_rows = pbs.get("config/datastore")
        if not isinstance(config_rows, list):
            raise SourceError("PBS datastore config is not a list")
        paths = {
            str(row.get("name")): str(row["path"])
            for row in config_rows
            if isinstance(row, dict) and row.get("name") and isinstance(row.get("path"), str)
        }
        filesystems = {}
        for path in ("/", *[paths.get(store) for store in config.datastores]):
            if not path:
                continue
            if not Path(path).is_absolute():
                raise SourceError("PBS datastore path is not absolute")
            try:
                device = os.stat(path).st_dev
                vfs = os.statvfs(path)
            except OSError as exc:
                raise SourceError(f"filesystem unavailable at {path}") from exc
            filesystems.setdefault(str(device), {
                "mountpoint": path,
                "total_bytes": int(vfs.f_blocks * vfs.f_frsize),
                "used_bytes": int((vfs.f_blocks - vfs.f_bfree) * vfs.f_frsize),
                "available_bytes": int(vfs.f_bavail * vfs.f_frsize),
            })
        result["filesystems"] = list(filesystems.values())
    except SourceError as exc:
        result["errors"].append(f"datastore filesystems: {exc}")
        statuses.append("UNAVAILABLE")

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
        task_rows = pbs.task_list(limit=100)
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
            endtime = task.get("endtime")
            if endtime is None:
                active += 1
                continue
            # A 30-day-old failure is historical evidence, not a new outage.
            # Only recent completed tasks can start a live incident.
            if not isinstance(endtime, (int, float)) or endtime < now - 86400 or endtime > now + 300:
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
            problems.append({
                "key": f"sync_overdue:{rule.job_id}", "type": "sync_overdue",
                "category": "sync",
                "facts": {
                    "job_id": rule.job_id, "age_hours": None,
                    "threshold_hours": rule.max_age_hours, "reason_code": "not_configured",
                },
            })
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
