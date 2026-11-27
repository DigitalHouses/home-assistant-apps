"""Read-only configured backup coverage; separate from execution results."""
from __future__ import annotations

import json
import re
import subprocess
from typing import Any, Callable

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
    if (pool and (all_mode or explicit)) or (all_mode and explicit):
        raise ValueError("ambiguous PVE job selection")
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



def collect_inventory(node: str, configured: list, get: Callable[..., object]) -> dict:
    """Reuse the history reader's job list. Never re-read vzdump task logs."""
    try:
        rows = get("/cluster/resources", "--type", "vm")
        if not isinstance(rows, list):
            raise ValueError("invalid guest inventory")
        guests = {}
        for row in rows:
            if not isinstance(row, dict) or not str(row.get("vmid", "")).isdecimal():
                raise ValueError("invalid guest row")
            if not isinstance(row.get("node"), str) or not row["node"]:
                raise ValueError("guest node unavailable")
            if row["node"] == node:
                guests[int(row["vmid"])] = row
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return {"status": "unavailable", "jobs": [], "guests": []}
    jobs = []
    membership = {vmid: [] for vmid in guests}
    exclusions = set()
    uncertain = False
    for job in configured:
        if not isinstance(job, dict) or not job.get("id"):
            uncertain = True
            continue
        if job.get("node") and job["node"] != node:
            continue
        ident = str(job["id"])
        record = {"id": ident[:128], "name": str(job.get("comment") or ident)[:100],
                  "schedule": str(job.get("schedule") or "")[:100],
                  "storage": str(job.get("storage") or "")[:100], "members": []}
        try:
            enabled = _bool(job.get("enabled"), True)
            if not enabled:
                record["status"] = "disabled"
            else:
                pool_members = None
                if job.get("pool"):
                    pool = str(job["pool"])
                    if not re.fullmatch(r"[A-Za-z0-9_.-]+", pool):
                        raise ValueError("invalid pool")
                    result = get("/pools/" + pool)
                    if not isinstance(result, dict) or not isinstance(result.get("members"), list):
                        raise ValueError("invalid pool inventory")
                    pool_members = set()
                    for member in result["members"]:
                        if not isinstance(member, dict):
                            raise ValueError("invalid pool member")
                        if member.get("type") in {"qemu", "lxc"} and not str(member.get("vmid", "")).isdecimal():
                            raise ValueError("invalid pool guest")
                        if str(member.get("vmid", "")).isdecimal():
                            pool_members.add(int(member["vmid"]))
                members = select_members(job, guests, pool_members)
                record["members"] = members
                record["status"] = "enabled"
                exclusions.update(_vmids(job.get("exclude")))
                for vmid in members:
                    membership[vmid].append(ident[:128])
        except (OSError, subprocess.SubprocessError, ValueError, TypeError):
            record["status"] = "unknown"
            uncertain = True
        jobs.append(record)
    details = []
    for vmid, guest in sorted(guests.items()):
        state = ("covered" if membership[vmid] else "unknown" if uncertain
                 else "excluded" if vmid in exclusions else "uncovered")
        details.append({"id": vmid, "name": str(guest.get("name") or "")[:80],
                        "kind": str(guest.get("type") or "")[:16],
                        "status": state, "jobs": membership[vmid]})
    counts = {state: sum(g["status"] == state for g in details)
              for state in ("covered", "uncovered", "excluded", "unknown")}
    return {"status": "unknown" if uncertain else "available", "counts": counts,
            "jobs": jobs, "guests": details}


def bounded_inventory(inventory: dict) -> dict:
    # This is a separate HA sensor with a separate attributes budget.
    result = {**inventory, "jobs": [], "guests": [], "details_limited": False}
    used = len(json.dumps(result, ensure_ascii=True).encode())
    for key in ("jobs", "guests"):
        for item in inventory.get(key, []):
            cost = len(json.dumps(item, ensure_ascii=True).encode()) + 2
            if used + cost > 11000:
                result["details_limited"] = True
                continue
            result[key].append(item)
            used += cost
    return result
