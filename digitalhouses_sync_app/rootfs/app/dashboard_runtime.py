"""Publish declarative GitHub panels through the official HA Storage API."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import yaml


LOG = logging.getLogger("dh_sync.dashboard")


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
    """Publish only dashboards declared in GitHub panel YAML (no migrations)."""

    def __init__(self, root: Path, data: Path, *, transport=None, journal=None):
        self.root = Path(root)
        self.data = Path(data)
        self.transport = transport if transport is not None else SupervisorWS
        self.journal = journal

    @staticmethod
    def _render(panel: dict, sources: dict) -> list[dict]:
        """Resolve ordered (product, path) references against MQTT-discovered Git views."""
        rendered, paths = [], set()
        for ref in panel["views"]:
            source = sources.get((ref["product"], ref["path"]))
            if source is None:
                continue  # No retained /sync product or canonical view: not installed.
            try:
                view = yaml.safe_load(source["bytes"].decode("utf-8"))
            except (UnicodeError, yaml.YAMLError) as exc:
                raise DashboardError("Invalid canonical view: " + ref["path"]) from exc
            if (not isinstance(view, dict) or view.get("path") != ref["path"]
                    or not isinstance(view.get("title"), str)):
                raise DashboardError("Invalid canonical view identity: " + ref["path"])
            if view["path"] in paths:
                raise DashboardError("Duplicate view path inside panel: " + ref["path"])
            paths.add(view["path"])
            view = dict(view)
            for name, value in ref.get("overrides", {}).items():
                if name == "icon" and value is None:
                    view.pop("icon", None)
                else:
                    view[name] = value
            rendered.append(view)
        return rendered

    @staticmethod
    def _config(ws, slug: str) -> dict:
        try:
            result = ws.request("lovelace/config", url_path=slug)
        except DashboardError as exc:
            if "config_not_found" not in str(exc):
                raise
            return {"views": []}
        if not isinstance(result, dict) or not isinstance(result.get("views"), list):
            raise DashboardError("Invalid dashboard configuration: " + slug)
        return result

    @staticmethod
    def _entry(entries: list, slug: str) -> dict | None:
        matches = [row for row in entries
                   if isinstance(row, dict) and row.get("url_path") == slug]
        if len(matches) > 1:
            raise DashboardError("Duplicate panel URL: " + slug)
        return matches[0] if matches else None

    @staticmethod
    def _fields(panel: dict) -> dict:
        result = {name: panel[name] for name in
                  ("title", "show_in_sidebar", "require_admin")}
        if panel["icon"] is not None:
            result["icon"] = panel["icon"]
        return result

    def _publish(self, ws, entries: list, panel: dict, views: list[dict]) -> str:
        slug = panel["slug"]
        entry = self._entry(entries, slug)
        if entry is None and not views:
            return "No active views"
        metadata_updated = False
        if entry is not None:
            if entry.get("mode") != "storage":
                raise DashboardError("Panel is not a Storage dashboard: " + slug)
            fields = self._fields(panel)
            if any(entry.get(name) != value for name, value in fields.items()):
                if "id" not in entry:
                    raise DashboardError("Dashboard ID unavailable: " + slug)
                ws.request("lovelace/dashboards/update",
                           dashboard_id=entry["id"], **fields)
                entry.update(fields)
                metadata_updated = True
        else:
            fields = self._fields(panel)
            response = ws.request("lovelace/dashboards/create",
                                  url_path=slug, **fields)
            entry = {"url_path": slug, "mode": "storage", **fields}
            if isinstance(response, dict) and "id" in response:
                entry["id"] = response["id"]
            entries.append(entry)
            LOG.info("Created panel %s", slug)
            if self.journal is not None:
                self.journal.record("dashboard_created", slug)

        old = self._config(ws, slug)
        new = {**old, "views": views}
        if old == new:
            return "Updated" if metadata_updated else "Current"
        ws.request("lovelace/config/save", url_path=slug, config=new)
        if ws.request("lovelace/config", url_path=slug, force=True) != new:
            raise DashboardError("Panel save not confirmed: " + slug)
        if self.journal is not None:
            old_views = {v.get("path"): v for v in old["views"] if isinstance(v, dict)}
            for ref in panel["views"]:
                for view in views:
                    if view["path"] == ref["path"] and old_views.get(ref["path"]) != view:
                        self.journal.record("view_updated", slug + "/" + ref["path"], product=ref["product"])
        return "Updated"

    def sync(self, panels: list[dict], sources: dict) -> dict:
        """YAML alone controls panel contents; no legacy routes or view migrations."""
        if not panels:
            return {"state": "No panel YAML", "url": "", "dashboards": [], "issues": []}
        results, issues = [], []
        transport = self.transport() if isinstance(self.transport, type) else self.transport
        with transport.session() as ws:
            entries = ws.request("lovelace/dashboards/list")
            if not isinstance(entries, list):
                raise DashboardError("Invalid dashboard registry")
            for panel in panels:
                slug = panel["slug"]
                try:
                    views = self._render(panel, sources)
                    state = self._publish(ws, entries, panel, views)
                    results.append({"slug": slug, "url": "/" + slug + "/",
                                    "state": state, "views": len(views)})
                    if state == "Updated" and self.journal is not None:
                        self.journal.record("dashboard_updated", slug)
                except Exception as exc:
                    issues.append("Dashboard " + slug + ": " + str(exc)[:160])
                    results.append({"slug": slug, "url": "/" + slug + "/",
                                    "state": "Error", "views": 0})
        updated = any(r["state"] == "Updated" for r in results)
        return {"state": "Partial" if issues else "Updated" if updated else "Current",
                "url": results[0]["url"] if len(results) == 1 else "",
                "dashboards": results, "issues": issues}
