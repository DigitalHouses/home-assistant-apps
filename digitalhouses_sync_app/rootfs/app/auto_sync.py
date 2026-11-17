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
PACKAGE_INCLUDE = "  packages: !include_dir_merge_named packages/\n"
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


def configured_packages(raw: bytes) -> bytes | None:
    """Add the canonical HA package include without reformatting user YAML.

    Returns None when already configured. Unknown or conflicting configurations
    are never overwritten; the caller reports a visible error instead.
    """
    try:
        content = raw.decode("utf-8", "strict")
        doc = yaml.compose(content, Loader=yaml.BaseLoader)
    except (UnicodeError, yaml.YAMLError, RecursionError) as exc:
        raise SyncError("configuration.yaml is invalid") from exc
    if doc is not None and not isinstance(doc, yaml.MappingNode):
        raise SyncError("configuration.yaml must be a YAML mapping")
    home = []
    if doc is not None:
        for key, value in doc.value:
            if not isinstance(key, yaml.ScalarNode):
                raise SyncError("configuration.yaml has an invalid YAML key")
            if key.value == "homeassistant":
                home.append((key, value))
    if len(home) > 1:
        raise SyncError("Multiple homeassistant sections in configuration.yaml")
    if not home:
        separator = "" if not content else ("\n" if content.endswith("\n") else "\n\n")
        return (content + separator + "homeassistant:\n" + PACKAGE_INCLUDE).encode("utf-8")

    key, section = home[0]
    if isinstance(section, yaml.MappingNode):
        if section.flow_style:
            raise SyncError("Inline homeassistant configuration must be preserved")
        members = []
        for subkey, subvalue in section.value:
            if not isinstance(subkey, yaml.ScalarNode):
                raise SyncError("Invalid homeassistant configuration")
            if subkey.value == "packages":
                members.append((subkey, subvalue))
        if len(members) > 1:
            raise SyncError("Multiple packages declarations in configuration.yaml")
        if members:
            value = members[0][1]
            if (isinstance(value, yaml.ScalarNode)
                    and value.tag == "!include_dir_merge_named"
                    and value.value.strip().rstrip("/") == "packages"):
                return None
            raise SyncError("Existing packages configuration is not merge_named packages/")
        indent = section.value[0][0].start_mark.column if section.value else key.start_mark.column + 2
    elif (isinstance(section, yaml.ScalarNode) and
          section.value == "" and section.style is None):
        indent = key.start_mark.column + 2
    else:
        raise SyncError("Existing homeassistant configuration cannot be modified safely")

    lines = content.splitlines(keepends=True)
    line = key.start_mark.line
    if line >= len(lines) or not lines[line].endswith("\n"):
        raise SyncError("Unsupported homeassistant YAML layout")
    # Preserve the surrounding YAML and comments verbatim.
    lines.insert(line + 1, " " * indent + PACKAGE_INCLUDE.lstrip())
    updated = "".join(lines).encode("utf-8")
    try:
        yaml.compose(updated.decode("utf-8"), Loader=yaml.BaseLoader)
    except yaml.YAMLError as exc:
        raise SyncError("Cannot safely update configuration.yaml") from exc
    return updated


def _safe_file(root: Path, relative: Path) -> Path:
    path = root / relative
    _safe_path(root, path)
    if path.exists() and not path.is_file():
        raise SyncError("YAML destination is not a file")
    return path


