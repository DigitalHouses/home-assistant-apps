"""Automatic owner-only Git -> Home Assistant YAML synchronization.

Both dashboards and packages use the same routine: discover, find by YAML
identity, compare bytes, back up, atomically replace. No buttons or approval.
No Home Assistant restarts, .storage writes, source version gates or deletions.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import stat
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from apply_service import _atomic_replace, _file_sync, _save_json
from discovery_contract import canonical_repository, safe_product_path
from git_source import BACKEND
from local_audit import _local_snapshot, _safe_path
from resource_preview import parse_view

LOG = logging.getLogger("dh_sync.auto")
VIEW_DIR = Path("dashboards/dh/views")
PACKAGE_DIR = Path("packages")
DEFAULT_PACKAGE_DIR = PACKAGE_DIR / "dh"
MAX_BYTES = 1_000_000
MAX_FILES = 300
FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.yaml\Z", re.ASCII)
PACKAGE_LOADER = re.compile(
    r"(?m)^\s+packages:\s*!include_dir_merge_named\s+packages/?\s*(?:#.*)?$")
CATEGORIES = ("dashboards/ru", "packages/common", "packages/locales/ru")


class SyncError(ValueError):
    pass


def digest(content: bytes | None) -> str | None:
    return hashlib.sha256(content).hexdigest() if content is not None else None


def package_keys(raw: bytes) -> list[str]:
    """Read HA package keys without constructing HA-specific YAML tags."""
    try:
        node = yaml.compose(raw.decode("utf-8", "strict"), Loader=yaml.BaseLoader)
    except (UnicodeError, yaml.YAMLError, RecursionError) as exc:
        raise SyncError("Package YAML is invalid") from exc
    if not isinstance(node, yaml.MappingNode) or not node.value:
        raise SyncError("Package has no top-level keys")
    result = []
    for key_node, value_node in node.value:
        if (not isinstance(key_node, yaml.ScalarNode)
                or not isinstance(value_node, yaml.MappingNode)):
            raise SyncError("Invalid package structure")
        key = key_node.value
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", key):
            raise SyncError("Invalid package name")
        if key in result:
            raise SyncError("Duplicate package key")
        result.append(key)
    return result


def package_identity(raw: bytes) -> str:
    keys = package_keys(raw)
    if len(keys) != 1:
        raise SyncError("Canonical package must have one top-level key")
    return keys[0]


def _safe_file(root: Path, relative: Path) -> Path:
    path = root / relative
    _safe_path(root, path)
    if path.exists() and not path.is_file():
        raise SyncError("YAML destination is not a file")
    return path


class AutoSync:
    def __init__(self, root: Path = Path("/homeassistant"),
                 data: Path = Path("/data/dh-sync-auto"), *, backend=None):
        self.root = Path(root)
        self.data = Path(data)
        self.backend = backend if backend is not None else BACKEND
        self.lock = threading.RLock()
        self.report = {
            "last_run": "", "state": "Ожидание MQTT", "updated": 0,
            "unchanged": 0, "issues": [], "resources": [],
        }

    def status(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.report, ensure_ascii=False))

    def _check_root(self) -> None:
        if not self.root.is_dir() or self.root.is_symlink():
            raise SyncError("Home Assistant configuration unavailable")
        if os.statvfs(self.root).f_flag & getattr(os, "ST_RDONLY", 1):
            raise SyncError("Home Assistant configuration is read-only")
        if not (self.root / VIEW_DIR).is_dir():
            raise SyncError("DigitalHouses dashboard directory unavailable")
        _safe_path(self.root, self.root / VIEW_DIR)

    def _local_views(self) -> tuple[dict, dict, set]:
        snap = _local_snapshot(self.root)
        if snap["issues"]:
            raise SyncError("; ".join(snap["issues"])[:180])
        return snap["by_path"], snap["by_name"], snap["storage_paths"]

    def _local_packages(self) -> dict[str, list[Path]]:
        root = self.root / PACKAGE_DIR
        _safe_path(self.root, root)
        if not root.is_dir():
            return {}
        files = sorted(root.rglob("*.yaml"))
        if len(files) > MAX_FILES:
            raise SyncError("Too many local package files")
        found: dict[str, list[Path]] = {}
        for path in files:
            _safe_path(self.root, path)
            if not path.is_file() or path.stat().st_size > MAX_BYTES:
                raise SyncError("Unsafe local package file")
            for key in package_keys(path.read_bytes()):
                found.setdefault(key, []).append(path.relative_to(self.root))
        return found

    def _published(self, claims: dict) -> tuple[list[dict], list[str]]:
        """Resolve each Git repository once; any owned product is eligible."""
        resources, issues = [], []
        seen_products = set()
        for identity, claim in sorted(claims.items()):
            try:
                repository = canonical_repository(claim["repository"])
                product = claim["product_id"]
                folder = safe_product_path(claim.get("product_path"), product)
                source_id = (repository, folder)
                if source_id in seen_products:
                    continue  # multiple agent instances share the same YAML
                seen_products.add(source_id)
                commit, _ = self.backend.resolve_revision(repository)
                prefix = "" if folder == "." else folder + "/"
                for category in CATEGORIES:
                    canonical = prefix + category
                    for item in self.backend.list_yaml(repository, canonical, commit):
                        name, source = item["name"], item["path"]
                        if not FILE.fullmatch(name) or source != canonical + "/" + name:
                            raise SyncError("Unsafe Git YAML name or path")
                        raw = self.backend.read_view(repository, source, commit)
                        if not raw or len(raw) > MAX_BYTES:
                            raise SyncError("Git YAML file missing or too large")
                        if category == "dashboards/ru":
                            metadata = parse_view(raw, source, product)
                            key = metadata["path"]
                            kind = "view"
                        else:
                            key = package_identity(raw)
                            kind = "package"
                        resources.append({
                            "product": product, "repository": repository,
                            "source": source, "commit": commit, "kind": kind,
                            "identity": key, "name": name, "bytes": raw,
                        })
            except Exception as exc:
                issues.append(identity + ": " + str(exc)[:100])
                LOG.warning("Source skipped: %s: %s", identity, exc)
        # Do not let two different Git resources fight for one local identity.
        count: dict[tuple[str, str], int] = {}
        for r in resources:
            key = r["kind"], r["identity"]
            count[key] = count.get(key, 0) + 1
        for r in resources:
            if count[r["kind"], r["identity"]] > 1:
                issues.append(r["product"] + ": conflicting canonical " + r["identity"])
        return [r for r in resources if count[r["kind"], r["identity"]] == 1], issues

    def _destination(self, item: dict, views: tuple,
                     packages: dict) -> Path:
        key, name = item["identity"], item["name"]
        if item["kind"] == "view":
            by_path, by_name, storage = views
            if key in storage:
                raise SyncError("Lovelace Storage path collision: " + key)
            matches = by_path.get(key, [])
            if len(matches) > 1:
                raise SyncError("Duplicate local view path: " + key)
            matching = matches[0] if matches else None
            collision = by_name.get(name)
            if collision is not None and collision is not matching:
                raise SyncError("Dashboard filename occupied: " + name)
            return VIEW_DIR / (matching["name"] if matching else name)
        matches = packages.get(key, [])
        if len(matches) > 1:
            raise SyncError("Duplicate local package key: " + key)
        if matches:
            if len(package_keys(_safe_file(self.root, matches[0]).read_bytes())) != 1:
                raise SyncError("Shared local package file cannot be replaced")
            return matches[0]
        if not PACKAGE_LOADER.search(
                (self.root / "configuration.yaml").read_text(encoding="utf-8")):
            raise SyncError("Home Assistant packages loader is not configured")
        return DEFAULT_PACKAGE_DIR / name

    def _apply_one(self, relative: Path, source: dict) -> bool:
        """One durable file transaction. Failure restores original automatically."""
        target = _safe_file(self.root, relative)
        old = target.read_bytes() if target.exists() else None
        new = source["bytes"]
        if old == new:
            return False
        info = target.stat() if target.exists() else None
        mode = stat.S_IMODE(info.st_mode) if info else 0o644
        uid = info.st_uid if info else os.getuid()
        gid = info.st_gid if info else os.getgid()
        self.data.mkdir(parents=True, mode=0o700, exist_ok=True)
        journal = self.data / ("tx-" + secrets.token_hex(10))
        journal.mkdir(mode=0o700)
        manifest = {
            "path": relative.as_posix(), "before": digest(old),
            "after": digest(new), "source": source["source"],
            "commit": source["commit"], "mode": mode, "uid": uid,
            "gid": gid, "state": "prepared",
        }
        if old is not None:
            _file_sync(journal / "original.yaml", old)
        _save_json(journal / "manifest.json", manifest)
        try:
            _safe_path(self.root, target)
            current = target.read_bytes() if target.exists() else None
            if digest(current) != manifest["before"]:
                raise SyncError("Local YAML changed during synchronization")
            if not target.parent.exists():
                target.parent.mkdir(parents=True)
            _safe_path(self.root, target)
            _atomic_replace(target, new, mode, uid, gid)
            manifest["state"] = "applied"
            _save_json(journal / "manifest.json", manifest)
            return True
        except Exception:
            try:
                _safe_path(self.root, target)
                current = target.read_bytes() if target.exists() else None
                if digest(current) == manifest["after"]:
                    if old is None:
                        target.unlink()
                    else:
                        _atomic_replace(target, old, mode, uid, gid)
                manifest["state"] = "recovered"
                _save_json(journal / "manifest.json", manifest)
            except Exception:
                LOG.exception("YAML transaction requires manual recovery: %s", relative)
            raise

    def recover(self) -> None:
        """Recover only an interrupted write, without overwriting later edits."""
        if not self.data.is_dir():
            return
        for file in sorted(self.data.glob("tx-*/manifest.json")):
            if file.is_symlink() or file.parent.is_symlink():
                continue
            try:
                manifest = json.loads(file.read_text(encoding="utf-8"))
                if manifest.get("state") != "prepared":
                    continue
                relative = Path(manifest["path"])
                target = _safe_file(self.root, relative)
                current = target.read_bytes() if target.exists() else None
                if digest(current) not in (manifest["before"], manifest["after"]):
                    raise SyncError("Recovery skipped because YAML was edited: " + str(relative))
                if digest(current) == manifest["after"]:
                    if manifest["before"] is None:
                        target.unlink()
                    else:
                        original = (file.parent / "original.yaml").read_bytes()
                        if digest(original) != manifest["before"]:
                            raise SyncError("Backup SHA mismatch")
                        _atomic_replace(target, original, manifest["mode"],
                                        manifest["uid"], manifest["gid"])
                manifest["state"] = "recovered"
                _save_json(file, manifest)
            except Exception:
                LOG.exception("Recovery failed: %s", file.parent.name)
                raise SyncError("An unfinished YAML transaction needs recovery")

    def sync(self, claims: dict) -> dict:
        with self.lock:
            report = {
                "last_run": datetime.now(timezone.utc).isoformat(),
                "state": "OK", "updated": 0, "unchanged": 0,
                "issues": [], "resources": [],
            }
            try:
                self._check_root()
                self.recover()
                resources, issues = self._published(claims)
                report["issues"].extend(issues)
                views = self._local_views()
                packages = self._local_packages()
                destinations = set()
                for source in resources:
                    label = source["product"] + " / " + source["name"]
                    try:
                        dest = self._destination(source, views, packages)
                        if dest in destinations:
                            raise SyncError("Two resources have same destination")
                        destinations.add(dest)
                        target = _safe_file(self.root, dest)
                        if target.exists() and source["kind"] == "package":
                            if package_identity(target.read_bytes()) != source["identity"]:
                                raise SyncError("Destination package has another key")
                        if self._apply_one(dest, source):
                            report["updated"] += 1
                            outcome = "Updated"
                            # Refresh identities for subsequent files in same pass.
                            if source["kind"] == "view":
                                views = self._local_views()
                            else:
                                packages = self._local_packages()
                        else:
                            report["unchanged"] += 1
                            outcome = "Current"
                    except Exception as exc:
                        outcome = "Skipped: " + str(exc)[:150]
                        report["issues"].append(label + ": " + str(exc)[:150])
                    report["resources"].append({"name": label, "status": outcome})
                if report["issues"]:
                    report["state"] = "Partial" if report["updated"] or report["unchanged"] else "Error"
            except Exception as exc:
                report["state"] = "Error"
                report["issues"].append(str(exc)[:200])
                LOG.exception("Automatic sync failed")
            self.report = report
            LOG.info("Auto-sync %s: updated=%s current=%s issues=%s",
                     report["state"], report["updated"], report["unchanged"],
                     len(report["issues"]))
            return self.status()
