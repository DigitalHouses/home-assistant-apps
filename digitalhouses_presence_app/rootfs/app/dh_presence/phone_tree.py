"""Single MQTT diagnostics read model for the dashboard registered-phone tree.

The App owns all enrollment filtering, grouping and line formatting. HA only
renders the finished text and does not join registration details with people
or Wi-Fi devices. The topic contains registration-time private IP/MAC, so the
diagnostic entity must be excluded from Recorder.
"""
from __future__ import annotations

import re

from dh_presence.core import Resident


def _label(value: str) -> str:
    # User and device names may contain line breaks or Markdown/HTML markup.
    # Never allow them to create forged tree branches. HTML is escaped in the
    # read-only Lovelace <pre> template, not at the MQTT source.
    return re.sub(r"[\x00-\x1f\x7f]+", " ", str(value)).strip()[:120] or "—"


def registered_phones_tree(registrations: list[dict],
                           residents: list[Resident]) -> dict:
    """Build a deterministic, self-contained MQTT state only on registry changes."""
    permitted = {r.tracker for r in residents if r.registered}
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
        wifi = (_label(reg["wifi_tracker"].removeprefix("device_tracker."))
                if reg.get("wifi_tracker") else "не привязан")
        ip = _label(reg["ip"])
        mac = _label(reg["mac"])
        lines.extend([
            f"{root} 📱 {who} ({device})",
            f"{indent}├─ GPS · {tracker}",
            f"{indent}├─ Wi-Fi · {wifi}",
            f"{indent}├─ IP (рег.) · {ip}",
            f"{indent}└─ MAC (рег.) · {mac}",
        ])
    # State: tiny stable count. One diagnostic 'tree' attribute, not a metric.
    return {"count": len(eligible), "tree": "\n".join(lines)}
