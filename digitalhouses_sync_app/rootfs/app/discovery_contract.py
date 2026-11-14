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

# Source admission has ONE rule: GitHub repository owner DigitalHouses.
# The remaining parsing is transport hygiene, not a product approval registry.
TOPIC_PART = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,95}\Z", re.ASCII)
REPO_PART = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z", re.ASCII)
FOLDER_PART = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}\Z", re.ASCII)
SOURCE_ROOT = "DigitalHouses/Global/"
EXPECTED_OWNER = "DigitalHouses"
MAX_PAYLOAD = 4096


class DiscoveryError(ValueError):
    pass


def canonical_repository(value: str) -> str:
    """Accept any actual GitHub repository under the DigitalHouses owner."""
    if not isinstance(value, str) or len(value) > 220:
        raise DiscoveryError("Repository URL missing or oversized")
    if not value.isascii() or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        raise DiscoveryError("Invalid repository URL")
    if any(c in value for c in ("@", "%", "\\", "?", "#")):
        raise DiscoveryError("Ambiguous repository URL")
    try:
        url = urlsplit(value)
    except ValueError as exc:
        raise DiscoveryError("Malformed repository URL") from exc
    try:
        is_github = (url.scheme == "https" and url.netloc.lower() == "github.com"
                     and url.hostname == "github.com" and url.username is None
                     and url.password is None and url.port is None)
    except ValueError as exc:
        raise DiscoveryError("Malformed repository URL port") from exc
    if not is_github:
        raise DiscoveryError("Repository must be a direct GitHub HTTPS URL")
    parts = url.path.removesuffix("/").split("/")
    if len(parts) != 3 or parts[0] or parts[1].lower() != EXPECTED_OWNER.lower():
        raise DiscoveryError("GitHub repository owner must be DigitalHouses")
    name = parts[2]
    if not REPO_PART.fullmatch(name) or name in (".", ".."):
        raise DiscoveryError("Missing or invalid GitHub repository name")
    return f"https://github.com/{EXPECTED_OWNER}/{name}"


def safe_product_path(value: object, product: str) -> str:
    """A safe relative lookup location; bad metadata falls back to product ID."""
    if not isinstance(value, str) or not value or len(value) > 240:
        return product
    if value == ".":
        return "."
    parts = value.split("/")
    if any(not FOLDER_PART.fullmatch(part) or part in (".", "..") for part in parts):
        return product
    return "/".join(parts)


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
    if not TOPIC_PART.fullmatch(product) or not TOPIC_PART.fullmatch(instance):
        return None
    return product, instance


def validate_sync_message(topic: str, payload: bytes | str) -> tuple[str, dict]:
    identity = parse_sync_topic(topic)
    if identity is None:
        raise DiscoveryError("Unsupported MQTT sync topic")
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_PAYLOAD:
        raise DiscoveryError("Invalid MQTT payload size")
    try:
        message = json.loads(raw.decode("utf-8", "strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DiscoveryError("Invalid MQTT sync JSON") from exc
    if not isinstance(message, dict):
        raise DiscoveryError("MQTT sync payload must be a JSON object")

    # Only rejection/approval condition for a well-formed message.
    repo = canonical_repository(message.get("repository"))
    product, instance = identity
    version = message.get("version")
    product_type = message.get("type")
    return product + "/" + instance, {
        "schema": 1,
        "product_id": product,  # the topic is authoritative for the identity
        "type": product_type if isinstance(product_type, str) else "unknown",
        "version": version if isinstance(version, str) else "unknown",
        "repository": repo,
        "product_path": safe_product_path(message.get("product_path"), product),
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
