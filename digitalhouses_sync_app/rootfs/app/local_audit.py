"""Non-mutating local HAOS dashboard audit for the DH Sync v0.2.0 pilot.

The container receives the Home Assistant config at /homeassistant as a
READ-ONLY Supervisor bind mount. Only approved DigitalHouses view YAML and
Lovelace Storage metadata are inspected. No HA API, no writes, no reloads.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import stat
from pathlib import Path

import yaml

from resource_preview import PreviewCatalog, parse_view, read_view

VIEW_DIR = Path("dashboards/dh/views")
PARENT_UI = Path("dashboards/dh/ui.yaml")
STORAGE_DIR = Path(".storage")
MAX_VIEW_BYTES = 1_000_000
MAX_STORAGE_BYTES = 8_000_000
MAX_UI_BYTES = 200_000
MAX_VIEW_FILES = 128
MAX_STORAGE_FILES = 128
MAX_DIFF_LINES = 45
MAX_DIFF_CHARS = 4500
VIEW_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.ya?ml\Z")


class AuditError(ValueError):
    pass


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _safe_path(root: Path, path: Path) -> None:
    """Prevent following symlinks or leaving the mapped config tree."""
    if not root.is_dir() or root.is_symlink():
        raise AuditError("Home Assistant config mount unavailable or unsafe")
    try:
        parts = path.relative_to(root).parts
    except ValueError as exc:
        raise AuditError("Path outside read-only HA configuration") from exc
    current = root
    for part in parts:
        current /= part
        if current.is_symlink():
            raise AuditError("Symlink in inspected Home Assistant path")


def _safe_read(root: Path, file: Path, *, limit: int) -> bytes:
    _safe_path(root, file)
    try:
        info = file.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise AuditError("Unsafe or oversized local file")
        with file.open("rb") as stream:
            content = stream.read(limit + 1)
    except OSError as exc:
        raise AuditError("Cannot read local Home Assistant file") from exc
    if len(content) > limit:
        raise AuditError("Local file exceeds audit size limit")
    return content


def _safe_yaml(raw: bytes) -> dict:
    try:
        document = yaml.safe_load(raw.decode("utf-8", "strict"))
    except (UnicodeError, yaml.YAMLError, RecursionError) as exc:
        raise AuditError("Invalid local YAML view") from exc
    if not isinstance(document, dict):
        raise AuditError("Local YAML view is not a mapping")
    return document


def _safe_json(raw: bytes) -> dict:
    try:
        document = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise AuditError("Invalid local Lovelace Storage JSON") from exc
    if not isinstance(document, dict):
        raise AuditError("Unexpected Lovelace Storage structure")
    return document


def _diff(old: bytes, new: bytes) -> dict:
    """Only view YAML diff is displayed. Never include Storage JSON/config."""
    try:
        previous = old.decode("utf-8", "strict").splitlines(keepends=True)
        current = new.decode("utf-8", "strict").splitlines(keepends=True)
    except UnicodeError as exc:
        raise AuditError("Local view is not UTF-8") from exc
    lines = list(difflib.unified_diff(
        previous, current, fromfile="CORE local view", tofile="GitHub canonical",
        n=2,
    ))
    additions = sum(s.startswith("+") and not s.startswith("+++") for s in lines)
    removals = sum(s.startswith("-") and not s.startswith("---") for s in lines)
    preview = "".join(lines[:MAX_DIFF_LINES])[:MAX_DIFF_CHARS]
    if len(lines) > MAX_DIFF_LINES or len("".join(lines[:MAX_DIFF_LINES])) > MAX_DIFF_CHARS:
        preview += "\n... diff truncated; no file modification performed\n"
    return {"added": additions, "removed": removals, "preview": preview}


def _storage_view_paths(root: Path) -> tuple[set[str], list[str]]:
    """Read only Lovelace config view paths. Never return Storage content."""
    folder = root / STORAGE_DIR
    if not folder.exists():
        return set(), []
    _safe_path(root, folder)
    if not folder.is_dir():
        raise AuditError("Lovelace Storage directory is invalid")
    # Newer HA versions store Storage dashboards as lovelace.<url_path>.
    # Keep support for the legacy lovelace and lovelace.dashboard_* layout.
    files = sorted(p for p in folder.iterdir()
                   if p.name == "lovelace" or p.name.startswith("lovelace."))
    if len(files) > MAX_STORAGE_FILES:
        raise AuditError("Too many Lovelace Storage files for bounded audit")
    paths: set[str] = set()
    sources = []
    for file in files:
        data = _safe_json(_safe_read(root, file, limit=MAX_STORAGE_BYTES))
        section = data.get("data")
        if not isinstance(section, dict):
            raise AuditError("Unexpected Lovelace Storage data structure")
        config = section.get("config", section)
        if not isinstance(config, dict):
            raise AuditError("Unexpected Lovelace Storage view structure")
        views = config.get("views", [])
        if not isinstance(views, list):
            raise AuditError("Invalid Lovelace Storage view list")
        for view in views:
            if not isinstance(view, dict):
                raise AuditError("Unexpected Lovelace Storage view")
            path = view.get("path")
            if isinstance(path, str) and path:
                paths.add(path)
                if file.name not in sources:
                    sources.append(file.name)
    return paths, sources


def _local_snapshot(root: Path) -> dict:
    ui = root / PARENT_UI
    issues = []
    if ui.is_symlink():
        raise AuditError("Symlink in DigitalHouses parent dashboard")
    if ui.is_file():
        ui_raw = _safe_read(root, ui, limit=MAX_UI_BYTES).decode("utf-8", "strict")
        if not re.search(r"(?m)^title:\s*DigitalHouses\s*$", ui_raw):
            issues.append("DigitalHouses ui.yaml: title is not the expected value")
        if not re.search(r"(?m)^views:\s*!include_dir_list\s+views/?\s*(?:#.*)?$", ui_raw):
            issues.append("DigitalHouses ui.yaml: expected views: !include_dir_list views/")
    else:
        issues.append("DigitalHouses ui.yaml is absent")
    folder = root / VIEW_DIR
    if folder.is_symlink():
        raise AuditError("Symlink in DigitalHouses views folder")
    by_path = {}
    by_name = {}
    if folder.is_dir():
        _safe_path(root, folder)
        files = sorted(p for p in folder.iterdir() if p.suffix in (".yaml", ".yml"))
        if len(files) > MAX_VIEW_FILES:
            raise AuditError("Too many local DigitalHouses views")
        for file in files:
            if not VIEW_NAME.fullmatch(file.name):
                raise AuditError("Unexpected local view filename")
            raw = _safe_read(root, file, limit=MAX_VIEW_BYTES)
            parsed = _safe_yaml(raw)
            if not isinstance(parsed.get("path"), str) or not parsed["path"]:
                issues.append("View has no path: " + file.name)
                continue
            view = {"name": file.name, "raw": raw, "parsed": parsed, "sha256": _hash(raw)}
            by_name[file.name] = view
            by_path.setdefault(parsed["path"], []).append(view)
        for path, copies in by_path.items():
            if len(copies) > 1:
                issues.append("Duplicate local YAML view path: " + path)
    else:
        issues.append("DigitalHouses YAML views directory is absent")
    storage_paths, storage_sources = _storage_view_paths(root)
    return {
        "by_name": by_name, "by_path": by_path,
        "storage_paths": storage_paths, "storage_count": len(storage_sources),
        "issues": issues,
    }


class LocalAuditor:
    def __init__(self, root: Path = Path("/homeassistant"), *,
                 catalog=None, fetcher=read_view, require_readonly: bool = True):
        self.root = root
        self.catalog = catalog if catalog is not None else PreviewCatalog()
        self.fetcher = fetcher
        self.require_readonly = require_readonly

    def inspect(self, claims: dict[str, dict]) -> dict:
        """Return a *read-only* status report; no data or backup files created."""
        report = {
            "ready": False, "readonly": True, "issues": [],
            "products": [], "write_enabled": False,
        }
        if not self.root.is_dir() or self.root.is_symlink():
            report["issues"].append("HAOS config not mounted at /homeassistant")
            return report
        if self.require_readonly:
            try:
                if not (os.statvfs(self.root).f_flag & getattr(os, "ST_RDONLY", 1)):
                    report["issues"].append("Home Assistant config mount is not read-only")
                    return report
            except OSError:
                report["issues"].append("Cannot verify read-only mount state")
                return report
        try:
            snapshot = _local_snapshot(self.root)
        except (AuditError, UnicodeError, OSError, ValueError) as exc:
            report["issues"].append(str(exc))
            return report
        report["ready"] = True
        report["issues"] = list(snapshot["issues"])
        report["storage_files_examined"] = snapshot["storage_count"]
        for product in self.catalog.inspect(claims):
            item = {
                "product": product["product"], "version": product["version"],
                "commit": product["commit"], "source_error": product["error"],
                "views": [],
            }
            report["products"].append(item)
            for view in product["views"]:
                row = {
                    "title": view["title"], "source_file": view["file"],
                    "view_path": view["path"], "source_status": view["status"],
                    "local_file": "", "status": "", "kind": "",
                    "source_sha256": "", "local_sha256": "", "diff": None,
                    "blocked": True,
                }
                item["views"].append(row)
                if view["blocked"]:
                    row["kind"], row["status"] = "blocked", "Неподтверждённая версия ресурса"
                    continue
                try:
                    source_path = ("" if product["product_path"] == "." else product["product_path"] + "/") + "dashboards/ru/" + view["file"]
                    if not VIEW_NAME.fullmatch(view["file"]):
                        raise AuditError("Unexpected GitHub view filename")
                    raw = self.fetcher(product["repository"], source_path, product["commit"])
                    if len(raw) > MAX_VIEW_BYTES:
                        raise AuditError("Oversized canonical source")
                    checked = parse_view(raw, source_path, product["product"])
                    if checked["path"] != view["path"] or checked["revision"] != view["revision"]:
                        raise AuditError("GitHub source metadata changed between checks")
                    row["source_sha256"] = _hash(raw)
                    matches = snapshot["by_path"].get(view["path"], [])
                    collision = snapshot["by_name"].get(view["file"])
                    if view["path"] in snapshot["storage_paths"]:
                        row["kind"], row["status"] = "storage", "Путь обнаружен в Lovelace Storage — требуется ручная проверка"
                    elif len(matches) > 1 or (collision and collision not in matches):
                        row["kind"], row["status"] = "collision", "Конфликт локального YAML пути или имени"
                    elif not matches:
                        row["kind"], row["status"] = "missing", "Локальный YAML отсутствует"
                    else:
                        local = matches[0]
                        row["local_file"] = local["name"]
                        row["local_sha256"] = local["sha256"]
                        row["diff"] = _diff(local["raw"], raw)
                        if local["raw"] == raw:
                            row["kind"], row["status"] = "identical", "Полное совпадение"
                        elif local["parsed"] == _safe_yaml(raw):
                            row["kind"], row["status"] = "equivalent", "YAML одинаковый; отличаются комментарии/формат"
                        else:
                            row["kind"], row["status"] = "different", "Локальный YAML отличается от GitHub"
                except (AuditError, ValueError, UnicodeError, OSError) as exc:
                    row["kind"], row["status"] = "error", str(exc)[:160]
        return report
