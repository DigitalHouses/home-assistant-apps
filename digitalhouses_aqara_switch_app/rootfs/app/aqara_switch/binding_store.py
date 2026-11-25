"""One-time import of Supervisor YAML into the app-owned JSON store.

The existing Scan/Adopt engine receives an in-memory options projection.
No writes to Supervisor options and no YAML configuration after migration.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock

from .catalog import CatalogError
from .entity_options import parse_rows, render_rows

class BindingStore:
    def __init__(self, supervisor, path=Path("/data/bindings.json")):
        self.supervisor = supervisor
        self.path = path
        self.lock = RLock()
        with self.lock:
            if not self.path.exists():
                options = supervisor.read()
                raw = supervisor.read_raw() if "switches" not in options else options
                if "switches" not in raw:
                    # New installs have no previous binding option.
                    raw = {**raw, "switches": "[]"}
                rows = parse_rows({**options, "switches": raw["switches"]})
                self._save(rows)
            self._read()

    def _read(self):
        try:
            raw = self.path.read_bytes()
            if len(raw) > 1_048_576:
                raise CatalogError("Binding store exceeds 1 MiB")
            doc = json.loads(raw)
            if not isinstance(doc, dict) or doc.get("schema") != 1:
                raise CatalogError("Unsupported binding store schema")
            return parse_rows({"switches": render_rows(doc["rows"])})
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise CatalogError("Binding store invalid; never overwrite it") from exc

    def _save(self, rows):
        encoded = json.dumps({"schema": 1, "rows": rows}, ensure_ascii=False,
                             separators=(",", ":")).encode()
        if len(encoded) > 1_048_576:
            raise CatalogError("Binding store exceeds 1 MiB")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())
            tmp.replace(self.path)
        finally:
            tmp.unlink(missing_ok=True)

    def read(self):
        with self.lock:
            settings = self.supervisor.read()
            return {**settings, "switches": render_rows(self._read()),
                    "_bindings_store": True}

    def write(self, options):
        with self.lock:
            self._save(parse_rows(options))
