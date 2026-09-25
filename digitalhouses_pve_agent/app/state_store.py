from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping


class StateStoreError(RuntimeError):
    pass


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise StateStoreError(
                f"invalid persisted state: {self.path}"
            ) from exc
        if not isinstance(data, dict):
            raise StateStoreError(
                f"invalid persisted state: {self.path}"
            )
        return data

    def save(self, data: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_name(f"{self.path.name}.tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as handle:
                json.dump(
                    dict(data),
                    handle,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        except (OSError, TypeError, ValueError) as exc:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise StateStoreError(
                f"unable to persist state: {self.path}"
            ) from exc
