"""Framework-neutral same-origin GET API and static resources for Ingress."""
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

from . import ROOT

ASSETS = {"/log": ("index.html", "text/html"), "/journal.js": ("journal.js", "text/javascript"),
          "/journal.css": ("journal.css", "text/css"),
          "/toast.js": ("toast.js", "text/javascript"), "/toast.css": ("toast.css", "text/css")}

def get(journal, url, tz):
    """Return (body, content_type, optional filename), or None for unrelated paths."""
    parsed = urlsplit(url)
    if parsed.path in ASSETS:
        name, mime = ASSETS[parsed.path]
        return (ROOT / "web" / name).read_bytes(), mime, None
    if parsed.path not in ("/api/log", "/api/log/export", "/api/log/toasts"):
        return None
    params = parse_qs(parsed.query)
    lang = params.get("lang", ["ru"])[0]
    if lang not in ("ru", "en"):
        raise ValueError("Invalid journal language")
    if parsed.path == "/api/log/export":
        name, content = journal.export(lang, tz)
        return content, "text/plain", name
    if parsed.path == "/api/log/toasts":
        raw_after = params.get("after", [None])[0]
        after = None if raw_after is None else int(raw_after)
        if after is not None and not 0 <= after < 2**63:
            raise ValueError("Invalid notification cursor")
        data = journal.toast_snapshot(after)
        for row in data["rows"]:
            row["message"] = journal.message(row, lang)
            row["icon"] = journal.icon(row)
            row["local_time"] = datetime.fromisoformat(row["ts"]).astimezone(journal.zone(tz)).strftime("%Y-%m-%d %H:%M:%S")
        # The browser needs only display facts, not the technical parameters.
        data["rows"] = [{key: row[key] for key in ("id", "ts", "level", "message", "icon", "local_time")} for row in data["rows"]]
        return data, "application/json", None
    after = int(params.get("after", ["0"])[0])
    if not 0 <= after < 2**63:
        raise ValueError("Invalid journal cursor")
    data = journal.snapshot(after, params.get("generation", [None])[0])
    zone = journal.zone(tz)
    for row in data["rows"]:
        row["message"] = journal.message(row, lang)
        row["icon"] = journal.icon(row)
        row["local_time"] = datetime.fromisoformat(row["ts"]).astimezone(zone).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    data["product"] = journal.product
    data["product_name"] = journal.product_name
    data["app_version"] = journal.app_version
    data["timezone"] = str(zone)
    return data, "application/json", None
