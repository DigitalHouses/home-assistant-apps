"""Single-owner MQTT phone-removal selection, never authentication.

Only one currently enrolled phone is selected at a time. The selection is
volatile and starts empty after every App start. A button press is a separate
non-retained MQTT command; duplicates cannot target the next phone because
selection is cleared before any deletion.
"""
from __future__ import annotations

from .core import Resident

EMPTY = "— Выберите телефон —"


def phone_removal_choices(registrations: list[dict],
                          residents: list[Resident]) -> dict[str, str]:
    """Return human-readable, unique MQTT select labels mapped to GPS trackers."""
    eligible = {r.tracker for r in residents if r.registered}
    choices = {}
    for record in sorted(
            (r for r in registrations if r["tracker"] in eligible),
            key=lambda r: (r["user_name"].casefold(), r["device_name"].casefold(),
                           r["tracker"])):
        # Include the exact canonical ID to avoid ambiguous display names.
        user = " ".join(str(record["user_name"]).split())[:100]
        device = " ".join(str(record["device_name"]).split())[:100]
        label = f"{user} ({device}) · {record['tracker']}"
        choices[label] = record["tracker"]
    return choices


class PhoneRemovalSelection:
    def __init__(self):
        self.selected = EMPTY

    def select(self, label: str, choices: dict[str, str]) -> bool:
        if label != EMPTY and label not in choices:
            return False
        self.selected = label
        return True

    def target(self, choices: dict[str, str]) -> str | None:
        return choices.get(self.selected)

    def refresh(self, choices: dict[str, str]) -> None:
        if self.selected not in choices:
            self.selected = EMPTY

    def clear(self) -> None:
        self.selected = EMPTY
