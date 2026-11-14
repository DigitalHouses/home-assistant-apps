"""DH Sync v0.1.0: allowlisted, manually approved YAML view delivery.

No automatic writes, no .storage writes, no packages and no agent updates.
The only supported destination is the existing DigitalHouses YAML dashboard.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


class SyncError(ValueError):
    pass


# Git commits are immutable, including the reviewed (still Draft) PVE PR head.
# Do NOT use product binary release tags: they predate these canonical YAMLs.
PVE_SHA = "2b7a7857ab5fe2d4c8493faacbfd1b43518ed087"
PLEX_SHA = "d4e99ac789b6bd53c4185bff0612edff5427d315"
MAX_SOURCE = 600_000
MAX_VIEW = 800_000
VIEW_DIR = Path("dashboards/dh/views")
UI = Path("dashboards/dh/ui.yaml")
LOCALE = "ru"


@dataclass(frozen=True)
class Resource:
    product: str
    source: str
    sha: str
    target: str
    view_path: str
    icon: str
    version_sensor: str
    agent_version: str
    compat: str
    legacy_sha: str | None = None


RESOURCES = (
    Resource(
        "digitalhouses_pve_agent",
        "digitalhouses_pve_agent/dashboards/ru/10_pve_proxmox.yaml",
        PVE_SHA, "10_pve_proxmox.yaml", "dh_pve_agent", "mdi:server",
        "sensor.dh_pve_agent_version", "0.5.88", ">=0.5.88,<0.5.89",
        "e41b1f9fe0736f8cf80f31e58214d3e1483200b091f4d8dee086e02e8966626d",
    ),
    Resource(
        "digitalhouses_pve_agent",
        "digitalhouses_pve_agent/dashboards/ru/11_pve_ups.yaml",
        PVE_SHA, "11_pve_ups.yaml", "dh_pve_agent_ups", "mdi:power-plug-battery",
        "sensor.dh_pve_agent_version", "0.5.88", ">=0.5.88,<0.5.89",
        "5aef50ab9e4d5db307e1c66a2924a20f38638a77ebd70d06311aa697fd082f96",
    ),
    Resource(
        "digitalhouses_plex_agent",
        "digitalhouses_plex_agent/dashboards/ru/10_plex.yaml",
        PLEX_SHA, "12_plex.yaml", "dh-plex-agent", "mdi:plex",
        "sensor.dh_plex_agent_version", "0.8.17", ">=0.8.17,<0.8.18",
    ),
)


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_digest(data: Any) -> str:
    return _digest(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode())


class NoDuplicateLoader(yaml.SafeLoader):
    pass


def _no_duplicates(loader: yaml.SafeLoader, node: yaml.MappingNode) -> dict:
    result: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, (str, int, float, bool)) or key in result:
            raise SyncError("Duplicate or unsupported YAML mapping key")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


NoDuplicateLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates
)


def _parse_yaml(raw: bytes) -> dict:
    try:
        document = yaml.load(raw.decode("utf-8"), Loader=NoDuplicateLoader)
    except (UnicodeDecodeError, yaml.YAMLError, RecursionError) as exc:
        raise SyncError(f"Invalid YAML view: {exc}") from exc
    if not isinstance(document, dict):
        raise SyncError("Expected a Lovelace view mapping")
    return document


def _check_safe_path(root: Path, path: Path) -> None:
    try:
        parts = path.relative_to(root).parts
    except ValueError as exc:
        raise SyncError("Path escapes Home Assistant root") from exc
    if root.is_symlink():
        raise SyncError("Home Assistant root is a symlink")
    current = root
    for part in parts:
        current /= part
        if current.is_symlink():
            raise SyncError(f"Symlinks are not allowed: {current}")


def _read(root: Path, path: Path, limit: int = MAX_VIEW) -> bytes:
    _check_safe_path(root, path)
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise SyncError(f"Unsafe or oversized file: {path}")
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise SyncError(f"File exceeded size limit: {path}")
        return raw
    except OSError as exc:
        raise SyncError(f"Cannot read file {path}: {exc}") from exc


def _source(resource: Resource) -> bytes:
    url = (
        "https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/"
        + resource.sha + "/" + resource.source
    )
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "DigitalHouses-Sync/0.1"})
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read(MAX_SOURCE + 1)
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise SyncError(f"GitHub source unavailable for {resource.target}") from exc
    if len(raw) > MAX_SOURCE:
        raise SyncError("Canonical YAML exceeds size limit")
    return raw


def _validate_source(resource: Resource, raw: bytes) -> dict:
    headers = raw.decode("utf-8", "strict").splitlines()[:8]
    for required in (
        "# DH-View: dh_pve_agent" if resource.product == "digitalhouses_pve_agent"
        else "# DH-View: dh_plex_agent",
        "# DH-View-Version: 1.0.0",
        "# DH-Compatible-Agent: " + resource.compat,
    ):
        if required not in headers:
            raise SyncError(f"Canonical metadata mismatch in {resource.target}: {required}")
    body = _parse_yaml(raw)
    if (
        body.get("path") != resource.view_path
        or body.get("icon") != resource.icon
        or body.get("type") != "sections"
        or not isinstance(body.get("sections"), list)
        or "views" in body
        or "lovelace" in body
    ):
        raise SyncError(f"Invalid canonical view identity in {resource.target}")
    if resource.product == "digitalhouses_pve_agent" and body.get("show_icon_and_title") is not False:
        raise SyncError(f"Icon-only navigation missing in {resource.target}")
    return body


def _check_existing_legacy(resource: Resource, raw: bytes, canonical: dict) -> bool:
    if not resource.legacy_sha or _digest(raw) != resource.legacy_sha:
        return False
    old = _parse_yaml(raw)
    # Exactly the operator-approved differences: top-level nav style and UPS icon.
    expected = dict(canonical)
    expected["show_icon_and_title"] = True
    if resource.target == "11_pve_ups.yaml":
        expected["icon"] = "mdi:power-plug-battery-outline"
    return old == expected


def _view_paths_in_storage(home: Path) -> set[str]:
    folder = home / ".storage"
    if not folder.exists():
        return set()
    if not folder.is_dir():
        raise SyncError("HA .storage is not a directory")
    _check_safe_path(home, folder)
    paths: set[str] = set()
    for file in folder.iterdir():
        if file.name != "lovelace" and not file.name.startswith("lovelace.dashboard_"):
            continue
        try:
            doc = json.loads(_read(home, file, limit=10_000_000))
        except (ValueError, UnicodeDecodeError) as exc:
            raise SyncError(f"Unreadable Lovelace Storage file: {file.name}") from exc
        if not isinstance(doc, dict) or not isinstance(doc.get("data"), dict):
            raise SyncError(f"Unexpected Lovelace Storage structure: {file.name}")
        cfg = doc["data"].get("config", doc["data"])
        if not isinstance(cfg, dict):
            raise SyncError(f"Invalid Storage config: {file.name}")
        views = cfg.get("views", [])
        if not isinstance(views, list):
            raise SyncError(f"Invalid Storage views: {file.name}")
        for view in views:
            if isinstance(view, dict) and isinstance(view.get("path"), str):
                paths.add(view["path"])
    return paths


def _atomic_replace(path: Path, raw: bytes, mode: int, uid: int | None, gid: int | None) -> None:
    fd, temp = tempfile.mkstemp(prefix=".dh-sync-", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        if uid is not None and gid is not None:
            os.fchown(fd, uid, gid)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        _fsync_dir(path.parent)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _save_json(path: Path, document: dict) -> None:
    _atomic_replace(path, (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(), 0o600, None, None)


@contextmanager
def _lock(root: Path):
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink():
        raise SyncError("Symlink in transaction directory")
    lockfile = root / ".lock"
    if lockfile.is_symlink():
        raise SyncError("Symlink in transaction lock")
    with lockfile.open("a+b") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SyncError("Another DH Sync operation is already active") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


class SyncEngine:
    def __init__(self, home: Path, data: Path, api: Any, *, fetcher=_source):
        self.home = home
        self.data = data
        self.api = api
        self.fetcher = fetcher
        self.views = home / VIEW_DIR
        self.ui = home / UI
        self.transactions = data / "sync-v01" / "transactions"

    def _validate_layout(self) -> None:
        if not self.home.is_dir() or self.home.is_symlink():
            raise SyncError("HA configuration directory unavailable")
        if not self.data.is_dir() or self.data.is_symlink():
            raise SyncError("/data directory unavailable")
        if not self.views.is_dir() or self.views.is_symlink():
            raise SyncError("Existing DigitalHouses views directory required")
        _check_safe_path(self.home, self.views)
        ui_raw = _read(self.home, self.ui).decode("utf-8", "strict")
        if not re.search(r"(?m)^views:\s*!include_dir_list\s+views/?\s*(?:#.*)?$", ui_raw):
            raise SyncError("DigitalHouses must use views: !include_dir_list views/")
        if not re.search(r"(?m)^title:\s*DigitalHouses\s*$", ui_raw):
            raise SyncError("Unknown parent DigitalHouses dashboard")
        dashboard = self.api.dashboard()
        if not isinstance(dashboard, dict) or not isinstance(dashboard.get("views"), list):
            raise SyncError("Registered digital-houses YAML dashboard not readable")

    def _check_duplicates(self) -> None:
        known: dict[str, str] = {}
        for file in sorted(self.views.iterdir()):
            if file.suffix not in (".yaml", ".yml"):
                continue
            body = _parse_yaml(_read(self.home, file))
            path = body.get("path")
            if not isinstance(path, str) or not path:
                raise SyncError(f"View without stable path: {file.name}")
            if path in known:
                raise SyncError(f"Duplicate Lovelace path {path}: {known[path]} and {file.name}")
            known[path] = file.name
        storage = _view_paths_in_storage(self.home)
        for r in RESOURCES:
            if r.view_path in storage:
                raise SyncError(f"Existing Storage view blocks YAML adoption: {r.view_path}")
            other = known.get(r.view_path)
            if other is not None and other != r.target:
                raise SyncError(f"Existing view path {r.view_path} is owned by {other}")

    def plan(self) -> dict:
        """Rebuild plan from live state, HA registration and immutable Git sources."""
        self._validate_layout()
        self._check_duplicates()
        sensors = self.api.versions()
        results = []
        fingerprints = []
        for r in RESOURCES:
            canonical = self.fetcher(r)
            expected = _validate_source(r, canonical)
            target = self.views / r.target
            if target.exists() or target.is_symlink():
                current = _read(self.home, target)
                old_hash = _digest(current)
                if current == canonical or _parse_yaml(current) == expected:
                    action = "unchanged"
                elif _check_existing_legacy(r, current, expected):
                    action = "replace"
                else:
                    action = "conflict"
            else:
                current = None
                old_hash = None
                action = "create"
            live = sensors.get(r.version_sensor)
            if live != r.agent_version:
                action = "incompatible"
            results.append({
                "product": r.product,
                "path": r.target,
                "view_path": r.view_path,
                "title": expected.get("title"),
                "icon": r.icon,
                "action": action,
                "installed_agent": live or "unavailable",
                "required_agent": r.agent_version,
                "source_commit": r.sha,
                "source_sha256": _digest(canonical),
                "installed_sha256": old_hash,
                "_content": canonical,
            })
            fingerprints.append({
                "path": r.target,
                "action": action,
                "old": old_hash,
                "new": _digest(canonical),
                "agent": live,
            })
        blocked = any(v["action"] in ("conflict", "incompatible") for v in results)
        fingerprint = _json_digest(fingerprints)
        return {"items": results, "blocked": blocked,
                "changes": sum(x["action"] in ("replace", "create") for x in results),
                "fingerprint": fingerprint, "locale": LOCALE,
                "packages_supported": False, "automatic_apply": False}

    @staticmethod
    def public(plan: dict) -> dict:
        return {**plan, "items": [{k: v for k, v in item.items() if not k.startswith("_")}
                                  for item in plan["items"]]}

    def _latest(self) -> tuple[Path, dict] | None:
        if not self.transactions.exists():
            return None
        folders = sorted((x for x in self.transactions.iterdir() if x.is_dir()), reverse=True)
        for folder in folders:
            journal = folder / "journal.json"
            if journal.exists():
                try:
                    return folder, json.loads(journal.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    raise SyncError("Transaction journal cannot be read") from exc
        return None

    def _rollback_files(self, folder: Path, journal: dict) -> None:
        # Check ALL files for unexpected edits before changing any single file.
        for entry in journal["files"]:
            target = self.views / entry["name"]
            if target.exists() or target.is_symlink():
                digest = _digest(_read(self.home, target))
                if digest not in (entry["after"], entry["before"]):
                    raise SyncError(f"File modified after apply, refusing rollback: {entry['name']}")
            elif entry["before"] is not None:
                raise SyncError(f"Existing view unexpectedly disappeared: {entry['name']}")
        for entry in reversed(journal["files"]):
            target = self.views / entry["name"]
            if entry["before"] is None:
                if target.exists():
                    target.unlink()
                    _fsync_dir(self.views)
            else:
                saved = _read(self.data, folder / ("backup_" + entry["name"]))
                if _digest(saved) != entry["before"]:
                    raise SyncError("Backup SHA mismatch; rollback stopped")
                _atomic_replace(target, saved, entry["mode"], entry["uid"], entry["gid"])

    def apply(self, expected_fingerprint: str, *, approved: bool) -> dict:
        if not approved:
            raise SyncError("Explicit approval required")
        if not re.fullmatch(r"[0-9a-f]{64}", expected_fingerprint):
            raise SyncError("Invalid preview fingerprint")
        with _lock(self.transactions):
            latest = self._latest()
            if latest and latest[1].get("phase") not in ("committed", "rolled_back", "rolled_back_auto"):
                raise SyncError("Incomplete transaction must be recovered before another apply")
            plan = self.plan()
            if plan["fingerprint"] != expected_fingerprint:
                raise SyncError("Preview expired: installed files, agent state or Git sources changed")
            if plan["blocked"]:
                raise SyncError("Incompatible agent or locally modified YAML blocks the whole batch")
            if not plan["changes"]:
                return {"status": "unchanged", "updated": [], "restart_required": False}
            if not self.api.check_config():
                raise SyncError("HA configuration invalid BEFORE apply; no files changed")
            selected = [v for v in plan["items"] if v["action"] in ("replace", "create")]
            txid = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:10]
            folder = self.transactions / txid
            folder.mkdir(mode=0o700)
            entries = []
            for item in selected:
                target = self.views / item["path"]
                if target.exists():
                    original = _read(self.home, target)
                    info = target.stat()
                    backup = folder / ("backup_" + item["path"])
                    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(original)
                        stream.flush()
                        os.fsync(stream.fileno())
                    before = _digest(original)
                    mode, uid, gid = stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid
                else:
                    before, mode, uid, gid = None, 0o644, None, None
                entries.append({
                    "name": item["path"], "before": before, "after": item["source_sha256"],
                    "mode": mode, "uid": uid, "gid": gid, "source": item["source_commit"],
                })
            _fsync_dir(folder)
            journal = {"id": txid, "phase": "applying",
                       "created_at": datetime.now(timezone.utc).isoformat(),
                       "files": entries, "fingerprint": expected_fingerprint}
            _save_json(folder / "journal.json", journal)
            try:
                for item, entry in zip(selected, entries):
                    target = self.views / item["path"]
                    if entry["before"] is None:
                        if target.exists() or target.is_symlink():
                            raise SyncError(f"File appeared during apply: {item['path']}")
                    elif _digest(_read(self.home, target)) != entry["before"]:
                        raise SyncError(f"File changed during apply: {item['path']}")
                    _atomic_replace(target, item["_content"], entry["mode"], entry["uid"], entry["gid"])
                if not self.api.check_config():
                    raise SyncError("HA configuration failed AFTER apply")
                dashboard = self.api.dashboard()
                views = dashboard.get("views", []) if isinstance(dashboard, dict) else []
                for item in selected:
                    matches = [v for v in views if isinstance(v, dict) and v.get("path") == item["view_path"]]
                    if len(matches) != 1:
                        raise SyncError("Updated YAML view was not loaded by HA: " + item["path"])
                    installed_view = matches[0]
                    if installed_view.get("icon") != item["icon"]:
                        raise SyncError("HA loaded a different navigation icon: " + item["path"])
                    if item["product"] == "digitalhouses_pve_agent" and installed_view.get("show_icon_and_title") is not False:
                        raise SyncError("HA did not load icon-only navigation: " + item["path"])
            except Exception as exc:
                try:
                    self._rollback_files(folder, journal)
                    journal["phase"] = "rolled_back_auto"
                except Exception as rollback_exc:
                    journal["phase"] = "recovery_required"
                    journal["error"] = str(rollback_exc)
                _save_json(folder / "journal.json", journal)
                raise SyncError(f"Apply failed; transaction {txid}: {exc}") from exc
            journal["phase"] = "committed"
            _save_json(folder / "journal.json", journal)
            return {"status": "applied", "transaction_id": txid,
                    "updated": [x["name"] for x in entries], "restart_required": False}

    def rollback(self, *, approved: bool) -> dict:
        if not approved:
            raise SyncError("Explicit rollback confirmation required")
        with _lock(self.transactions):
            latest = self._latest()
            if not latest:
                raise SyncError("No DH Sync transaction available")
            folder, journal = latest
            if journal.get("phase") not in ("committed", "applying", "recovery_required"):
                raise SyncError("No active transaction to roll back")
            self._rollback_files(folder, journal)
            journal["phase"] = "rolled_back"
            _save_json(folder / "journal.json", journal)
            return {"status": "rolled_back", "transaction_id": journal["id"],
                    "restored": [x["name"] for x in journal["files"]],
                    "restart_required": False}

    def last_transaction(self) -> dict | None:
        latest = self._latest()
        if not latest:
            return None
        data = latest[1]
        return {"id": data.get("id"), "phase": data.get("phase"),
                "files": [x.get("name") for x in data.get("files", [])]}
