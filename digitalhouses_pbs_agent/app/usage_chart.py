"""Thirty-day PBS datastore usage chart, fully rendered by the Agent.

The UI displays HTML without calculating day buckets, values, scale or deltas.
RRD stores filesystem usage, not the sum of deduplicated snapshot sizes.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from html import escape
import math
from zoneinfo import ZoneInfo

from .view import validate_timezone

GIB = 1024 ** 3
DAYS = 30


def daily_usage(rows: list[dict], observed_at: str, timezone_name: str | None,
                latest_used_bytes: int | float | None = None) -> list[dict]:
    """Use the last valid RRD point of each HA-local day; preserve missing days.

    Today gets the more recent live datastore-status measurement. RRD monthly
    AVERAGE values are 30-minute aggregates, so historical points are not exact
    23:59 snapshots. No zeros or interpolation for missing dates.
    """
    zone = ZoneInfo(validate_timezone(timezone_name) or "UTC")
    observed = datetime.fromisoformat(observed_at)
    if observed.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    local_now = observed.astimezone(zone)
    first = local_now.date() - timedelta(days=DAYS - 1)
    latest: dict[date, tuple[float, float, str]] = {}
    if isinstance(rows, list):
        for item in rows:
            if not isinstance(item, dict):
                continue
            stamp, used = item.get("time"), item.get("used")
            if (type(stamp) not in (int, float)
                    or type(used) not in (int, float)
                    or not math.isfinite(stamp) or not math.isfinite(used)
                    or stamp > observed.timestamp() or used < 0):
                continue
            try:
                day = datetime.fromtimestamp(stamp, zone).date()
            except (ValueError, OSError, OverflowError):
                continue
            if not first <= day <= local_now.date():
                continue
            if day not in latest or stamp > latest[day][0]:
                latest[day] = (float(stamp), float(used), "rrd")
    if (type(latest_used_bytes) in (int, float)
            and math.isfinite(latest_used_bytes) and latest_used_bytes >= 0):
        today = local_now.date()
        latest[today] = (observed.timestamp(), float(latest_used_bytes), "live")
    return [
        {
            "date": (first + timedelta(days=i)).isoformat(),
            "timestamp": latest[first + timedelta(days=i)][0] if first + timedelta(days=i) in latest else None,
            "used_gib": round(latest[first + timedelta(days=i)][1] / GIB, 3)
                        if first + timedelta(days=i) in latest else None,
            "source": latest[first + timedelta(days=i)][2] if first + timedelta(days=i) in latest else None,
        }
        for i in range(DAYS)
    ]


def _usage_panel(store: str, days: list[dict], timezone_name: str | None,
                 error: str | None = None) -> str:
    valid = [d for d in days if d["used_gib"] is not None]
    title = escape(store, quote=True)
    heading = ('<div style="font-size:13px;font-weight:600;margin:2px 0 7px">'
               + title + '</div>')
    if not valid:
        reason = " · " + escape(error[:110], quote=True) if error else ""
        return heading + ('<div style="padding:32px 4px;text-align:center;'
                          'color:var(--secondary-text-color)">'
                          'Нет достоверной истории занятого места PBS' + reason + '</div>')

    sizes = [d["used_gib"] for d in valid]
    low, high = min(sizes), max(sizes)
    spread = max(high - low, 0.0)
    margin = max(1.0, spread * 0.25)
    floor = max(0.0, low - margin)
    ceiling = max(high + margin, floor + 0.1)
    latest = valid[-1]
    latest_date = datetime.strptime(latest["date"], "%Y-%m-%d").strftime("%d.%m")
    value = f'{latest["used_gib"]:.2f} GiB'
    if len(valid) > 1:
        first = valid[0]
        delta = latest["used_gib"] - first["used_gib"]
        day = datetime.strptime(first["date"], "%Y-%m-%d").strftime("%d.%m")
        change = f'Изменение с {day}: {delta:+.2f} GiB'
    else:
        change = "История пока не накоплена"
    summary = ('<div style="display:flex;align-items:baseline;justify-content:space-between;'
               'gap:8px;flex-wrap:wrap;font-size:12px;margin-bottom:9px">'
               f'<b>{value}</b><span style="color:var(--secondary-text-color)">{escape(change)}</span>'
               '</div>')

    # Inline SVG keeps the entire 30-bar payload small (<10 KiB) and needs
    # no chart library, HA history queries or frontend calculation.
    svg = [
        '<div style="width:100%;overflow-x:auto">',
        '<svg role="img" aria-label="Занято на диске PBS за 30 дней" '
        'viewBox="0 0 480 207" width="480" height="207" '
        'style="width:100%;height:auto;display:block" '
        'xmlns="http://www.w3.org/2000/svg">',
    ]
    bottom, plot_h = 167.0, 150.0
    for y in (17, 67, 117, 167):
        svg.append(f'<line x1="4" y1="{y}" x2="476" y2="{y}" '
                   'stroke="var(--divider-color)" stroke-width="1" '
                   'stroke-dasharray="2 3"/>')
    for i, item in enumerate(days):
        date_label = datetime.strptime(item["date"], "%Y-%m-%d").strftime("%d.%m")
        used = item["used_gib"]
        x = 5.0 + i * 15.65
        center = x + 5.3
        if used is None:
            tooltip = f'{date_label}: нет измерений'
            rect = ''
        else:
            height = max(2.0, min(plot_h, plot_h * (used - floor) / (ceiling - floor)))
            stamp = datetime.fromtimestamp(
                item["timestamp"], ZoneInfo(validate_timezone(timezone_name) or "UTC"))
            description = 'текущее значение' if item["source"] == "live" else 'RRD, усреднённое'
            tooltip = f'{date_label} · {used:.2f} GiB · {stamp:%H:%M} · {description}'
            rect = (f'<rect x="{x:.1f}" y="{bottom-height:.1f}" '
                    f'width="10.6" height="{height:.1f}" rx="2" '
                    'fill="var(--primary-color)"/>')
        svg.append('<g><title>' + escape(tooltip) + '</title>' + rect + '</g>')
        if i == 0 or i == DAYS - 1 or i % 5 == 0:
            svg.append(
                f'<text x="{center:.1f}" y="191" text-anchor="middle" '
                'font-size="10" fill="var(--secondary-text-color)" '
                'font-family="sans-serif">' + date_label + '</text>'
            )
    svg.append('</svg></div>')
    scale = ('<div style="display:flex;justify-content:space-between;'
             'color:var(--secondary-text-color);font-size:10px;margin-top:5px">'
             f'<span>Шкала {floor:.1f}–{ceiling:.1f} GiB (не от нуля)</span>'
             f'<span>Измерений: {len(valid)}/{DAYS}</span></div>')
    note = ('<div style="font-size:10px;color:var(--secondary-text-color);'
            'margin-top:5px">Последнее значение RRD за день; сегодня — текущий статус.'
            ' Пропуски не заменяются нулями.</div>')
    if error:
        note += ('<div style="font-size:10px;color:var(--warning-color,orange);'
                 'margin-top:3px">RRD недоступен: ' + escape(error[:110]) + '</div>')
    return heading + summary + ''.join(svg) + scale + note


def render_usage_chart(raw: dict, stores: list[dict], observed_at: str,
                       timezone_name: str | None) -> dict:
    """One fully authored 30-bar HTML plot for each discovered local datastore."""
    raw = raw if isinstance(raw, dict) else {}
    cards = []
    counts = 0
    latest = None
    delta = None
    for store in stores:
        name = store.get("name")
        if not isinstance(name, str) or store.get("backend") == "S3":
            continue
        info = raw.get(name)
        info = info if isinstance(info, dict) else {}
        days = daily_usage(
            info.get("rows") or [], observed_at, timezone_name,
            store.get("used_bytes") if store.get("health") != "UNAVAILABLE" else None,
        )
        values = [d for d in days if d["used_gib"] is not None]
        counts += len(values)
        if values:
            latest = values[-1]["used_gib"]
            delta = round(latest - values[0]["used_gib"], 2) if len(values) > 1 else None
        cards.append(_usage_panel(name, days, timezone_name, info.get("error")))
    if not cards:
        cards = ['<div style="text-align:center;padding:30px">'
                 'Нет локальных datastore для графика</div>']
    if not validate_timezone(timezone_name):
        cards.append('<div style="font-size:11px;color:var(--warning-color,orange)">'
                     'Часовой пояс HA не получен; временно UTC</div>')
    return {
        "status": "OK" if counts else "NO_DATA",
        "html": '<div style="width:100%;box-sizing:border-box;overflow:hidden">'
                + '<div style="display:flex;flex-direction:column;gap:14px">'
                + ''.join(cards) + '</div></div>',
        "days": DAYS,
        "available": counts,
        "latest_used_gib": latest,
        "delta_gib": delta,
        "ha_timezone": timezone_name or "unknown",
    }
