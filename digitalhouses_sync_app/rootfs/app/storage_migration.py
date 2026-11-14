"""Two-phase, fail-closed Plex Storage -> DH YAML dashboard migration engine.

Never writes .storage directly. The transport is a Home Assistant admin
WebSocket client (read/save) with independent persistence verification.
Inactive by default: DH Sync's HA mapping remains read-only in v0.0.1.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Protocol, Any

import yaml

from adoption import AdoptionError, guard_path, read_file, parsed

PLEX_PATH = "dh-plex-agent"
PLEX_VIEW_FILENAME = "10_plex.yaml"
STATE_REL = "dh-sync/plex-migration.json"
TARGET_REL = "dashboards/dh/views/10_plex.yaml"
UI_REL = "dashboards/dh/ui.yaml"
SUPPORTED_COMPAT = "0.8.17"
INCLUDE_RE = re.compile(r"(?m)^views:\s*!include_dir_list\s+views/?\s*(?:#.*)?$")


class MigrationError(AdoptionError):
    pass


class HAStorage(Protocol):
    """A production implementation MUST use HA's admin API, never .storage writes."""

    def read_storage(self, url_path: str) -> dict: ...
    def save_storage(self, url_path: str, config: dict) -> None: ...
    def read_persisted_storage(self, url_path: str) -> dict: ...
    def read_target_yaml_dashboard(self, url_path: str) -> dict: ...
    def check_config(self) -> bool: ...


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _write_new(path: Path, content: bytes) -> None:
    """Exclusive creation; never overwrite a user's file."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())


def _atomic_json(path: Path, value: dict) -> None:
    fd, name = tempfile.mkstemp(prefix=".dh-sync-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(value, output, indent=2, sort_keys=True, ensure_ascii=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _without_plex(config: dict, expected_view: dict) -> tuple[dict, int]:
    if not isinstance(config, dict) or not isinstance(config.get("views"), list):
        raise MigrationError("Storage dashboard does not contain a views list")
    indices = [
        index for index, view in enumerate(config["views"])
        if isinstance(view, dict) and view.get("path") == PLEX_PATH
    ]
    if len(indices) != 1:
        raise MigrationError("Storage dashboard must contain exactly one Plex view")
    index = indices[0]
    if config["views"][index] != expected_view:
        raise MigrationError("Live Plex view differs from the canonical source")
    updated = copy.deepcopy(config)
    del updated["views"][index]
    return updated, index


class PlexMigration:
    """The operator drives stage, cutover and rollback in separate explicit steps."""

    def __init__(
        self,
        home: Path,
        data: Path,
        api: HAStorage,
        *,
        source_url_path: str,
        target_url_path: str = "digital-houses",
    ):
        self.home = home
        self.data = data
        self.api = api
        if not source_url_path or not re.fullmatch(r"[a-z0-9-]+", source_url_path):
            raise MigrationError("Storage dashboard URL path must be supplied explicitly")
        if source_url_path == target_url_path:
            raise MigrationError("Source and target dashboard must be different")
        if target_url_path != "digital-houses":
            raise MigrationError("Only the DigitalHouses YAML destination is supported")
        if not home.is_dir() or home.is_symlink():
            raise MigrationError("Invalid Home Assistant directory")
        if not data.is_dir() or data.is_symlink():
            raise MigrationError("Invalid persistent /data directory")
        self.source = source_url_path
        self.target = target_url_path
        self.view_file = home / TARGET_REL
        self.ui_file = home / UI_REL
        self.state_file = data / STATE_REL

    def _view(self, canonical_view_yaml: str) -> dict:
        try:
            view = parsed(canonical_view_yaml)
        except AdoptionError as exc:
            raise MigrationError(str(exc)) from exc
        if view.get("path") != PLEX_PATH or view.get("type") != "sections":
            raise MigrationError("Expected canonical Plex sections view")
        header = canonical_view_yaml.splitlines()[:8]
        if "# DH-Compatible-Agent: >=0.8.17,<0.8.18" not in header:
            raise MigrationError("Missing exact approved Plex agent compatibility")
        if "# DH-View: dh_plex_agent" not in header:
            raise MigrationError("Missing canonical Plex view identity")
        return view

    def _existing(self) -> dict | None:
        guard_path(self.data, self.state_file)
        if not self.state_file.is_file():
            return None
        try:
            return json.loads(read_file(self.data, self.state_file))
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            raise MigrationError("Existing migration journal is invalid") from exc

    def _preflight(self, view: dict, runtime_version: str) -> tuple[dict, dict]:
        if runtime_version != SUPPORTED_COMPAT:
            raise MigrationError("Live Plex Agent must be verified at 0.8.17")
        if self._existing() is not None:
            raise MigrationError("A migration journal already exists; use rollback/recovery")
        if not self.ui_file.is_file():
            raise MigrationError("DigitalHouses YAML dashboard must be registered first")
        ui = read_file(self.home, self.ui_file).decode("utf-8")
        if not INCLUDE_RE.search(ui):
            raise MigrationError("Target ui.yaml must use views: !include_dir_list views")
        if self.view_file.exists() or self.view_file.is_symlink():
            raise MigrationError("Managed Plex view already exists, refusing overwrite")
        if self.view_file.parent.is_symlink():
            raise MigrationError("Target views directory is linked")
        if not self.view_file.parent.is_dir():
            raise MigrationError("Existing managed views directory is required")
        # Refuse a duplicate view path elsewhere in managed views.
        for path in self.view_file.parent.glob("*.yaml"):
            candidate = read_file(self.home, path).decode("utf-8")
            if parsed(candidate).get("path") == PLEX_PATH:
                raise MigrationError(f"Duplicate managed Plex view in {path.name}")
        current = self.api.read_storage(self.source)
        new, index = _without_plex(current, view)
        disk = self.api.read_persisted_storage(self.source)
        if _digest(disk) != _digest(current):
            raise MigrationError("Live Storage does not match persisted Storage")
        # The YAML dashboard must be registered already; an empty views list is okay.
        target = self.api.read_target_yaml_dashboard(self.target)
        if not isinstance(target, dict) or not isinstance(target.get("views"), list):
            raise MigrationError("Destination YAML dashboard not available")
        if any(isinstance(v, dict) and v.get("path") == PLEX_PATH for v in target["views"]):
            raise MigrationError("Plex view already exists in destination dashboard")
        if not self.api.check_config():
            raise MigrationError("HA configuration validation failed before stage")
        return current, {"updated_storage": new, "index": index}

    def stage(self, canonical_view_yaml: str, *, runtime_version: str, confirm: bool) -> dict:
        """Write only the new managed YAML after durable backup. Do NOT touch Storage."""
        if not confirm:
            raise MigrationError("Explicit first-stage confirmation required")
        view = self._view(canonical_view_yaml)
        original, details = self._preflight(view, runtime_version)
        guard_path(self.home, self.view_file)
        state_dir = self.state_file.parent
        if state_dir.is_symlink():
            raise MigrationError("Unsafe migration journal directory")
        state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.state_file.exists():
            raise MigrationError("Concurrent migration journal creation")
        content = canonical_view_yaml.encode("utf-8")
        state = {
            "schema": 1,
            "phase": "prepared",
            "source_url_path": self.source,
            "target_url_path": self.target,
            "agent_version": runtime_version,
            "view_sha256": hashlib.sha256(content).hexdigest(),
            "storage_before": original,
            "storage_before_sha256": _digest(original),
            "storage_after_sha256": _digest(details["updated_storage"]),
            "view_index": details["index"],
        }
        # Durable recovery checkpoint precedes the first HA write.
        _write_new(self.state_file, (json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n").encode())
        try:
            _write_new(self.view_file, content)
            if not self.api.check_config():
                raise MigrationError("HA configuration check failed after staging YAML")
            state["phase"] = "staged"
            _atomic_json(self.state_file, state)
        except Exception:
            # Leave the recovery journal if an unexpected interruption occurs.
            # Normal errors attempt safe cleanup only when our file hash matches.
            if self.view_file.exists() and hashlib.sha256(read_file(self.home, self.view_file)).hexdigest() == state["view_sha256"]:
                self.view_file.unlink()
            _atomic_json(self.state_file, {**state, "phase": "stage_failed"})
            raise
        return {"phase": "staged", "storage_changed": False, "managed_file": TARGET_REL}

    def cutover(self, canonical_view_yaml: str, *, confirm_rendered: bool) -> dict:
        """Operator confirms target render; then HA WebSocket removes only Plex view."""
        if not confirm_rendered:
            raise MigrationError("Operator confirmation that YAML dashboard renders is required")
        state = self._existing()
        if not state or state.get("phase") != "staged":
            raise MigrationError("No staged migration available")
        view = self._view(canonical_view_yaml)
        expected_sha = hashlib.sha256(canonical_view_yaml.encode("utf-8")).hexdigest()
        if state["view_sha256"] != expected_sha:
            raise MigrationError("Canonical view revision changed since staging")
        if hashlib.sha256(read_file(self.home, self.view_file)).hexdigest() != expected_sha:
            raise MigrationError("Staged view was edited after staging")
        current = self.api.read_storage(self.source)
        if _digest(current) != state["storage_before_sha256"]:
            raise MigrationError("Storage changed since staging; refuse to remove any view")
        if _digest(self.api.read_persisted_storage(self.source)) != _digest(current):
            raise MigrationError("Storage disk differs from live API state")
        rendered = self.api.read_target_yaml_dashboard(self.target)
        matches = [v for v in rendered.get("views", []) if isinstance(v, dict) and v.get("path") == PLEX_PATH]
        if len(matches) != 1 or matches[0] != view:
            raise MigrationError("Destination YAML dashboard has not rendered canonical Plex view")
        if not self.api.check_config():
            raise MigrationError("HA configuration validation failed before cutover")
        after, _ = _without_plex(current, view)
        if _digest(after) != state["storage_after_sha256"]:
            raise MigrationError("Calculated source dashboard differs from prepared snapshot")
        state["phase"] = "cutover_pending"
        _atomic_json(self.state_file, state)
        try:
            self.api.save_storage(self.source, after)
            self._verify_storage(after)
        except Exception as exc:
            # Restore only when the only observed changes are ours; if ambiguous,
            # keep journal for the operator rather than overwrite unrelated edits.
            observed = self.api.read_storage(self.source)
            if _digest(observed) == _digest(after):
                self.api.save_storage(self.source, state["storage_before"])
                self._verify_storage(state["storage_before"])
            state["phase"] = "cutover_failed"
            _atomic_json(self.state_file, state)
            raise MigrationError(f"Cutover failed; verify journal and Storage: {exc}") from exc
        state["phase"] = "cutover"
        _atomic_json(self.state_file, state)
        return {"phase": "cutover", "storage_verified": True, "rollback_available": True}

    def _verify_storage(self, expected: dict) -> None:
        """A websocket save acknowledgment alone is NOT persistence evidence."""
        if _digest(self.api.read_storage(self.source)) != _digest(expected):
            raise MigrationError("Storage WebSocket readback differs")
        # HA can schedule the underlying Store write; never claim success until
        # the on-disk Storage content independently matches.
        for index in range(20):
            if _digest(self.api.read_persisted_storage(self.source)) == _digest(expected):
                return
            if index < 19:
                time.sleep(0.25)
        raise MigrationError("Storage API acknowledged, but on-disk persistence unverified")

    def rollback(self, *, confirm: bool) -> dict:
        if not confirm:
            raise MigrationError("Explicit rollback confirmation required")
        state = self._existing()
        if not state or state.get("phase") not in (
            "prepared", "staged", "stage_failed", "cutover", "cutover_failed", "cutover_pending"
        ):
            raise MigrationError("No recoverable Plex migration journal")
        observed = self.api.read_storage(self.source)
        observed_hash = _digest(observed)
        before_hash = state["storage_before_sha256"]
        after_hash = state["storage_after_sha256"]
        if observed_hash not in (before_hash, after_hash):
            raise MigrationError("Parent Storage dashboard changed after migration; manual recovery required")
        if observed_hash == after_hash:
            self.api.save_storage(self.source, state["storage_before"])
            self._verify_storage(state["storage_before"])
        if self.view_file.exists():
            current_hash = hashlib.sha256(read_file(self.home, self.view_file)).hexdigest()
            if current_hash != state["view_sha256"]:
                raise MigrationError("Managed view changed; cannot safely remove it")
            self.view_file.unlink()
        state["phase"] = "rolled_back"
        _atomic_json(self.state_file, state)
        return {"phase": "rolled_back", "storage_restored": True, "managed_view_removed": True}
