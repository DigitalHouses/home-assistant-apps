"""Pure data transformations for Backblaze B2 statistics."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_GIB = 1024 ** 3
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def bytes_to_gib(value: int) -> float:
    return round(max(0, int(value)) / _GIB, 3)


def slugify(value: str) -> str:
    slug = _SLUG_RE.sub("_", value.lower()).strip("_")
    return slug or "bucket"


@dataclass
class BucketAccumulator:
    bucket_id: str
    bucket_name: str
    bucket_type: str
    storage_bytes: int = 0
    current_file_count: int = 0
    version_count: int = 0
    hide_marker_count: int = 0
    _seen_names: set[str] = field(default_factory=set, repr=False)

    def consume(self, item: dict[str, Any]) -> None:
        name = str(item.get("fileName") or "")
        action = str(item.get("action") or "")

        if name and name not in self._seen_names:
            self._seen_names.add(name)
            if action == "upload":
                self.current_file_count += 1

        if action == "upload":
            self.version_count += 1
            try:
                self.storage_bytes += max(0, int(item.get("contentLength") or 0))
            except (TypeError, ValueError):
                pass
        elif action == "hide":
            self.hide_marker_count += 1

    def result(self) -> dict[str, Any]:
        return {
            "bucket_id": self.bucket_id,
            "bucket_name": self.bucket_name,
            "bucket_type": self.bucket_type,
            "storage_bytes": self.storage_bytes,
            "storage_gib": bytes_to_gib(self.storage_bytes),
            "file_count": self.current_file_count,
            "version_count": self.version_count,
            "old_version_count": max(
                0, self.version_count - self.current_file_count
            ),
            "hide_marker_count": self.hide_marker_count,
        }


def build_account_state(
    buckets: list[dict[str, Any]],
    *,
    app_version: str,
    started_at: str,
    updated_at: str,
) -> dict[str, Any]:
    total_bytes = sum(int(bucket.get("storage_bytes") or 0) for bucket in buckets)
    return {
        "api_ok": True,
        "app_version": app_version,
        "started_at": started_at,
        "last_update": updated_at,
        "bucket_count": len(buckets),
        "total_bytes": total_bytes,
        "total_gib": bytes_to_gib(total_bytes),
        "buckets": {
            str(bucket["bucket_id"]): bucket
            for bucket in buckets
        },
    }
