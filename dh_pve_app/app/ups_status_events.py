from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UpsStatusEventTracker:
    previous_status: tuple[str, ...] | None = None
    previous_raw_status: tuple[str, ...] | None = None

    def observe(
        self,
        *,
        current_status: tuple[str, ...],
        current_raw_status: tuple[str, ...],
        observed_at: str,
    ) -> tuple[str, dict[str, object]] | None:
        current_status = tuple(current_status)
        current_raw_status = tuple(current_raw_status)

        if self.previous_status is None:
            self.previous_status = current_status
            self.previous_raw_status = current_raw_status
            return None

        previous_status = self.previous_status
        previous_raw_status = self.previous_raw_status or ()

        self.previous_status = current_status
        self.previous_raw_status = current_raw_status

        if previous_status == current_status:
            return None

        payload: dict[str, object] = {
            "schema_version": 2,
            "event_type": "ups_status_changed",
            "observed_at": observed_at,
            "previous_status": list(previous_status),
            "current_status": list(current_status),
            "previous_raw_status": list(previous_raw_status),
            "current_raw_status": list(current_raw_status),
        }
        key = (
            f"ups_status_changed:{observed_at}:"
            f"{','.join(previous_status)}->{','.join(current_status)}"
        )
        return key, payload