class AutoSync:
    def __init__(self, root: Path = Path("/homeassistant"),
                 data: Path = Path("/data/dh-sync-auto"), *, backend=None,
                 publisher=None, reloader=None):
        self.root = Path(root)
        self.data = Path(data)
        self.backend = backend if backend is not None else BACKEND
        self.publisher = publisher
        self.reloader = reloader
        self.lock = threading.RLock()
        self.report = {
            "last_run": "", "state": "Ожидание MQTT", "updated": 0,
            "unchanged": 0, "issues": [], "resources": [], "dashboard": None,
            "packages": None,
        }

    def status(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.report, ensure_ascii=False))

    def _check_root(self) -> None:
        if not self.root.is_dir() or self.root.is_symlink():
            raise SyncError("Home Assistant configuration unavailable")
        if os.statvfs(self.root).f_flag & getattr(os, "ST_RDONLY", 1):
            raise SyncError("Home Assistant configuration is read-only")
        # A newly installed HA instance may have no DH dashboard or package tree.
        # Bootstrap only missing paths; do not replace existing local resources.
        for relative in (VIEW_DIR, DEFAULT_PACKAGE_DIR):
            folder = self.root / relative
            _safe_path(self.root, folder)
            if folder.exists() and not folder.is_dir():
                raise SyncError("YAML directory is occupied: " + relative.as_posix())
            try:
                folder.mkdir(mode=0o755, parents=True, exist_ok=True)
            except OSError as exc:
                raise SyncError("Cannot create YAML directory: " + relative.as_posix()) from exc
            _safe_path(self.root, folder)

        ui = self.root / "dashboards/dh/ui.yaml"
        _safe_path(self.root, ui)
        if not ui.exists():
            _atomic_replace(
                ui, b"title: DigitalHouses\nviews: !include_dir_list views/\n",
                0o644, os.getuid(), os.getgid(),
            )
        elif not ui.is_file():
            raise SyncError("DigitalHouses ui.yaml is not a file")

    def _local_views(self) -> tuple[dict, dict, set]:
        snap = _local_snapshot(self.root, include_storage=False)
        if snap["issues"]:
            raise SyncError("; ".join(snap["issues"])[:180])
        return snap["by_path"], snap["by_name"]

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
            by_path, by_name = views
            # Paths in other dashboards (including Storage dashboards) have
            # distinct URL prefixes and do not collide with DigitalHouses YAML.
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
        return DEFAULT_PACKAGE_DIR / name

    def _ensure_package_loader(self) -> str:
        """Install the HA packages include with the ordinary backup transaction."""
        file = _safe_file(self.root, Path("configuration.yaml"))
        old = file.read_bytes() if file.exists() else b""
        new = configured_packages(old)
        if new is None:
            return "Current"
        source = {
            "bytes": new, "source": "dh-sync/package-loader",
            "commit": "local-configuration",
        }
        self._apply_one(Path("configuration.yaml"), source)
        return "Configured"

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
                "issues": [], "resources": [], "dashboard": None,
                "packages": None,
            }
            try:
                self._check_root()
                self.recover()
                resources, issues = self._published(claims)
                report["issues"].extend(issues)
                views = self._local_views()
                packages = self._local_packages()
                destinations = set()
                package_sources = [s for s in resources if s["kind"] == "package"]
                loader_problem = None
                if package_sources:
                    try:
                        loader_state = self._ensure_package_loader()
                        report["packages"] = {"loader": loader_state, "reload": "Not needed"}
                    except Exception as exc:
                        loader_problem = str(exc)[:150]
                        report["packages"] = {"loader": "Unavailable", "reload": "Not needed"}
                changed_packages = 0
                for source in resources:
                    label = source["product"] + " / " + source["name"]
                    try:
                        if source["kind"] == "package" and loader_problem:
                            raise SyncError("Packages configuration: " + loader_problem)
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
                            if source["kind"] == "package":
                                changed_packages += 1
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
                if changed_packages or (report["packages"] and
                                        report["packages"]["loader"] == "Configured"):
                    if self.reloader is not None:
                        try:
                            self.reloader()
                            report["packages"]["reload"] = "Requested"
                        except Exception as exc:
                            report["packages"]["reload"] = "Unavailable"
                            report["issues"].append("Packages quick reload: " + str(exc)[:150])
                    else:
                        report["packages"]["reload"] = "Not available"
                if self.publisher is not None:
                    try:
                        report["dashboard"] = self.publisher.sync()
                    except Exception as exc:
                        report["issues"].append("DigitalHouses Dashboard: " + str(exc)[:150])
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
