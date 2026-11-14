"""Plex adoption preflight. Read Home Assistant; never edit YAML or .storage."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

PRODUCT = "digitalhouses_plex_agent"
VIEW_PATH = "dh-plex-agent"
PACKAGE_KEY = "dh_app_plex_monitoring_package"
SOURCE_SHA = "d4e99ac789b6bd53c4185bff0612edff5427d315"
COMPAT = ">=0.8.17,<0.8.18"
VIEW_SOURCE = "digitalhouses_plex_agent/dashboards/ru/10_plex.yaml"
PACKAGE_SOURCE = "digitalhouses_plex_agent/packages/common/dh_plex_app_package.yaml"
MAX_BYTES = 2_000_000
KEY_PATTERN = re.compile(r"^dh_app_plex_monitoring_package\s*:", re.M)
LOADER = re.compile(r"(?m)^\s+packages:\s*!include_dir_merge_named\s+packages/?\s*(?:#.*)?$")


class AdoptionError(ValueError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def guard_path(home: Path, path: Path) -> None:
    if home.is_symlink():
        raise AdoptionError("Home Assistant directory is a symlink")
    try:
        parts = path.relative_to(home).parts
    except ValueError as exc:
        raise AdoptionError("Path is outside Home Assistant directory") from exc
    current = home
    for part in parts:
        current /= part
        if current.is_symlink():
            raise AdoptionError(f"Symlink in path: {current}")


def read_file(home: Path, path: Path) -> bytes:
    guard_path(home, path)
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            raise AdoptionError(f"Unsafe or oversized file: {path}")
        with path.open("rb") as f:
            value = f.read(MAX_BYTES + 1)
        if len(value) > MAX_BYTES:
            raise AdoptionError(f"Oversized file: {path}")
        return value
    except OSError as exc:
        raise AdoptionError(f"Cannot read {path}: {exc}") from exc


def parsed(text: str) -> dict:
    try:
        result = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise AdoptionError(f"Invalid YAML: {exc}") from exc
    if not isinstance(result, dict):
        raise AdoptionError("Expected YAML mapping")
    return result


def fetch(source_path: str) -> str:
    url = (
        "https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/"
        + SOURCE_SHA + "/" + source_path
    )
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            content = response.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise AdoptionError("Canonical GitHub file too large")
        return content.decode("utf-8")
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise AdoptionError(f"Cannot fetch immutable canonical YAML: {exc}") from exc


def canonical() -> tuple[str, str]:
    view, package = fetch(VIEW_SOURCE), fetch(PACKAGE_SOURCE)
    for text, required in (
        (view, ("# DH-View: dh_plex_agent", "# DH-View-Version: 1.0.0")),
        (package, ("# DH-Package: " + PACKAGE_KEY, "# DH-Package-Version: 1.0.0")),
    ):
        header = text.splitlines()[:8]
        if not all(marker in header for marker in (*required, "# DH-Compatible-Agent: " + COMPAT)):
            raise AdoptionError("Canonical resource metadata is missing or incompatible")
    if parsed(view).get("path") != VIEW_PATH or parsed(view).get("type") != "sections":
        raise AdoptionError("Canonical Plex view identity changed")
    if set(parsed(package)) != {PACKAGE_KEY}:
        raise AdoptionError("Canonical Recorder package identity changed")
    return view, package


def storage_matches(home: Path) -> list[tuple[str, dict]]:
    directory = home / ".storage"
    if not directory.exists():
        return []
    guard_path(home, directory)
    if not directory.is_dir():
        raise AdoptionError("Invalid .storage directory")
    result: list[tuple[str, dict]] = []
    for item in sorted(directory.iterdir()):
        if item.name != "lovelace" and not item.name.startswith("lovelace.dashboard_"):
            continue
        try:
            raw = json.loads(read_file(home, item).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise AdoptionError(f"Unparseable Storage dashboard: {item}") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("data"), dict):
            raise AdoptionError(f"Unexpected Storage dashboard data: {item}")
        data = raw["data"]
        config = data.get("config", data)
        if not isinstance(config, dict) or not isinstance(config.get("views", []), list):
            raise AdoptionError(f"Unexpected Storage view structure: {item}")
        for view in config.get("views", []):
            if not isinstance(view, dict):
                raise AdoptionError(f"Malformed Storage view: {item}")
            if view.get("path") == VIEW_PATH:
                result.append((str(item.relative_to(home)), view))
    return result


def package_candidates(home: Path) -> list[Path]:
    base = home / "packages"
    if not base.exists():
        return []
    guard_path(home, base)
    if not base.is_dir():
        raise AdoptionError("Invalid packages directory")
    found = []
    for directory, dirs, files in os.walk(base, followlinks=False):
        parent = Path(directory)
        guard_path(home, parent)
        for name in dirs:
            guard_path(home, parent / name)
        for name in files:
            if not name.endswith(".yaml"):
                continue
            file = parent / name
            try:
                text = read_file(home, file).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise AdoptionError(f"Non-UTF-8 package: {file}") from exc
            if KEY_PATTERN.search(text):
                found.append(file)
    return sorted(found)


def assess(home: Path, view_yaml: str, package_yaml: str) -> dict:
    """Complete read-only audit. A safe-looking result never authorizes installation."""
    if not home.is_dir() or home.is_symlink():
        raise AdoptionError("Missing or linked HA configuration directory")
    view, package = parsed(view_yaml), parsed(package_yaml)
    if view.get("path") != VIEW_PATH or set(package) != {PACKAGE_KEY}:
        raise AdoptionError("Supplied canonical YAML identity invalid")
    try:
        configuration = read_file(home, home / "configuration.yaml").decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AdoptionError("configuration.yaml is not UTF-8") from exc
    loader_ok = bool(LOADER.search(configuration))

    views = storage_matches(home)
    if not views:
        view_status = "no_storage_view_found"
    elif len(views) > 1:
        view_status = "blocked_duplicate_storage_views"
    elif views[0][1] == view:
        view_status = "blocked_identical_storage_view"
    else:
        view_status = "blocked_different_storage_view"

    packages = package_candidates(home)
    package_path = None
    package_hash = None
    if not loader_ok:
        package_status = "blocked_unverified_package_loader"
    elif len(packages) > 1:
        package_status = "blocked_duplicate_package_key"
    elif not packages:
        package_status = "package_missing"
    else:
        file = packages[0]
        installed_bytes = read_file(home, file)
        try:
            installed = parsed(installed_bytes.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise AdoptionError("Installed Recorder package is not UTF-8") from exc
        package_path = str(file.relative_to(home))
        package_hash = sha(installed_bytes)
        package_status = (
            "exact_existing_package" if installed == package else "blocked_different_package"
        )

    return {
        "product": PRODUCT,
        "canonical_sha": SOURCE_SHA,
        "compatible_agent": COMPAT,
        "live_agent_version_verified": False,
        "view": {
            "status": view_status,
            "storage_files": [name for name, _ in views],
            "write_allowed": False,
        },
        "recorder": {
            "status": package_status,
            "path": package_path,
            "installed_sha256": package_hash,
            "write_allowed": False,
        },
        "automatic_apply_allowed": False,
    }


def record_recorder(home: Path, data: Path, report: dict, package_yaml: str) -> dict:
    """Only create a /data receipt after explicit consent and an identical package."""
    section = report["recorder"]
    if section["status"] != "exact_existing_package":
        raise AdoptionError("Recorder cannot be recorded: installed package is not identical")
    if data.is_symlink() or not data.is_dir():
        raise AdoptionError("Persistent data directory is missing or linked")
    destination = home / section["path"]
    if sha(read_file(home, destination)) != section["installed_sha256"]:
        raise AdoptionError("Recorder changed after preflight")
    receipt = data / "plex_recorder_adoption.json"
    if receipt.is_symlink():
        raise AdoptionError("Refusing to use a symlink receipt")
    value = {
        "product": PRODUCT,
        "status": "recorded_only_no_ha_writes",
        "source_sha": SOURCE_SHA,
        "compatible_agent": COMPAT,
        "live_agent_version_verified": False,
        "path": section["path"],
        "installed_sha256": section["installed_sha256"],
        "canonical_semantic_sha256": sha(
            json.dumps(parsed(package_yaml), sort_keys=True, ensure_ascii=False).encode()
        ),
        "ha_restart_required": False,
    }
    if receipt.exists():
        try:
            existing = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AdoptionError("Existing receipt unreadable") from exc
        if {k: v for k, v in existing.items() if k != "recorded_at"} == value:
            return existing
        raise AdoptionError("Existing receipt differs; operator review required")
    value["recorded_at"] = datetime.now(timezone.utc).isoformat()
    fd, temp = tempfile.mkstemp(prefix=".dh-sync-recorder-", dir=data)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, receipt)  # EXCL: never overwrite an existing receipt
    except FileExistsError as exc:
        raise AdoptionError("Receipt was created concurrently") from exc
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return value


def main() -> int:
    cli = argparse.ArgumentParser(description="DH Sync Plex preflight (HA read-only)")
    cli.add_argument("action", choices=("audit-plex", "record-plex-recorder"))
    cli.add_argument("--home", type=Path, default=Path("/homeassistant"))
    cli.add_argument("--data", type=Path, default=Path("/data"))
    cli.add_argument("--confirm-existing-only", action="store_true")
    args = cli.parse_args()
    try:
        view_yaml, package_yaml = canonical()
        report = assess(args.home, view_yaml, package_yaml)
        if args.action == "record-plex-recorder":
            if not args.confirm_existing_only:
                raise AdoptionError("Explicit --confirm-existing-only required")
            report["receipt"] = record_recorder(
                args.home, args.data, report, package_yaml
            )
    except AdoptionError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, **report}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
