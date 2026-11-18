"""Machine event transitions. PBS data is facts; HA packages own Russian text."""
from __future__ import annotations

from datetime import datetime, timezone
from .state import StateStore

RECOVERIES = {
    "backup_overdue": "backup_recovered",
    "backup_failed": "backup_recovered",
    "sync_failed": "sync_recovered",
    "sync_overdue": "sync_recovered",
    "disk_space_low": "disk_space_recovered",
    "zfs_pool_degraded": "zfs_pool_recovered",
    "service_unavailable": "service_recovered",
}


def _confirmed_recovery(key: str, old: dict, payload: dict) -> bool:
    kind = old["type"]
    if kind == "service_unavailable":
        return payload.get("pbs_version") not in (None, "unknown")
    if kind == "backup_overdue":
        return any(
            x.get("status") == "OK" and
            f"backup:{x['datastore']}:{x['namespace']}:{x['group']}" == key
            for x in payload.get("backups", [])
        )
    if kind == "sync_overdue":
        return any(
            x.get("status") == "OK" and x.get("last_success_age_hours") is not None and
            x["last_success_age_hours"] <= x["max_age_hours"] and
            "sync_overdue:" + str(x["id"]) == key
            for x in payload.get("sync_jobs", [])
        )
    if kind == "sync_failed":
        return any(
            "sync_jobs:" + str(x["id"]) == key and x.get("status") == "OK"
            for x in payload.get("sync_jobs", [])
        )
    if kind == "verify_failed":
        return any(
            "verify_jobs:" + str(x["id"]) == key and x.get("status") == "OK"
            for x in payload.get("verify_jobs", [])
        )
    if kind == "disk_space_low":
        return any(
            "capacity:" + str(x["name"]) == key and x.get("health") == "HEALTHY"
            for x in payload.get("datastores", [])
        )
    if kind == "zfs_pool_degraded":
        return any(
            "zfs:" + x["pool"] == key and x.get("health") == "ONLINE"
            for x in payload.get("zfs", {}).get("pools", [])
        )
    return False


def transitions(payload: dict, store: StateStore) -> list[dict]:
    """Persist baseline once. Unknown/unobservable sources never imply recovery."""
    saved = store.load()
    previous = saved.get("active", {})
    if not isinstance(previous, dict):
        previous = {}
    active = {k: v for k, v in previous.items() if isinstance(v, dict)}
    actual = {x["key"]: x for x in payload.get("problems", [])}
    events = []
    def make(problem: dict, event_type: str) -> dict:
        # Each event type receives only its own machine facts, no envelope.
        return {
            "schema_version": 1,
            "event_type": event_type,
            "observed_at": payload["observed_at"],
            **problem["facts"],
        }
    for key, problem in actual.items():
        if key not in active or active[key].get("type") != problem["type"]:
            events.append({"category": problem["category"], "payload": make(problem, problem["type"])})
        active[key] = problem
    for key, old in previous.items():
        if key in actual or not isinstance(old, dict) or not _confirmed_recovery(key, old, payload):
            continue
        recovered = RECOVERIES.get(old["type"])
        if recovered:
            events.append({"category": old["category"], "payload": make(old, recovered)})
        active.pop(key, None)
    store.save({"active": active})
    return events
