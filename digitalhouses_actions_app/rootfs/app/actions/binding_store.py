"""App-owned persistent JSON bindings; start empty on first use.

The existing Scan/Adopt engine receives an in-memory options projection.
No import of old Supervisor bindings and no writes to Supervisor options.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock

from .catalog import CatalogError
from .entity_options import parse_rows, render_rows, validate_rows

SCHEMA = 1
MAX_DOCUMENT_BYTES = 1_048_576


def binding_document(rows):
    """One versioned contract for disk, import and export."""
    document = {"schema": SCHEMA, "rows": validate_rows(rows)}
    try:
        encoded = json.dumps(document, ensure_ascii=False, allow_nan=False,
                             separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise CatalogError("Bindings must be valid JSON") from exc
    if len(encoded) > MAX_DOCUMENT_BYTES:
        raise CatalogError("Binding store exceeds 1 MiB")
    return document, encoded


def validate_document(doc):
    if (not isinstance(doc, dict) or set(doc) != {"schema", "rows"}
            or type(doc["schema"]) is not int or doc["schema"] != SCHEMA):
        raise CatalogError("Unsupported binding document schema")
    return binding_document(doc["rows"])[0]


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CatalogError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def decode_json(raw):
    """Reject duplicate object keys rather than silently dropping settings."""
    return json.loads(raw, object_pairs_hook=_unique_object)


class BindingStore:
    def __init__(self, supervisor, path=Path("/data/bindings.json")):
        self.supervisor = supervisor
        self.path = path
        self.lock = RLock()
        with self.lock:
            if not self.path.exists():
                self._save([])
            self._read()

    def _read(self):
        try:
            raw = self.path.read_bytes()
            if len(raw) > MAX_DOCUMENT_BYTES:
                raise CatalogError("Binding store exceeds 1 MiB")
            return validate_document(decode_json(raw))["rows"]
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise CatalogError("Binding store invalid; never overwrite it") from exc

    def _save(self, rows):
        _, encoded = binding_document(rows)
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
