"""Automatic owner-only Git -> Home Assistant YAML synchronization.

Both dashboards and packages use the same routine: discover, find by YAML
identity, compare bytes, back up, atomically replace. No approvals.
Manual refresh requests one checked Home Assistant Core restart when the
managed Recorder package configuration has not yet been activated.
No HAOS reboot, .storage writes, source version gates or deletions.
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
from discovery_contract import (DEFAULT_DASHBOARD, canonical_repository,
                                safe_product_path, safe_dashboard_slug)
from git_source import BACKEND
from local_audit import _safe_path
from resource_preview import parse_view
from panel_config import PANEL_DIRECTORY, PANEL_REPOSITORY, parse_panel

LOG = logging.getLogger("dh_sync.auto")
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


def has_recorder_config(raw: bytes) -> bool:
    """Recognize Recorder inside canonical package YAML, not in comments.

    The package has one top-level key whose value is a mapping. Do not
    interpret arbitrary strings as active configuration.
    """
    try:
        document = yaml.compose(raw.decode("utf-8", "strict"), Loader=yaml.BaseLoader)
    except (UnicodeError, yaml.YAMLError, RecursionError) as exc:
        raise SyncError("Package YAML is invalid") from exc
    if not isinstance(document, yaml.MappingNode):
        return False
    return any(
        isinstance(body, yaml.MappingNode)
        and any(isinstance(key, yaml.ScalarNode) and key.value == "recorder"
                for key, _ in body.value)
        for _, body in document.value
    )


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
                 publisher=None, reloader=None, core_checker=None,
                 core_restarter=None):
        self.root = Path(root)
        self.data = Path(data)
        self.backend = backend if backend is not None else BACKEND
        self.publisher = publisher
        self.reloader = reloader
        self.core_checker = core_checker
        self.core_restarter = core_restarter
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
        # Bootstrap packages only. Panels are Storage dashboards, not local YAML files.
        for relative in (DEFAULT_PACKAGE_DIR,):
            folder = self.root / relative
            _safe_path(self.root, folder)
            if folder.exists() and not folder.is_dir():
                raise SyncError("YAML directory is occupied: " + relative.as_posix())
            try:
                folder.mkdir(mode=0o755, parents=True, exist_ok=True)
            except OSError as exc:
                raise SyncError("Cannot create YAML directory: " + relative.as_posix()) from exc
            _safe_path(self.root, folder)

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
        count: dict[tuple[str, str, str], int] = {}
        for r in resources:
            key = (r["kind"], r["product"] if r["kind"] == "view" else "", r["identity"])
            count[key] = count.get(key, 0) + 1
        for r in resources:
            if count[r["kind"], r["product"] if r["kind"] == "view" else "", r["identity"]] > 1:
                issues.append(r["product"] + ": conflicting canonical " + r["identity"])
        return [r for r in resources if count[r["kind"], r["product"] if r["kind"] == "view" else "", r["identity"]] == 1], issues

    def _panels(self) -> list[dict]:
        commit, _ = self.backend.resolve_revision(PANEL_REPOSITORY)
        result = []
        for item in self.backend.list_yaml(PANEL_REPOSITORY, PANEL_DIRECTORY, commit):
            raw = self.backend.read_view(PANEL_REPOSITORY, item["path"], commit)
            result.append(parse_panel(item["name"], raw))
        return result

    def _destination(self, item: dict, packages: dict) -> Path:
        key, name = item["identity"], item["name"]
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

    def _recorder_revision(self, sources: list[dict]) -> str | None:
        """Fingerprint successfully installed canonical Recorder packages.

        A digest tracks only Recorder configuration, not arbitrary Dashboard
        edits. It also detects the already-installed PBS package after DH Sync
        upgrades from an older release with no activation receipt.
        """
        recorder = [src for src in sources if has_recorder_config(src["bytes"])]
        if not recorder:
            return None
        local = self._local_packages()
        items = []
        for source in recorder:
            relative = self._destination(source, local)
            target = _safe_file(self.root, relative)
            if not target.exists() or target.read_bytes() != source["bytes"]:
                raise SyncError("Recorder package not installed: " + source["identity"])
            items.append((source["identity"], digest(source["bytes"])))
        return digest(json.dumps(sorted(items), separators=(",", ":")).encode("utf-8"))

    def _recorder_active_revision(self) -> str | None:
        receipt = self.data / "recorder_core_activation.json"
        if not receipt.exists() or receipt.is_symlink():
            return None
        try:
            data = json.loads(receipt.read_text("utf-8"))
            value = data.get("revision")
            return value if isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) else None
        except (OSError, ValueError, TypeError):
            return None

    def sync(self, claims: dict, *, refresh: bool = False) -> dict:
        with self.lock:
            if refresh:
                invalidate = getattr(self.backend, "invalidate", None)
                if callable(invalidate):
                    invalidate()
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
                for source in package_sources:
                    label = source["product"] + " / " + source["name"]
                    try:
                        if source["kind"] == "package" and loader_problem:
                            raise SyncError("Packages configuration: " + loader_problem)
                        dest = self._destination(source, packages)
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
                            packages = self._local_packages()
                        else:
                            report["unchanged"] += 1
                            outcome = "Current"
                    except Exception as exc:
                        outcome = "Skipped: " + str(exc)[:150]
                        report["issues"].append(label + ": " + str(exc)[:150])
                    report["resources"].append({"name": label, "status": outcome})
                recorder_revision = None
                if report["packages"] is not None and not loader_problem:
                    try:
                        recorder_revision = self._recorder_revision(package_sources)
                        if recorder_revision is not None:
                            report["packages"]["core"] = (
                                "Not needed" if recorder_revision == self._recorder_active_revision()
                                else "Required"
                            )
                    except Exception as exc:
                        report["packages"]["core"] = "Unavailable"
                        report["issues"].append("Recorder package activation: " + str(exc)[:150])

                if changed_packages or (report["packages"] and
                                        report["packages"]["loader"] == "Configured"):
                    if (refresh and recorder_revision is not None
                            and report["packages"]["core"] == "Required"):
                        # Core restart below applies ALL YAML in this pass.
                        report["packages"]["reload"] = "Core restart needed"
                    elif self.reloader is not None:
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
                        panels = self._panels()
                        available = {(r["product"], r["identity"]): r
                                     for r in resources if r["kind"] == "view"}
                        report["dashboard"] = self.publisher.sync(panels, available)
                        report["issues"].extend(report["dashboard"].get("issues", []))
                    except Exception as exc:
                        report["issues"].append("DigitalHouses panels: " + str(exc)[:150])
                # "Проверить и обновить" applies Recorder configuration, not
                # just reloadable YAML. An hourly/retained MQTT sync never
                # restarts Core unexpectedly. The activation fingerprint
                # allows a one-time catch-up for already-installed packages.
                if (refresh and recorder_revision is not None
                        and report["packages"]["core"] == "Required"):
                    if self.core_checker is None or self.core_restarter is None:
                        report["packages"]["core"] = "Unavailable"
                        report["issues"].append("Recorder Core restart API unavailable")
                    else:
                        try:
                            if not self.core_checker():
                                raise SyncError("Home Assistant configuration check failed")
                            self.core_restarter()
                            # Store only a confirmed *request*, not a claim that
                            # Recorder has already produced historical statistics.
                            self.data.mkdir(parents=True, exist_ok=True)
                            _save_json(self.data / "recorder_core_activation.json", {
                                "revision": recorder_revision,
                                "requested_at": datetime.now(timezone.utc).isoformat(),
                            })
                            report["packages"]["core"] = "Requested"
                        except Exception as exc:
                            report["packages"]["core"] = "Failed"
                            report["issues"].append(
                                "Recorder Core restart: " + str(exc)[:150]
                            )

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
