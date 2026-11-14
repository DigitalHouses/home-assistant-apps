"""DH Sync Discovery Contract v1: untrusted MQTT product-source metadata.

Repository ownership is an admission rule, not authorization to execute/install.
Never pass an MQTT URL directly to urllib, git, or a dynamic download routine.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit

PRODUCT_RE = re.compile(r"digitalhouses_[a-z0-9_]+_(?:app|agent)\Z", re.ASCII)
INSTANCE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z", re.ASCII)
REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z", re.ASCII)
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.+-]+)?\Z", re.ASCII)
SOURCE_ROOT = "DigitalHouses/Global/"
EXPECTED_OWNER = "DigitalHouses"
MAX_PAYLOAD = 4096


class DiscoveryError(ValueError):
    pass


def canonical_repository(value: str) -> str:
    """Reject host confusion, credentials, encodings, ports and path traversal."""
    if not isinstance(value, str) or not value or len(value) > 220:
        raise DiscoveryError("Missing or oversized repository URL")
    if not value.isascii() or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        raise DiscoveryError("Repository URL must be printable ASCII without whitespace")
    # Reject ambiguous userinfo, URL encoding, backslashes and fragments outright.
    if any(c in value for c in ("@", "%", "\\", "?", "#")):
        raise DiscoveryError("Ambiguous repository URL syntax")
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise DiscoveryError("Malformed repository URL") from exc
    if (parsed.scheme != "https" or parsed.netloc.lower() != "github.com"
            or parsed.hostname != "github.com" or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment):
        raise DiscoveryError("Only a direct HTTPS github.com repository is allowed")
    segments = parsed.path.split("/")
    if len(segments) != 3 or segments[0] != "":
        raise DiscoveryError("Repository URL must be /DigitalHouses/<repository>")
    owner, name = segments[1:]
    if owner.lower() != EXPECTED_OWNER.lower():
        raise DiscoveryError("Repository owner is not DigitalHouses")
    if (not REPOSITORY_RE.fullmatch(name) or name in (".", "..")
            or name.startswith("-") or name.endswith(".git")):
        raise DiscoveryError("Invalid repository name")
    return f"https://github.com/{EXPECTED_OWNER}/{name}"


def parse_sync_topic(topic: str) -> tuple[str, str] | None:
    if not isinstance(topic, str) or not topic.startswith(SOURCE_ROOT):
        return None
    parts = topic[len(SOURCE_ROOT):].split("/")
    if len(parts) == 2 and parts[1] == "sync":
        product, instance = parts[0], "default"
    elif len(parts) == 3 and parts[2] == "sync":
        product, instance = parts[0], parts[1]
    else:
        return None
    if not PRODUCT_RE.fullmatch(product) or not INSTANCE_RE.fullmatch(instance):
        return None
    return product, instance


def validate_sync_message(topic: str, payload: bytes | str) -> tuple[str, dict]:
    identity = parse_sync_topic(topic)
    if identity is None:
        raise DiscoveryError("Unsupported product sync topic")
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_PAYLOAD:
        raise DiscoveryError("Invalid MQTT sync payload size")
    try:
        message = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DiscoveryError("Invalid MQTT sync JSON") from exc
    if not isinstance(message, dict):
        raise DiscoveryError("MQTT sync payload must be an object")
    required = ("schema", "product_id", "type", "version", "repository", "product_path")
    if any(key not in message for key in required):
        raise DiscoveryError("Required discovery field is missing")
    if type(message["schema"]) is not int or message["schema"] != 1:
        raise DiscoveryError("Unsupported discovery schema")
    product_id = identity[0]
    if message["product_id"] != product_id:
        raise DiscoveryError("MQTT topic and product_id do not match")
    expected_type = "agent" if product_id.endswith("_agent") else "app"
    if message["type"] != expected_type:
        raise DiscoveryError("Product type does not match its identity")
    if not isinstance(message["version"], str) or not VERSION_RE.fullmatch(message["version"]):
        raise DiscoveryError("Invalid product version")
    repo = canonical_repository(message["repository"])
    path = message["product_path"]
    if path != "." and (not isinstance(path, str) or not PRODUCT_RE.fullmatch(path)):
        raise DiscoveryError("product_path must be a canonical product directory or '.'")
    if repo.lower() == "https://github.com/digitalhouses/home-assistant-apps":
        if path != product_id:
            raise DiscoveryError("Monorepo product_path must match product_id")
    key = product_id + "/" + identity[1]
    return key, {
        "schema": 1,
        "product_id": product_id,
        "type": expected_type,
        "version": message["version"],
        "repository": repo,
        "product_path": path,
    }


class ProductSources:
    """Persist accepted *claims* for read-only UI; no installation authority."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._items: dict[str, dict] = {}
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                for key, value in stored.items():
                    if not isinstance(value, dict):
                        continue
                    product, sep, instance = key.partition("/")
                    if not sep or not instance:
                        continue
                    topic = SOURCE_ROOT + product + (
                        "/" + instance if instance != "default" else ""
                    ) + "/sync"
                    try:
                        valid_key, canonical = validate_sync_message(
                            topic, json.dumps(value).encode()
                        )
                    except (DiscoveryError, TypeError, ValueError):
                        continue
                    if valid_key == key:
                        self._items[key] = canonical
        except (FileNotFoundError, OSError, ValueError):
            pass

    def apply(self, topic: str, payload: bytes | str) -> bool:
        key, value = validate_sync_message(topic, payload)
        with self._lock:
            if self._items.get(key) == value:
                return False
            self._items[key] = value
            return True

    def snapshot(self) -> dict[str, dict]:
        with self._lock:
            return {key: value.copy() for key, value in sorted(self._items.items())}

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".dh-sources-", dir=self.path.parent)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(self._items, stream, sort_keys=True, indent=2)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(tmp, self.path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
