from __future__ import annotations


VALID_OPERATION_STATES = frozenset({"idle", "updating", "error"})


def operation_payload(
    state: str,
    *,
    started_at: str | None = None,
    finished_at: str | None = None,
    duration_seconds: float | None = None,
    error: str | None = None,
) -> dict[str, object]:
    if state not in VALID_OPERATION_STATES:
        raise ValueError(f"unsupported operation state: {state}")
    return {
        "state": state,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": (
            None if duration_seconds is None else round(max(0.0, float(duration_seconds)), 3)
        ),
        "error": error,
    }
