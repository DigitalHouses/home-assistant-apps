"""Framework-neutral same-origin GET API and static resources for Ingress."""
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

from . import ROOT

ASSETS = {"/log": ("index.html", "text/html"), "/journal.js": ("journal.js", "text/javascript"),
          "/journal.css": ("journal.css", "text/css")}

def get(journal, url, tz):
    """Return (body, content_type, optional filename), or None for unrelated paths."""
    parsed = urlsplit(url)
    if parsed.path in ASSETS:
        name, mime = ASSETS[parsed.path]
        return (ROOT / "web" / name).read_bytes(), mime, None
    if parsed.path not in ("/api/log", "/api/log/export"):
        return None
    params = parse_qs(parsed.query)
    lang = params.get("lang", ["ru"])[0]
    if lang not in ("ru", "en"):
        raise ValueError("Invalid journal language")
    if parsed.path == "/api/log/export":
        name, content = journal.export(lang, tz)
        return content, "text/plain", name
    after = int(params.get("after", ["0"])[0])
    if not 0 <= after < 2**63:
        raise ValueError("Invalid journal cursor")
    data = journal.snapshot(after, params.get("generation", [None])[0])
    zone = journal.zone(tz)
    for row in data["rows"]:
        row["message"] = journal.message(row, lang)
        row["local_time"] = datetime.fromisoformat(row["ts"]).astimezone(zone).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    data["product"] = journal.product
    data["timezone"] = str(zone)
    return data, "application/json", None
