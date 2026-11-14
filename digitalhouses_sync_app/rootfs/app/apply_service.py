"""DH Sync 0.3: explicit owner-only YAML Apply with reversible file transactions.

Only /homeassistant/dashboards/dh/views/*.yaml is writable. No .storage/API,
dashboard registration, package installation, agent updates or automatic reload.
Source acceptance: GitHub owner DigitalHouses, with no product/version gates.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import tempfile
import threading
import time
from pathlib import Path

from discovery_contract import canonical_repository
from local_audit import VIEW_DIR, MAX_VIEW_BYTES, _diff, _local_snapshot, _safe_path, _safe_yaml
from resource_preview import PreviewCatalog, parse_view, read_view


class ApplyError(ValueError):
    pass


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _file_sync(path: Path, data: bytes, mode: int = 0o600) -> None:
    """Write a new private journal/backup file, without following symlinks."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _atomic_replace(path: Path, data: bytes, mode: int = 0o644,
                    uid: int | None = None, gid: int | None = None) -> None:
    """Atomic replacement inside the pre-validated DigitalHouses views directory."""
    fd, temporary = tempfile.mkstemp(prefix=".dh-sync-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            os.fchmod(out.fileno(), mode & 0o777)
            if uid is not None and gid is not None:
                os.fchown(out.fileno(), uid, gid)
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
        dirfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _save_json(path: Path, value: dict) -> None:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    temp = path.with_name(path.name + "." + secrets.token_hex(5) + ".tmp")
    _file_sync(temp, raw)
    try:
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temp.exists():
            temp.unlink()


class ApplyManager:
    """Single-use, expiring preview tokens; backup journal persists in /data."""

    def __init__(self, root: Path = Path("/homeassistant"),
                 data: Path = Path("/data/dh-sync-transactions"),
                 *, catalog=None, fetcher=read_view, clock=time.monotonic):
        self.root = Path(root)
        self.data = Path(data)
        self.catalog = catalog if catalog is not None else PreviewCatalog()
        self.fetcher = fetcher
        self.clock = clock
        self.lock = threading.RLock()
        self.plans: dict[str, dict] = {}
        self.rollback_tokens: dict[str, float] = {}

    def _snapshot(self) -> dict:
        if not self.root.is_dir() or self.root.is_symlink():
            raise ApplyError("Home Assistant config mount unavailable")
        if os.statvfs(self.root).f_flag & getattr(os, "ST_RDONLY", 1):
            raise ApplyError("Home Assistant config mount is read-only; Apply disabled")
        _safe_path(self.root, self.root / VIEW_DIR)
        self._assert_no_pending()
        snap = _local_snapshot(self.root)
        if snap["issues"]:
            raise ApplyError("; ".join(snap["issues"])[:300])
        folder = self.root / VIEW_DIR
        if not folder.is_dir() or folder.is_symlink():
            raise ApplyError("DigitalHouses views directory missing")
        return snap

    def _target(self, filename: str) -> Path:
        if (not isinstance(filename, str) or not filename.endswith(".yaml")
                or not filename[0].isalnum()
                or any(not (c.isalnum() or c in "._-") or ord(c) > 127
                       for c in filename)):
            raise ApplyError("Invalid destination YAML filename")
        target = self.root / VIEW_DIR / filename
        _safe_path(self.root, target)
        return target

    def prepare(self, claims: dict, identity: str) -> dict:
        with self.lock:
            self._assert_no_pending()
            if identity not in claims:
                raise ApplyError("Product was not discovered by MQTT")
            claim = claims[identity]
            canonical_repository(claim["repository"])  # sole source gate
            products = self.catalog.inspect({identity: claim})
            if len(products) != 1 or products[0]["error"]:
                raise ApplyError(products[0]["error"] if products else "No GitHub resources")
            product = products[0]
            if not product["views"]:
                raise ApplyError("No canonical dashboard files to apply")
            snap = self._snapshot()
            entries = []
            filenames = set()
            for view in product["views"]:
                source_path = ("" if product["product_path"] == "."
                               else product["product_path"] + "/") + (
                                   "dashboards/ru/" + view["file"])
                raw = self.fetcher(product["repository"], source_path, product["commit"])
                if len(raw) > MAX_VIEW_BYTES:
                    raise ApplyError("Canonical YAML exceeds size limit")
                verified = parse_view(raw, source_path, product["product"])
                if verified["path"] != view["path"]:
                    raise ApplyError("Canonical view changed during preview")
                if view["path"] in snap["storage_paths"]:
                    raise ApplyError("Lovelace Storage already has view " + view["path"])
                matches = snap["by_path"].get(view["path"], [])
                if len(matches) > 1:
                    raise ApplyError("Duplicate local Lovelace path " + view["path"])
                local = matches[0] if matches else None
                filename = local["name"] if local else view["file"]
                collision = snap["by_name"].get(view["file"])
                if collision and collision is not local:
                    raise ApplyError("Filename already used for another view: " + view["file"])
                if filename in filenames:
                    raise ApplyError("Two source views target the same filename")
                filenames.add(filename)
                target = self._target(filename)
                old = local["raw"] if local else None
                if old == raw:
                    action = "identical"
                elif old is None:
                    action = "create"
                else:
                    action = "replace"
                entries.append({
                    "filename": filename, "source_path": source_path,
                    "view_path": view["path"], "title": view["title"],
                    "action": action, "before": _sha(old) if old is not None else None,
                    "after": _sha(raw), "raw": raw,
                    "mode": stat.S_IMODE(target.stat().st_mode) if old is not None else 0o644,
                    "uid": target.stat().st_uid if old is not None else os.getuid(),
                    "gid": target.stat().st_gid if old is not None else os.getgid(),
                    "diff": _diff(old, raw) if old is not None and old != raw else None,
                    "bytes": len(raw),
                })
            token = secrets.token_urlsafe(24)
            self.plans[token] = {
                "created": self.clock(), "identity": identity, "product": product["product"],
                "repository": product["repository"], "commit": product["commit"],
                "entries": entries,
            }
            # Limit retained previews without ever approving a different source.
            if len(self.plans) > 20:
                oldest = sorted(self.plans, key=lambda x: self.plans[x]["created"])
                for key in oldest[:-20]:
                    self.plans.pop(key, None)
            return {
                "token": token, "product": product["product"],
                "commit": product["commit"], "repository": product["repository"],
                "entries": [{k: v for k, v in item.items() if k != "raw"}
                            for item in entries],
                "changes": sum(e["action"] != "identical" for e in entries),
            }

    def _recheck(self, entries: list[dict]) -> None:
        snap = self._snapshot()
        for e in entries:
            target = self._target(e["filename"])
            if e["view_path"] in snap["storage_paths"]:
                raise ApplyError("Storage collision appeared since preview")
            matches = snap["by_path"].get(e["view_path"], [])
            if e["before"] is None:
                if target.exists() or target.is_symlink() or matches:
                    raise ApplyError("New view appeared since preview; start again")
            else:
                if len(matches) != 1 or matches[0]["name"] != e["filename"]:
                    raise ApplyError("Local view identity changed; start again")
                if matches[0]["sha256"] != e["before"]:
                    raise ApplyError("Local YAML changed since preview; start again")
                current = target.stat()
                if (stat.S_IMODE(current.st_mode) != e["mode"]
                        or current.st_uid != e["uid"] or current.st_gid != e["gid"]):
                    raise ApplyError("Local YAML permissions changed since preview")

    def apply(self, token: str, *, confirmed: bool) -> dict:
        with self.lock:
            if not confirmed:
                raise ApplyError("Explicit confirmation required")
            plan = self.plans.pop(token, None)
            if plan is None or self.clock() - plan["created"] > 600:
                raise ApplyError("Preview expired or already used; prepare again")
            entries = [e for e in plan["entries"] if e["action"] != "identical"]
            if not entries:
                return {"status": "identical", "count": 0, "id": ""}
            self._recheck(plan["entries"])
            self.data.mkdir(mode=0o700, parents=True, exist_ok=True)
            txn = self.data / ("tx-" + secrets.token_hex(12))
            txn.mkdir(mode=0o700)
            manifest = {
                "id": txn.name, "identity": plan["identity"],
                "created": time.time(), "commit": plan["commit"], "state": "prepared",
                "entries": [],
            }
            for index, e in enumerate(entries):
                backup = str(index) + ".bak" if e["before"] else ""
                if backup:
                    path = self._target(e["filename"])
                    original = path.read_bytes()
                    if _sha(original) != e["before"]:
                        raise ApplyError("Local YAML changed while creating backup")
                    _file_sync(txn / backup, original)
                manifest["entries"].append({
                    "file": e["filename"], "view_path": e["view_path"],
                    "before": e["before"], "after": e["after"],
                    "mode": e["mode"], "uid": e["uid"], "gid": e["gid"],
                "backup": backup,
                })
            _save_json(txn / "manifest.json", manifest)
            written = []
            try:
                for e in entries:
                    path = self._target(e["filename"])
                    # A second just-in-time check avoids overwriting a manual
                    # edit made between initial batch preflight and this write.
                    if e["before"] is None:
                        if path.exists() or path.is_symlink():
                            raise ApplyError("New local YAML appeared during Apply")
                    elif (not path.is_file() or path.is_symlink()
                          or _sha(path.read_bytes()) != e["before"]):
                        raise ApplyError("Local YAML changed during Apply")
                    _atomic_replace(path, e["raw"], e["mode"], e["uid"], e["gid"])
                    written.append(e)
                manifest["state"] = "applied"
                _save_json(txn / "manifest.json", manifest)
            except Exception as exc:
                # Best-effort immediate rollback; keep journal if interrupted.
                problems = []
                for e in reversed(written):
                    try:
                        path = self._target(e["filename"])
                        original = next(m for m in manifest["entries"]
                                        if m["file"] == e["filename"])
                        if original["backup"]:
                            _atomic_replace(path, (txn / original["backup"]).read_bytes(),
                                            original["mode"], original["uid"], original["gid"])
                        else:
                            path.unlink()
                    except Exception as rollback_exc:
                        problems.append(str(rollback_exc))
                manifest["state"] = "recovered" if not problems else "needs_recovery"
                _save_json(txn / "manifest.json", manifest)
                raise ApplyError("Apply failed; rollback " +
                                 ("incomplete: " + "; ".join(problems) if problems
                                  else "completed") + ": " + str(exc)) from exc
            return {"status": "applied", "count": len(entries), "id": txn.name}


    def _pending_manifests(self) -> list[tuple[Path, dict]]:
        if not self.data.is_dir():
            return []
        pending = []
        for path in sorted(self.data.glob("tx-*/manifest.json")):
            if path.is_symlink() or path.parent.is_symlink():
                continue
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if item.get("state") in ("prepared", "rolling_back", "needs_recovery"):
                pending.append((path, item))
        return pending

    def _assert_no_pending(self) -> None:
        if self._pending_manifests():
            raise ApplyError("Unfinished YAML transaction; recovery required before Apply")

    def recover_pending(self) -> list[str]:
        """On startup undo interrupted transactions only if no user edits intervene.

        An unrelated edit results in needs_recovery; it is never overwritten.
        Already restored entries are allowed, and all backups are verified
        before touching any file.
        """
        with self.lock:
            recovered = []
            for path, manifest in self._pending_manifests():
                entries = manifest.get("entries", [])
                try:
                    if not isinstance(entries, list):
                        raise ApplyError("Corrupt transaction manifest")
                    work = []
                    for e in entries:
                        target = self._target(e["file"])
                        if target.is_symlink():
                            raise ApplyError("Unexpected symlink in recovery path")
                        state = _sha(target.read_bytes()) if target.is_file() else None
                        if state not in (e["before"], e["after"]):
                            raise ApplyError("User edit detected: " + e["file"])
                        backup = path.parent / e["backup"] if e["backup"] else None
                        if backup is not None:
                            if (not backup.is_file() or backup.is_symlink()
                                    or _sha(backup.read_bytes()) != e["before"]):
                                raise ApplyError("Invalid rollback backup: " + e["file"])
                        work.append((e, target, state, backup))
                    for e, target, state, backup in reversed(work):
                        if state == e["before"]:
                            continue
                        if backup is not None:
                            _atomic_replace(target, backup.read_bytes(), e["mode"],
                                            e["uid"], e["gid"])
                        else:
                            target.unlink()
                    manifest["state"] = "recovered"
                    recovered.append(manifest.get("id", path.parent.name))
                except (ApplyError, OSError, KeyError, ValueError):
                    manifest["state"] = "needs_recovery"
                _save_json(path, manifest)
            return recovered

    def last_transaction(self) -> dict | None:
        with self.lock:
            if not self.data.is_dir():
                return None
            candidates = []
            for path in self.data.glob("tx-*/manifest.json"):
                if path.is_symlink() or path.parent.is_symlink():
                    continue
                try:
                    manifest = json.loads(path.read_text())
                except (OSError, ValueError):
                    continue
                if isinstance(manifest.get("created"), (int, float)):
                    candidates.append(manifest)
            newest = max(candidates, key=lambda x: x["created"], default=None)
            return newest if newest and newest.get("state") == "applied" else None

    def rollback_preview(self) -> dict | None:
        with self.lock:
            manifest = self.last_transaction()
            if manifest is None:
                return None
            token = secrets.token_urlsafe(24)
            self.rollback_tokens[token] = (self.clock(), manifest["id"])
            return {"token": token, "transaction": manifest}

    def rollback(self, token: str, *, confirmed: bool) -> dict:
        with self.lock:
            if not confirmed:
                raise ApplyError("Explicit rollback confirmation required")
            ticket = self.rollback_tokens.pop(token, None)
            if ticket is None or self.clock() - ticket[0] > 600:
                raise ApplyError("Rollback token expired; prepare again")
            manifest = self.last_transaction()
            if manifest is None or manifest["id"] != ticket[1]:
                raise ApplyError("No successful transaction to roll back")
            txn = self.data / manifest["id"]
            for e in manifest["entries"]:
                path = self._target(e["file"])
                if not path.is_file() or path.is_symlink() or _sha(path.read_bytes()) != e["after"]:
                    raise ApplyError("YAML changed after Apply; rollback refused: " + e["file"])
                if e["backup"]:
                    backup = txn / e["backup"]
                    if not backup.is_file() or backup.is_symlink():
                        raise ApplyError("Backup missing: " + e["file"])
                    if _sha(backup.read_bytes()) != e["before"]:
                        raise ApplyError("Backup checksum mismatch: " + e["file"])
            manifest["state"] = "rolling_back"
            _save_json(txn / "manifest.json", manifest)
            try:
                for e in reversed(manifest["entries"]):
                    path = self._target(e["file"])
                    if e["backup"]:
                        _atomic_replace(path, (txn / e["backup"]).read_bytes(), e["mode"],
                                        e["uid"], e["gid"])
                    else:
                        path.unlink()
                manifest["state"] = "rolled_back"
            except Exception:
                manifest["state"] = "needs_recovery"
                _save_json(txn / "manifest.json", manifest)
                raise
            _save_json(txn / "manifest.json", manifest)
            return {"status": "rolled_back", "count": len(manifest["entries"]),
                    "id": manifest["id"]}
