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

from apply_service import _file_sync, _save_json
from local_audit import _safe_path

LOG = logging.getLogger("dh_sync.dashboard")
URL_PATH = "digital-houses"
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
    """Idempotently register and maintain only the DigitalHouses panel."""

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
            if not isinstance(view, dict) or not isinstance(view.get("path"), str) or not view["path"]:
                raise DashboardError("View has no path: " + path.name)
            if view["path"] in keys:
                raise DashboardError("Duplicate DigitalHouses view path: " + view["path"])
            keys.add(view["path"])
            views.append(view)
        return views

    def _marker(self) -> dict | None:
        file = self.data / "dashboard-managed.json"
        if not file.exists():
            return None
        try:
            obj = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise DashboardError("Managed dashboard marker invalid") from exc
        if not isinstance(obj, dict) or obj.get("url_path") != URL_PATH or not isinstance(obj.get("paths"), list):
            raise DashboardError("Managed dashboard marker invalid")
        if not all(isinstance(p, str) for p in obj["paths"]):
            raise DashboardError("Managed dashboard marker invalid")
        return obj

    def _save_marker(self, paths: set[str]) -> None:
        self.data.mkdir(mode=0o700, parents=True, exist_ok=True)
        _save_json(self.data / "dashboard-managed.json", {
            "url_path": URL_PATH, "paths": sorted(paths),
        })

    def sync(self) -> dict:
        views = self._local_views()
        if not views:
            return {"state": "No published views", "url": ""}
        marker = self._marker()
        transport = self.transport() if isinstance(self.transport, type) else self.transport
        with transport.session() as ws:
            entries = ws.request("lovelace/dashboards/list")
            if not isinstance(entries, list):
                raise DashboardError("Invalid dashboard registry response")
            # Respect an already registered YAML dashboard with its own file.
            for item in entries:
                if (isinstance(item, dict) and item.get("mode") == "yaml"
                        and item.get("url_path") in (URL_PATH, "digitalhouses")):
                    yaml_config = ws.request("lovelace/config", url_path=item["url_path"],
                                             force=True)
                    actual = yaml_config.get("views") if isinstance(yaml_config, dict) else None
                    if not isinstance(actual, list) or not all(
                            isinstance(row, dict) for row in actual):
                        raise DashboardError("Registered YAML dashboard views unavailable")
                    local_paths = {view["path"] for view in views}
                    loaded_paths = {row.get("path") for row in actual}
                    if not local_paths.issubset(loaded_paths):
                        raise DashboardError("Registered YAML dashboard does not include DH views")
                    return {"state": "YAML registered", "url": "/" + item["url_path"] + "/"}
            matching = [item for item in entries if isinstance(item, dict)
                        and item.get("url_path") == URL_PATH]
            if len(matching) > 1:
                raise DashboardError("Duplicate DigitalHouses dashboard registry")
            if matching and matching[0].get("mode") != "storage":
                raise DashboardError("DigitalHouses dashboard is not Storage-mode")
            if matching and marker is None:
                raise DashboardError("Existing DigitalHouses dashboard is not owned by DH Sync")
            if not matching:
                ws.request("lovelace/dashboards/create", url_path=URL_PATH,
                           title=TITLE, icon=ICON, show_in_sidebar=True)
                self._save_marker(set())
                marker = {"url_path": URL_PATH, "paths": []}
                LOG.info("Registered DigitalHouses dashboard in Home Assistant")

            try:
                config = ws.request("lovelace/config", url_path=URL_PATH)
            except DashboardError as exc:
                if "config_not_found" not in str(exc):
                    raise
                config = {"views": []}
            if not isinstance(config, dict):
                raise DashboardError("Invalid DigitalHouses dashboard configuration")
            existing = config.get("views", [])
            if not isinstance(existing, list):
                raise DashboardError("DigitalHouses dashboard views are invalid")

            managed = set(marker["paths"])
            canonical = {view["path"]: view for view in views}
            rows, found = [], set()
            for row in existing:
                if not isinstance(row, dict) or not isinstance(row.get("path"), str):
                    raise DashboardError("Unknown DigitalHouses dashboard view")
                path = row["path"]
                if path in found:
                    raise DashboardError("Duplicate DigitalHouses dashboard view")
                found.add(path)
                if path in canonical:
                    if path not in managed:
                        raise DashboardError("Unmanaged view path occupied: " + path)
                    rows.append(canonical[path])
                else:
                    rows.append(row)  # preserve local-only views
            rows.extend(view for view in views if view["path"] not in found)
            new = {**config, "views": rows}
            if new == config:
                self._save_marker(managed | set(canonical))
                return {"state": "Current", "url": "/" + URL_PATH + "/"}

            # Persist a pre-image of changed Storage config in private /data.
            self.data.mkdir(mode=0o700, parents=True, exist_ok=True)
            backup = self.data / ("dashboard-backup-" + secrets.token_hex(8) + ".json")
            _file_sync(backup, json.dumps(config, ensure_ascii=False).encode("utf-8"))
            self._save_marker(managed | set(canonical))
            ws.request("lovelace/config/save", url_path=URL_PATH, config=new)
            if ws.request("lovelace/config", url_path=URL_PATH, force=True) != new:
                raise DashboardError("Home Assistant dashboard save was not confirmed")
            return {"state": "Updated", "url": "/" + URL_PATH + "/"}
