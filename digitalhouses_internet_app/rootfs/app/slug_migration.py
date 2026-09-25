"""Controlled Home Assistant App slug migration support.

Bridge release:
    digitalhouses_internet -> digitalhouses_internet_app

The bridge exports only explicit App-owned persistent files to a single atomic
bundle under /share.  The canonical-slug release imports that bundle before the
runtime starts, so the new App keeps the old options and persistent identity.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tarfile
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PRODUCT_ID = "digitalhouses_internet_app"
SOURCE_SLUG = "digitalhouses_internet"
TARGET_SLUG = "digitalhouses_internet_app"
BUNDLE_SCHEMA_VERSION = 1

DATA_DIR = Path("/data")
BUNDLE_DIR = Path("/share/digitalhouses_internet_app/slug-migration-v1")
BUNDLE_FILE = BUNDLE_DIR / "bundle.tar.gz"
IMPORT_MARKER = DATA_DIR / ".slug_migration_v1_imported.json"
OPTIONS_PENDING_MARKER = DATA_DIR / ".slug_migration_v1_options_pending.json"

IMPORT_NONE = "none"
IMPORT_RESTART_REQUIRED = "restart_required"
IMPORT_COMPLETE = "imported"
RESTART_REQUIRED_EXIT = 10

STATE_FILES = (
    "options.json",
    "telemetry.json",
    "runtime/outages.json",
    "runtime/speedtest.json",
    "runtime/thresholds.json",
    "runtime/traffic.json",
    "runtime/recent_results.json",
    "runtime/servers.json",
    "runtime/recovery.json",
    "runtime/discovery.json",
)

SUPERVISOR_URL = "http://supervisor"
SUPERVISOR_TIMEOUT_SECONDS = 5.0


class SlugMigrationError(RuntimeError):
    """Raised when the controlled slug migration cannot be completed safely."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _supervisor_token() -> str:
    token = os.getenv("SUPERVISOR_TOKEN", "").strip()
    if not token:
        raise SlugMigrationError("SUPERVISOR_TOKEN is unavailable")
    return token


def _supervisor_json(
    *,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = None
    headers = {
        "Authorization": f"Bearer {_supervisor_token()}",
        "Accept": "application/json",
    }
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        f"{SUPERVISOR_URL}{path}",
        data=body,
        method=method,
        headers=headers,
    )
    with urllib.request.urlopen(
        request,
        timeout=SUPERVISOR_TIMEOUT_SECONDS,
    ) as response:
        raw = response.read()
        if not raw:
            return {}
        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise SlugMigrationError("Supervisor returned a non-object response")
        if parsed.get("result") == "error":
            raise SlugMigrationError(
                f"Supervisor request failed: {parsed.get('message') or 'unknown error'}"
            )
        data = parsed.get("data")
        return data if isinstance(data, dict) else parsed


def read_self_supervisor_settings() -> dict[str, Any]:
    """Read optional App-level Supervisor settings worth preserving."""
    info = _supervisor_json(method="GET", path="/addons/self/info")
    result: dict[str, Any] = {}

    boot = info.get("boot")
    if boot in {"auto", "manual"}:
        result["boot"] = boot

    for key in ("auto_update", "watchdog"):
        value = info.get(key)
        if isinstance(value, bool):
            result[key] = value

    return result


def apply_self_supervisor_settings(settings: dict[str, Any]) -> None:
    """Apply imported options/settings to the canonical-slug App."""
    options = settings.get("options")
    if not isinstance(options, dict):
        raise SlugMigrationError("migration bundle options are invalid")

    payload: dict[str, Any] = {"options": options}
    boot = settings.get("boot")
    if boot in {"auto", "manual"}:
        payload["boot"] = boot
    for key in ("auto_update", "watchdog"):
        value = settings.get(key)
        if isinstance(value, bool):
            payload[key] = value

    _supervisor_json(
        method="POST",
        path="/addons/self/options",
        payload=payload,
    )


