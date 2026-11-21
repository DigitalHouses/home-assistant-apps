"""Lightweight, ready-to-display PBS trees. No data logic in Lovelace."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def validate_timezone(value: str) -> str | None:
    if not isinstance(value, str) or len(value) > 80:
        return None
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError, OSError):
        return None
    return value


def _local(value: str | None, zone: ZoneInfo, pattern: str) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return "—"
        return parsed.astimezone(zone).strftime(pattern)
    except (ValueError, TypeError, OverflowError):
        return "—"


def _size(raw: int | None) -> str:
    if type(raw) is not int or raw < 0:
        return ""
    if raw >= 10737418:
        return " · +" + f"{raw / 1073741824:.2f}" + " GiB"
    if raw >= 1024:
        return " · +" + f"{raw / 1048576:.1f}" + " MiB"
    return " · +" + str(raw) + " B"


def render_trees(data: dict, timezone_name: str | None, limits: dict) -> dict[str, str]:
    """Pre-render groups, jobs and history from native PBS facts in HA timezone."""
    valid = validate_timezone(timezone_name)
    zone = ZoneInfo(valid or "UTC")
    tz_notice = [] if valid else ["⚠ Часовой пояс HA не получен; временно UTC"]

    groups = data.get("backup_groups") or []
    backup_limit = limits.get("backup_groups", 10)
    history = data.get("task_history") or []
    event_limit = limits.get("task_events", 10)
    if type(backup_limit) is not int or not 1 <= backup_limit <= 80:
        backup_limit = 10
    if type(event_limit) is not int or not 1 <= event_limit <= 50:
        event_limit = 10

    backup_lines = ["PBS", f"├─ Группы резервных копий ({len(groups)})"]
    stores = data.get("datastores") or []
    for i, group in enumerate(groups[:backup_limit]):
        status = group.get("status")
        icon = "🟢" if status == "OK" else "🔴" if status == "OVERDUE" else "⚪"
        count = group.get("snapshot_count")
        count_str = str(count) if isinstance(count, int) and count >= 0 else "?"
        prefix = group.get("datastore", "") + "/" if len(stores) > 1 else ""
        ns = (group.get("namespace") or "")
        prefix += ns + "/" if ns else ""
        ident = prefix + str(group.get("group", "?"))
        when = _local(group.get("last_backup_at"), zone, "%d.%m %H:%M")
        upload = _size(group.get("last_uploaded_compressed_bytes"))
        branch = "└─" if i == min(len(groups), backup_limit)-1 and len(groups) <= backup_limit else "├─"
        backup_lines.append(f"│  {branch} {icon} {ident} · {count_str} коп.{upload} · {when}")
    coverage = data.get("backup_groups_status")
    if not groups:
        backup_lines.append("│  └─ " + ("Нет копий" if coverage == "COMPLETE" else "⚪ Нет достоверного списка"))
    elif len(groups) > backup_limit:
        backup_lines.append(f"│  └─ Ещё {len(groups)-backup_limit} групп")
    if coverage != "COMPLETE":
        backup_lines.append(f"│  ⚠ Инвентаризация: {coverage or 'UNKNOWN'}")
    freshness = data.get("freshness_summary") or {}
    checked = freshness.get("checked", len(groups))
    ok = freshness.get("ok", sum(g.get("status") == "OK" for g in groups))
    overdue = freshness.get("overdue", sum(g.get("status") == "OVERDUE" for g in groups))
    unknown = freshness.get("unknown", sum(g.get("status") == "UNKNOWN" for g in groups))
    threshold = freshness.get("auto_hours", 36)
    symbol = "🔴" if overdue else "⚪" if unknown or not checked else "🟢"
    backup_lines.append(f"└─ {symbol} Свежесть: {ok}/{checked} · авто {threshold:g} ч"
                        + (f" · просрочено {overdue}" if overdue else ""))
    backup_lines.extend(tz_notice)

    jobs = data.get("maintenance_jobs") or []
    job_lines = [f"Задания PBS ({len(jobs)})"]
    kinds = ["Push Sync", "S3 Sync", "Pull Sync", "Verify", "Prune", "GC"]
    kinds = [k for k in kinds if any(j.get("type") == k for j in jobs)]
    for index, kind in enumerate(kinds):
        found = [j for j in jobs if j.get("type") == kind]
        last_kind = index == len(kinds) - 1
        job_lines.append(f"{'└─' if last_kind else '├─'} {kind} ({len(found)})")
        prefix = "   " if last_kind else "│  "
        for j, job in enumerate(found):
            status = job.get("status", "UNKNOWN")
            icon = "🟢" if status == "OK" else "🔴" if status in ("FAILED", "UNAVAILABLE") else "🟠" if status == "NOT_CONFIGURED" else "⚪"
            branch = "└─" if j == len(found)-1 else "├─"
            inner = "   " if j == len(found)-1 else "│  "
            when = _local(job.get("last_run_at"), zone, "%d.%m %H:%M")
            job_lines.append(f"{prefix}{branch} 🕒 {job.get('schedule') or 'без расписания'}")
            job_lines.append(f"{prefix}{inner}└─ {icon} {job.get('id') or '?'} · {status} · {when}")
    if not jobs:
        job_lines.append("└─ ⚪ Заданий нет или данные недоступны")
    job_lines.extend(tz_notice)

    counts = Counter(_local(x.get("started_at"), zone, "%d.%m.%Y") for x in history)
    dates: dict[str, list[dict]] = {}
    for item in history[:event_limit]:
        day = _local(item.get("started_at"), zone, "%d.%m.%Y")
        dates.setdefault(day, []).append(item)
    history_lines = ["Последние выполнения PBS"]
    for index, (day, items) in enumerate(dates.items()):
        last_day = index == len(dates)-1 and len(history) <= event_limit
        history_lines.append(f"{'└─' if last_day else '├─'} 📅 {day} ({counts[day]})")
        prefix = "   " if last_day else "│  "
        for j, event in enumerate(items):
            status = event.get("status", "UNKNOWN")
            icon = "🟢" if status == "OK" else "🔴" if status == "FAILED" else "🟡" if status == "RUNNING" else "⚪"
            branch = "└─" if j == len(items)-1 else "├─"
            when = _local(event.get("started_at"), zone, "%H:%M")
            kind = str(event.get("type") or "?")
            if event.get("guest"):
                kind += " " + str(event["guest"])
            size = _size(event.get("uploaded_compressed_bytes"))
            duration = (str(event["duration_seconds"]) + " с"
                        if event.get("duration_seconds") is not None else "—")
            history_lines.append(f"{prefix}{branch} {icon} {when} · {kind}{size} · {duration} · {status}")
    if not history:
        coverage = data.get("task_history_status")
        history_lines.append("└─ ⚪ " + ("Нет подходящих задач" if coverage == "AVAILABLE" else "История недоступна"))
    elif len(history) > event_limit:
        history_lines.append(f"└─ Ещё {len(history)-event_limit} событий")
    history_lines.extend(tz_notice)
    summary = data.get("summary") or {}
    sum_lines = [
        "Сводка PBS",
        "Datastore: " + str(summary.get("datastore_count", 0)),
        f"Свежесть: {ok}/{checked} · авто {threshold:g} ч"
        + (f" · просрочено {overdue}" if overdue else ""),
        "Push Sync: " + str(summary.get("push_jobs", 0)),
        "Verify: " + str(summary.get("verify_jobs", 0))
        + " · Prune: " + str(summary.get("prune_jobs", 0)),
        "Активных проблем: " + str(summary.get("active_problems", 0)),
    ]
    return {
        "backup": "\n".join(backup_lines),
        "jobs": "\n".join(job_lines),
        "history": "\n".join(history_lines),
        "summary": "\n".join(sum_lines),
    }
