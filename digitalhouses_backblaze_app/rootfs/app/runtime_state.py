from __future__ import annotations

import json
from pathlib import Path


RUNTIME_STATE_PATH = Path("/data/runtime_state.json")


class RuntimeStateError(RuntimeError):
    pass


def load_last_refresh(path: Path = RUNTIME_STATE_PATH) -> str | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RuntimeStateError(f"Unable to read runtime state: {exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeStateError("Runtime state is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeStateError("Runtime state must be a JSON object")

    value = payload.get("last_refresh")
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise RuntimeStateError("Runtime state last_refresh must be a non-empty string or null")
    return value


def save_last_refresh(
    last_refresh: str | None,
    path: Path = RUNTIME_STATE_PATH,
) -> None:
    if last_refresh is not None and (
        not isinstance(last_refresh, str) or not last_refresh
    ):
        raise RuntimeStateError("Runtime state last_refresh must be a non-empty string or null")

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(
            json.dumps(
                {"last_refresh": last_refresh},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        tmp.replace(path)
    except OSError as exc:
        raise RuntimeStateError(f"Unable to persist runtime state: {exc}") from exc
