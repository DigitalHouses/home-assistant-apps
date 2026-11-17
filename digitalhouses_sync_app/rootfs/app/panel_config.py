"""Data-only panel contract; MQTT /sync remains the sole product registry."""
from __future__ import annotations

import re
import yaml
from discovery_contract import TOPIC_PART

PANEL_DIRECTORY = "digitalhouses_sync_app/dashboards"
PANEL_REPOSITORY = "https://github.com/DigitalHouses/home-assistant-apps"
PANEL_SLUG = re.compile(r"[a-z0-9][a-z0-9-]*-[a-z0-9][a-z0-9-]*\Z")


class PanelError(ValueError):
    pass


def parse_panel(filename: str, raw: bytes) -> dict:
    """One panel file defines native HA properties and an ordered view list."""
    if not filename.endswith(".yaml") or not PANEL_SLUG.fullmatch(filename[:-5]):
        raise PanelError("Invalid panel filename: " + filename)
    try:
        panel = yaml.safe_load(raw.decode("utf-8", "strict"))
    except (UnicodeError, yaml.YAMLError, RecursionError) as exc:
        raise PanelError("Invalid panel YAML: " + filename) from exc
    if not isinstance(panel, dict) or not isinstance(panel.get("title"), str) or not panel["title"]:
        raise PanelError("Panel title required: " + filename)
    if type(panel.get("require_admin")) is not bool:
        raise PanelError("require_admin must be explicit: " + filename)
    if type(panel.get("show_in_sidebar", True)) is not bool:
        raise PanelError("Invalid show_in_sidebar: " + filename)
    if panel.get("icon") is not None and not isinstance(panel["icon"], str):
        raise PanelError("Invalid panel icon: " + filename)
    entries = panel.get("views")
    if not isinstance(entries, list):
        raise PanelError("Panel views must be a list: " + filename)
    refs, identities = [], set()
    for row in entries:
        if not isinstance(row, dict):
            raise PanelError("Invalid view reference in " + filename)
        product, path = row.get("product"), row.get("path")
        if not isinstance(product, str) or not TOPIC_PART.fullmatch(product):
            raise PanelError("Invalid view product in " + filename)
        if not isinstance(path, str) or not path or "/" in path:
            raise PanelError("Invalid view path in " + filename)
        identity = product, path
        if identity in identities:
            raise PanelError("Repeated view reference in " + filename)
        identities.add(identity)
        overrides = {}
        for name in ("title", "icon", "show_icon_and_title"):
            if name not in row:
                continue
            value = row[name]
            if name == "show_icon_and_title" and type(value) is not bool:
                raise PanelError("Invalid show_icon_and_title in " + filename)
            if name == "title" and (not isinstance(value, str) or not value):
                raise PanelError("Invalid view title in " + filename)
            if name == "icon" and value is not None and not isinstance(value, str):
                raise PanelError("Invalid view icon in " + filename)
            overrides[name] = value
        refs.append({"product": product, "path": path, "overrides": overrides})
    return {
        "slug": filename[:-5],
        "title": panel["title"],
        "icon": panel.get("icon"),
        "show_in_sidebar": panel.get("show_in_sidebar", True),
        "require_admin": panel["require_admin"],
        "views": refs,
    }