def _read_state_files(data_dir: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for relative in STATE_FILES:
        path = data_dir / relative
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file():
            raise SlugMigrationError(
                f"migration state path is not a regular file: {relative}"
            )
        files[relative] = path.read_bytes()

    if "options.json" not in files:
        raise SlugMigrationError("required /data/options.json is missing")
    try:
        options = json.loads(files["options.json"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SlugMigrationError("options.json is not valid JSON") from exc
    if not isinstance(options, dict):
        raise SlugMigrationError("options.json must contain an object")
    return files


def export_bridge_bundle(
    *,
    app_version: str,
    data_dir: Path = DATA_DIR,
    bundle_file: Path = BUNDLE_FILE,
    settings_reader: Callable[[], dict[str, Any]] = read_self_supervisor_settings,
) -> dict[str, Any]:
    """Write an atomic migration bundle for the legacy-slug installation."""
    files = _read_state_files(data_dir)

    try:
        supervisor_settings = settings_reader()
    except Exception:
        # Options and all product state still remain fully exportable from /data.
        # Optional Supervisor UI settings are best-effort only.
        supervisor_settings = {}
    if not isinstance(supervisor_settings, dict):
        supervisor_settings = {}

    file_manifest = {
        relative: {
            "size": len(payload),
            "sha256": _sha256_bytes(payload),
        }
        for relative, payload in sorted(files.items())
    }
    manifest = {
        "schema": BUNDLE_SCHEMA_VERSION,
        "product": PRODUCT_ID,
        "source_slug": SOURCE_SLUG,
        "target_slug": TARGET_SLUG,
        "source_version": app_version,
        "exported_at": _utc_now(),
        "files": file_manifest,
        "supervisor_settings": supervisor_settings,
    }
    manifest_bytes = (
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")

    bundle_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        bundle_file.parent.chmod(0o700)
    except OSError:
        pass

    fd, tmp_name = tempfile.mkstemp(
        prefix=".bundle.",
        suffix=".tar.gz",
        dir=str(bundle_file.parent),
    )
    os.close(fd)
    tmp_path = Path(tmp_name)

    try:
        with tarfile.open(tmp_path, mode="w:gz") as archive:
            info = tarfile.TarInfo("manifest.json")
            info.size = len(manifest_bytes)
            info.mode = 0o600
            info.mtime = int(time.time())
            archive.addfile(info, io.BytesIO(manifest_bytes))

            for relative, payload in sorted(files.items()):
                info = tarfile.TarInfo(f"data/{relative}")
                info.size = len(payload)
                info.mode = 0o600
                info.mtime = int(time.time())
                archive.addfile(info, io.BytesIO(payload))

        with tmp_path.open("rb") as handle:
            os.fsync(handle.fileno())
        tmp_path.chmod(0o600)
        os.replace(tmp_path, bundle_file)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass

    return {
        "bundle": str(bundle_file),
        "sha256": _sha256_file(bundle_file),
        "files": len(files),
        "exported_at": manifest["exported_at"],
    }


def _load_bundle(bundle_file: Path) -> tuple[dict[str, Any], dict[str, bytes], str]:
    if not bundle_file.is_file():
        raise FileNotFoundError(bundle_file)

    try:
        with tarfile.open(bundle_file, mode="r:gz") as archive:
            members = archive.getmembers()
            by_name = {member.name: member for member in members}
            manifest_member = by_name.get("manifest.json")
            if manifest_member is None or not manifest_member.isfile():
                raise SlugMigrationError("migration bundle has no manifest.json")

            extracted = archive.extractfile(manifest_member)
            if extracted is None:
                raise SlugMigrationError("cannot read migration manifest")
            manifest = json.loads(extracted.read().decode("utf-8"))
            if not isinstance(manifest, dict):
                raise SlugMigrationError("migration manifest must be an object")

            if manifest.get("schema") != BUNDLE_SCHEMA_VERSION:
                raise SlugMigrationError("unsupported migration bundle schema")
            if manifest.get("product") != PRODUCT_ID:
                raise SlugMigrationError("migration bundle product mismatch")
            if manifest.get("source_slug") != SOURCE_SLUG:
                raise SlugMigrationError("migration bundle source slug mismatch")
            if manifest.get("target_slug") != TARGET_SLUG:
                raise SlugMigrationError("migration bundle target slug mismatch")

            declared = manifest.get("files")
            if not isinstance(declared, dict):
                raise SlugMigrationError("migration manifest files are invalid")

            unknown = sorted(set(declared) - set(STATE_FILES))
            if unknown:
                raise SlugMigrationError(
                    "migration bundle contains unsupported state files: "
                    + ", ".join(unknown)
                )
            if "options.json" not in declared:
                raise SlugMigrationError("migration bundle has no options.json")

            expected_members = {"manifest.json"} | {
                f"data/{relative}" for relative in declared
            }
            actual_members = {member.name for member in members}
            if actual_members != expected_members:
                raise SlugMigrationError("migration bundle member set mismatch")

            files: dict[str, bytes] = {}
            for relative, metadata in declared.items():
                member = by_name[f"data/{relative}"]
                if not member.isfile() or member.issym() or member.islnk():
                    raise SlugMigrationError(
                        f"unsafe migration bundle member: {relative}"
                    )
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise SlugMigrationError(
                        f"cannot read migration state file: {relative}"
                    )
                payload = extracted.read()
                if not isinstance(metadata, dict):
                    raise SlugMigrationError(
                        f"invalid migration metadata: {relative}"
                    )
                if metadata.get("size") != len(payload):
                    raise SlugMigrationError(
                        f"migration state size mismatch: {relative}"
                    )
                if metadata.get("sha256") != _sha256_bytes(payload):
                    raise SlugMigrationError(
                        f"migration state hash mismatch: {relative}"
                    )
                files[relative] = payload
    except (tarfile.TarError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SlugMigrationError("migration bundle is unreadable") from exc

    try:
        options = json.loads(files["options.json"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SlugMigrationError("imported options.json is invalid") from exc
    if not isinstance(options, dict):
        raise SlugMigrationError("imported options.json must contain an object")

    return manifest, files, _sha256_file(bundle_file)


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.migration.",
        dir=str(path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.chmod(0o600)
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _read_current_options(data_dir: Path) -> dict[str, Any] | None:
    path = data_dir / "options.json"
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError, OSError):
        return None
    return current if isinstance(current, dict) else None


def _read_marker(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
        raise SlugMigrationError(f"{label} marker is invalid") from exc
    if not isinstance(payload, dict):
        raise SlugMigrationError(f"{label} marker must be an object")
    return payload


def _write_json_marker(path: Path, payload: dict[str, Any]) -> None:
    _write_atomic(
        path,
        (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n"
        ).encode("utf-8"),
    )


def import_canonical_bundle(
    *,
    data_dir: Path = DATA_DIR,
    bundle_file: Path = BUNDLE_FILE,
    marker_file: Path | None = None,
    pending_file: Path | None = None,
    settings_applier: Callable[[dict[str, Any]], None] = apply_self_supervisor_settings,
) -> str:
    """Import a bridge bundle exactly once before the canonical runtime starts.

    Supervisor accepts App options immediately through its API, but the running
    container receives the updated /data/options.json only on the next start.
    Therefore options migration is intentionally two-stage when the current
    container still has package defaults.
    """
    marker_file = marker_file or (data_dir / IMPORT_MARKER.name)
    pending_file = pending_file or (data_dir / OPTIONS_PENDING_MARKER.name)

    # A completed migration is authoritative. The legacy rollback App may
    # regenerate the shared bridge bundle with a new exported_at/hash on every
    # start/stop. That must never cause the canonical App to re-import or fail.
    if marker_file.is_file():
        marker = _read_marker(marker_file, label="existing migration")
        if marker.get("schema") != BUNDLE_SCHEMA_VERSION:
            raise SlugMigrationError("completed migration marker schema mismatch")
        if marker.get("product") != PRODUCT_ID:
            raise SlugMigrationError("completed migration marker product mismatch")
        if marker.get("source_slug") != SOURCE_SLUG:
            raise SlugMigrationError("completed migration marker source slug mismatch")
        if marker.get("target_slug") != TARGET_SLUG:
            raise SlugMigrationError("completed migration marker target slug mismatch")
        return IMPORT_NONE

    if not bundle_file.is_file():
        return IMPORT_NONE

    manifest, files, bundle_sha256 = _load_bundle(bundle_file)

    options = json.loads(files["options.json"].decode("utf-8"))
    current_options = _read_current_options(data_dir)

    if pending_file.is_file():
        pending = _read_marker(pending_file, label="options migration")
        if pending.get("bundle_sha256") != bundle_sha256:
            raise SlugMigrationError(
                "pending options migration belongs to a different bundle"
            )
        if current_options != options:
            raise SlugMigrationError(
                "Supervisor migration options are not active after restart"
            )
    elif current_options != options:
        settings = dict(manifest.get("supervisor_settings") or {})
        settings["options"] = options

        # Supervisor persists these settings immediately, but the current
        # container keeps the old /data/options.json until it is started again.
        settings_applier(settings)
        _write_json_marker(
            pending_file,
            {
                "schema": BUNDLE_SCHEMA_VERSION,
                "product": PRODUCT_ID,
                "source_slug": SOURCE_SLUG,
                "target_slug": TARGET_SLUG,
                "source_version": manifest.get("source_version"),
                "requested_at": _utc_now(),
                "bundle_sha256": bundle_sha256,
                "options_sha256": _sha256_bytes(files["options.json"]),
            },
        )
        return IMPORT_RESTART_REQUIRED

    # Options visible to the runtime now match the bridge source. Restore every
    # App-owned state file except options.json, which remains Supervisor-owned.
    for relative, payload in files.items():
        if relative == "options.json":
            continue
        _write_atomic(data_dir / relative, payload)

    _write_json_marker(
        marker_file,
        {
            "schema": BUNDLE_SCHEMA_VERSION,
            "product": PRODUCT_ID,
            "source_slug": SOURCE_SLUG,
            "target_slug": TARGET_SLUG,
            "source_version": manifest.get("source_version"),
            "exported_at": manifest.get("exported_at"),
            "imported_at": _utc_now(),
            "bundle_sha256": bundle_sha256,
        },
    )
    try:
        pending_file.unlink()
    except FileNotFoundError:
        pass
    return IMPORT_COMPLETE

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1 or argv[0] not in {"export", "import"}:
        print("usage: slug_migration.py <export|import>", file=sys.stderr)
        return 2

    try:
        if argv[0] == "export":
            result = export_bridge_bundle(
                app_version=os.getenv("APP_VERSION", "unknown")
            )
            print(
                "Slug migration bridge bundle ready: "
                f"{result['bundle']} files={result['files']} "
                f"sha256={result['sha256']}"
            )
            return 0

        status = import_canonical_bundle()
        if status == IMPORT_COMPLETE:
            print(
                "Slug migration bundle imported successfully: "
                f"{SOURCE_SLUG} -> {TARGET_SLUG}"
            )
            return 0
        if status == IMPORT_RESTART_REQUIRED:
            print(
                "Slug migration options applied successfully; "
                "restart canonical App once to complete state import"
            )
            return RESTART_REQUIRED_EXIT
        print("No pending slug migration bundle to import")
        return 0
    except Exception as exc:
        print(f"Slug migration failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
