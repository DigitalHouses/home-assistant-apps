from __future__ import annotations

from collections.abc import Mapping, Sequence


_HISTORY_LIMIT = 10


def normalize_test_result(value: str | None) -> str:
    if not value:
        return "Unknown"
    text = value.strip().casefold()
    if not text:
        return "Unknown"
    if "progress" in text or "running" in text:
        return "Running"
    if "pass" in text or "success" in text:
        return "Passed"
    if "abort" in text or "stop" in text or "cancel" in text:
        return "Stopped"
    if "fail" in text or "error" in text:
        return "Failed"
    return "Unknown"


def append_test_history(
    history: Sequence[Mapping[str, object]],
    record: Mapping[str, object],
) -> list[dict[str, object]]:
    result = [dict(item) for item in history]
    result.append(dict(record))
    if len(result) > _HISTORY_LIMIT:
        result = result[-_HISTORY_LIMIT:]
    return result
