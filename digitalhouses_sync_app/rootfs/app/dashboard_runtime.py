"""Publish DigitalHouses YAML views to an HA-managed Storage dashboard.

Lovelace cannot register new YAML-mode dashboards using its WebSocket API.
Use official Storage dashboard APIs for live registration and keep local YAML
views as the canonical source. Never edit .storage files directly.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
from pathlib import Path

import yaml

from discovery_contract import DEFAULT_DASHBOARD, DASHBOARD_SLUG, safe_dashboard_slug

from apply_service import _file_sync, _save_json
from local_audit import _safe_path

LOG = logging.getLogger("dh_sync.dashboard")
URL_PATH = DEFAULT_DASHBOARD
TITLE = "DigitalHouses"
ICON = "mdi:home-assistant"
MAX_VIEW_BYTES = 1_000_000


class DashboardError(ValueError):
    pass


class SupervisorWS:
    """Small authenticated client for the official Core WebSocket proxy."""

    def __init__(self, token: str | None = None):
        self.token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN", "")
        if not self.token:
            raise DashboardError("Supervisor API token unavailable")

    def session(self):
        try:
            import websocket
        except ImportError as exc:
            raise DashboardError("websocket-client is not installed") from exc
        try:
            sock = websocket.create_connection(
                "ws://supervisor/core/websocket", timeout=15,
                http_proxy_host=None,
            )
            if json.loads(sock.recv()).get("type") != "auth_required":
                sock.close()
                raise DashboardError("Unexpected HA WebSocket handshake")
            sock.send(json.dumps({"type": "auth", "access_token": self.token}))
            if json.loads(sock.recv()).get("type") != "auth_ok":
                sock.close()
                raise DashboardError("Home Assistant API authorization failed")
            return _Session(sock)
        except (OSError, ValueError, websocket.WebSocketException) as exc:
            if isinstance(exc, DashboardError):
                raise
            raise DashboardError("Home Assistant WebSocket unavailable") from exc


class _Session:
    def __init__(self, sock):
        self.sock = sock
        self.next_id = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.sock.close()

    def request(self, kind: str, **fields):
        self.next_id += 1
        ident = self.next_id
        self.sock.send(json.dumps({"id": ident, "type": kind, **fields},
                                  ensure_ascii=False))
        try:
            for _ in range(16):
                reply = json.loads(self.sock.recv())
                if reply.get("id") != ident:
                    continue
                if reply.get("type") != "result":
                    raise DashboardError("Unexpected Home Assistant response")
                if not reply.get("success"):
                    err = reply.get("error")
                    code = err.get("code", "unknown") if isinstance(err, dict) else "unknown"
                    raise DashboardError(kind + ": " + str(code))
                return reply.get("result")
        except (OSError, ValueError) as exc:
            if isinstance(exc, DashboardError):
                raise
            raise DashboardError("Home Assistant dashboard API unavailable") from exc
        raise DashboardError("Missing Home Assistant response")


class DashboardPublisher:
    """Manage DigitalHouses-owned Storage dashboards, keyed by MQTT slug."""

    def __init__(self, root: Path, data: Path, *, transport=None):
        self.root = Path(root)
        self.data = Path(data)
        self.transport = transport if transport is not None else SupervisorWS

    def _local_views(self) -> list[dict]:
        folder = self.root / "dashboards/dh/views"
        _safe_path(self.root, folder)
        views, keys = [], set()
        for path in sorted(file for file in folder.iterdir()
                           if file.suffix in (".yaml", ".yml")):
            _safe_path(self.root, path)
            if not path.is_file() or path.stat().st_size > MAX_VIEW_BYTES:
                raise DashboardError("Unsafe DigitalHouses view: " + path.name)
            try:
                view = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (UnicodeError, yaml.YAMLError) as exc:
                raise DashboardError("Invalid DigitalHouses view: " + path.name) from exc
            if (not isinstance(view, dict) or not isinstance(view.get("path"), str)
                    or not view["path"]):
                raise DashboardError("View has no path: " + path.name)
            if view["path"] in keys:
                raise DashboardError("Duplicate DigitalHouses view path: " + view["path"])
            keys.add(view["path"])
            views.append(view)
        return views

    def _marker_file(self, slug: str) -> Path:
        if not DASHBOARD_SLUG.fullmatch(slug):
            raise DashboardError("Invalid dashboard slug")
        return self.data / "dashboard-managed" / (slug + ".json")

    def _marker(self, slug: str) -> set[str] | None:
        file = self._marker_file(slug)
        if not file.exists() and slug == DEFAULT_DASHBOARD:
            # Pick up the 0.4.x single-dashboard ownership marker.
            file = self.data / "dashboard-managed.json"
        if not file.exists():
            return None
        if file.is_symlink():
            raise DashboardError("Dashboard ownership marker is a symlink")
        try:
            obj = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise DashboardError("Managed dashboard marker invalid") from exc
        if (not isinstance(obj, dict) or obj.get("url_path") != slug
                or not isinstance(obj.get("paths"), list)
                or not all(isinstance(path, str) and path for path in obj["paths"])):
            raise DashboardError("Managed dashboard marker invalid")
        return set(obj["paths"])

    def _all_markers(self) -> dict[str, set[str]]:
        markers = {}
        folder = self.data / "dashboard-managed"
        if folder.exists():
            if folder.is_symlink() or not folder.is_dir():
                raise DashboardError("Invalid dashboard ownership folder")
            for path in sorted(folder.glob("*.json")):
                slug = path.stem
                marker = self._marker(slug)
                if marker is not None:
                    markers[slug] = marker
        if DEFAULT_DASHBOARD not in markers:
            legacy = self._marker(DEFAULT_DASHBOARD)
            if legacy is not None:
                markers[DEFAULT_DASHBOARD] = legacy
        return markers

    def _save_marker(self, slug: str, paths: set[str]) -> None:
        file = self._marker_file(slug)
        file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if file.is_symlink():
            raise DashboardError("Dashboard ownership marker is a symlink")
        _save_json(file, {"url_path": slug, "paths": sorted(paths)})

    @staticmethod
    def _config(ws, slug: str) -> dict:
        try:
            config = ws.request("lovelace/config", url_path=slug)
        except DashboardError as exc:
            if "config_not_found" not in str(exc):
                raise
            config = {"views": []}
        if not isinstance(config, dict) or not isinstance(config.get("views"), list):
            raise DashboardError("Invalid dashboard config: " + slug)
        paths = set()
        for row in config["views"]:
            if not isinstance(row, dict) or not isinstance(row.get("path"), str):
                raise DashboardError("Unknown dashboard view: " + slug)
            if row["path"] in paths:
                raise DashboardError("Duplicate view in dashboard: " + slug)
            paths.add(row["path"])
        return config

    def _save(self, ws, slug: str, previous: dict, current: dict,
              managed: set[str]) -> bool:
        if previous == current:
            self._save_marker(slug, managed)
            return False
        self.data.mkdir(mode=0o700, parents=True, exist_ok=True)
        backup = self.data / ("dashboard-backup-" + secrets.token_hex(8) + ".json")
        _file_sync(backup, json.dumps(previous, ensure_ascii=False).encode("utf-8"))
        # Persist the ownership record first so that an interrupted save can
        # be retried without declaring our own new view to be user-owned.
        self._save_marker(slug, managed)
        ws.request("lovelace/config/save", url_path=slug, config=current)
        if ws.request("lovelace/config", url_path=slug, force=True) != current:
            raise DashboardError("Home Assistant dashboard save was not confirmed: " + slug)
        return True

    @staticmethod
    def _registry_entry(entries: list, slug: str) -> dict | None:
        matching = [item for item in entries if isinstance(item, dict)
                    and item.get("url_path") == slug]
        if len(matching) > 1:
            raise DashboardError("Duplicate dashboard registry: " + slug)
        return matching[0] if matching else None

    def _publish(self, ws, entries: list, slug: str, views: list[dict],
                 managed: set[str] | None) -> str:
        entry = self._registry_entry(entries, slug)
        # Keep the alternate legacy YAML URL understood by DH Sync 0.4.x.
        if entry is None and slug == DEFAULT_DASHBOARD:
            alias = self._registry_entry(entries, "digitalhouses")
            if alias is not None and alias.get("mode") == "yaml":
                entry = alias
        desired = {view["path"]: view for view in views}
        if entry is not None and entry.get("mode") == "yaml":
            loaded = ws.request("lovelace/config", url_path=entry["url_path"], force=True)
            loaded_views = loaded.get("views") if isinstance(loaded, dict) else None
            if not isinstance(loaded_views, list) or not all(
                    isinstance(row, dict) for row in loaded_views):
                raise DashboardError("Registered YAML dashboard views unavailable: " + slug)
            if not set(desired).issubset({row.get("path") for row in loaded_views}):
                raise DashboardError("Registered YAML dashboard does not include DH views: " + slug)
            return "YAML registered"

        if entry is not None and entry.get("mode") != "storage":
            raise DashboardError("Dashboard mode is not Storage: " + slug)
        if entry is not None and managed is None:
            raise DashboardError("Existing dashboard is not owned by DH Sync: " + slug)
        if entry is None:
            ws.request("lovelace/dashboards/create", url_path=slug,
                       title="DigitalHouses" if slug == DEFAULT_DASHBOARD
                             else ("DH " + slug[3:].replace("-", " ").title()
                                   if slug.startswith("dh-")
                                   else slug.replace("-", " ").title()),
                       icon=ICON, show_in_sidebar=True)
            self._save_marker(slug, set())
            managed = set()
            entries.append({"url_path": slug, "mode": "storage"})
            LOG.info("Registered dashboard %s", slug)

        managed = managed or set()
        config = self._config(ws, slug)
        rows, found = [], set()
        for row in config["views"]:
            path = row["path"]
            found.add(path)
            if path in desired:
                if path not in managed:
                    raise DashboardError("Unmanaged view path occupied: " + path)
                rows.append(desired[path])
            else:
                rows.append(row)  # Leave user views and not-yet-migrated views intact.
        rows.extend(view for view in views if view["path"] not in found)
        changed = self._save(ws, slug, config, {**config, "views": rows},
                             managed | set(desired))
        return "Updated" if changed else "Current"

    def _move_out(self, ws, entries: list, slug: str,
                  paths: set[str], managed: set[str]) -> bool:
        entry = self._registry_entry(entries, slug)
        if entry is None:
            # The previous panel was removed externally. Do not recreate it.
            self._save_marker(slug, managed - paths)
            return False
        if entry.get("mode") != "storage":
            raise DashboardError("Cannot migrate from non-Storage dashboard: " + slug)
        config = self._config(ws, slug)
        if not paths.issubset(managed):
            raise DashboardError("Refusing to remove unmanaged dashboard views")
        rows = [row for row in config["views"] if row["path"] not in paths]
        return self._save(ws, slug, config, {**config, "views": rows},
                          managed - paths)

    def sync(self, routes: dict[str, str] | None = None) -> dict:
        views = self._local_views()
        if not views:
            return {"state": "No published views", "url": "", "dashboards": [], "issues": []}
        routes = routes or {}
        markers = self._all_markers()
        assignments = {}
        issues = []
        for view in views:
            path = view["path"]
            if path in routes:
                slug = safe_dashboard_slug(routes[path])
                if slug != routes[path]:
                    issues.append("Invalid dashboard for view: " + path)
            else:
                # A temporarily unavailable product keeps its previous panel.
                prior = [slug for slug, owned in markers.items() if path in owned]
                if len(prior) > 1:
                    issues.append("View belongs to multiple dashboards: " + path)
                    continue
                slug = prior[0] if prior else DEFAULT_DASHBOARD
            assignments[path] = slug

        groups: dict[str, list[dict]] = {}
        for view in views:
            slug = assignments.get(view["path"])
            if slug is not None:
                groups.setdefault(slug, []).append(view)

        results = []
        successful_paths = set()
        transport = self.transport() if isinstance(self.transport, type) else self.transport
        with transport.session() as ws:
            entries = ws.request("lovelace/dashboards/list")
            if not isinstance(entries, list):
                raise DashboardError("Invalid dashboard registry response")
            for slug, wanted in sorted(groups.items()):
                try:
                    state = self._publish(ws, entries, slug, wanted, markers.get(slug))
                    successful_paths.update(view["path"] for view in wanted)
                    entry = self._registry_entry(entries, slug)
                    alias = self._registry_entry(entries, "digitalhouses") if (
                        slug == DEFAULT_DASHBOARD and entry is None) else None
                    actual_slug = ("digitalhouses" if state == "YAML registered"
                                   and alias is not None else slug)
                    results.append({"slug": slug, "url": "/" + actual_slug + "/",
                                    "state": state, "views": len(wanted)})
                except Exception as exc:
                    issues.append("Dashboard " + slug + ": " + str(exc)[:160])
                    results.append({"slug": slug, "url": "/" + slug + "/",
                                    "state": "Error", "views": len(wanted)})

            # Only remove a view from the old panel AFTER its destination is saved.
            # The original 0.4.x marker supplies ownership for the first migration.
            for slug, managed in sorted(markers.items()):
                move = {path for path in managed if path in successful_paths
                        and assignments.get(path) != slug}
                if not move:
                    continue
                try:
                    changed = self._move_out(ws, entries, slug, move, managed)
                    for row in results:
                        if row["slug"] == slug and changed and row["state"] == "Current":
                            row["state"] = "Updated"
                    if not any(row["slug"] == slug for row in results):
                        results.append({"slug": slug, "url": "/" + slug + "/",
                                        "state": "Updated" if changed else "Current",
                                        "views": 0})
                except Exception as exc:
                    issues.append("Dashboard migration " + slug + ": " + str(exc)[:160])

        changed = any(row["state"] == "Updated" for row in results)
        state = ("Partial" if issues else "Updated" if changed
                 else "YAML registered" if results and all(
                     row["state"] == "YAML registered" for row in results)
                 else "Current")
        return {"state": state, "url": results[0]["url"] if len(results) == 1 else "",
                "dashboards": results, "issues": issues}
