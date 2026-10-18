"""Single MQTT diagnostics read model for the dashboard registered-phone tree.

The App owns all enrollment filtering, grouping and line formatting. HA only
renders the finished text and does not join registration details with people
or Wi-Fi devices. The topic contains registration-time private IP/MAC, so the
diagnostic entity must be excluded from Recorder.
"""
from __future__ import annotations

import re
from datetime import datetime, tzinfo

from dh_presence.core import Resident, Status


def _label(value: str) -> str:
    # User and device names may contain line breaks or Markdown/HTML markup.
    # Never allow them to create forged tree branches. HTML is escaped in the
    # read-only Lovelace <pre> template, not at the MQTT source.
    return re.sub(r"[\x00-\x1f\x7f]+", " ", str(value)).strip()[:120] or "—"


def _presence_label(status: Status) -> str:
    """Return the source's confirmed state; never treat an outage as away."""
    if status is Status.HOME:
        return "🟢 Дома"
    if status is Status.NOT_HOME:
        return "🟠 Не дома"
    return "⚪ Недоступно"


def _since(value: datetime | None, local_tz: tzinfo | None) -> str:
    """Show HA-local wall time, without a redundant timezone/UTC offset suffix."""
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        return "нет данных"
    if local_tz is None:
        # Never misrepresent a UTC time as HA-local if Core config is missing.
        return "местное время недоступно"
    return value.astimezone(local_tz).strftime("%d.%m.%Y %H:%M")


def registered_phones_tree(registrations: list[dict],
                           residents: list[Resident], *,
                           local_tz: tzinfo | None = None) -> dict:
    """Build a live source-status tree with source transition timestamps."""
    permitted = {r.tracker: r for r in residents if r.registered}
    eligible = sorted(
        (reg for reg in registrations if reg["tracker"] in permitted),
        key=lambda x: (x["user_name"].casefold(), x["device_name"].casefold(),
                       x["tracker"]),
    )
    lines = ["Зарегистрированные телефоны"]
    for n, reg in enumerate(eligible):
        last = n == len(eligible) - 1
        root = "└─" if last else "├─"
        indent = "   " if last else "│  "
        who = _label(reg["user_name"])
        device = _label(reg["device_name"])
        tracker = _label(reg["tracker"].removeprefix("device_tracker."))
        resident = permitted[reg["tracker"]]
        wifi_linked = bool(reg.get("wifi_tracker"))
        wifi = (_label(reg["wifi_tracker"].removeprefix("device_tracker."))
                if wifi_linked else "не привязан")
        gps_status = _presence_label(resident.gps)
        wifi_status = _presence_label(resident.wifi) if wifi_linked else "⚪ Не привязан"
        gps_since = _since(resident.gps_changed_at, local_tz)
        wifi_since = (_since(resident.wifi_changed_at, local_tz)
                      if wifi_linked else "не применимо")
        ip = _label(reg["ip"])
        mac = _label(reg["mac"])
        lines.extend([
            f"{root} 📲 {who} ({device})",
            f"{indent}├─ GPS · {gps_status} · {tracker}",
            f"{indent}│  └─ Статус с · {gps_since}",
            f"{indent}├─ Wi-Fi · {wifi_status}" +
                (f" · {wifi}" if wifi_linked else ""),
            f"{indent}│  └─ Статус с · {wifi_since}",
            f"{indent}├─ IP (рег.) · {ip}",
            f"{indent}└─ MAC (рег.) · {mac}",
        ])
    # State: stable count. The tree attribute updates on live GPS/Wi-Fi changes
    # but is deduplicated by MqttOutput when neither status nor roster changes.
    return {"count": len(eligible), "tree": "\n".join(lines)}
