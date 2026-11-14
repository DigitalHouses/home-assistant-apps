"""Read-only preview of canonical views at pinned, review-controlled Git commits.

MQTT source claims are never used as Git URLs, revisions, or download paths.
This module never modifies Home Assistant state. No background Git polling.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit

import yaml

MONOREPO = "https://github.com/DigitalHouses/home-assistant-apps"
API = "https://api.github.com/repos/DigitalHouses/home-assistant-apps/contents/"
RAW = "https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/"
PRODUCT_RE = re.compile(r"digitalhouses_[a-z0-9_]+_(?:app|agent)\Z")
FILE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.yaml\Z")
SEMVER = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)\Z")
RANGE = re.compile(r">=([0-9]+\.[0-9]+\.[0-9]+),<([0-9]+\.[0-9]+\.[0-9]+)\Z")


@dataclass(frozen=True)
class Pin:
    commit: str
    label: str
    reviewed: bool


# Immutable review boundaries for the pilot, not a product/repository registry.
# GitHub itself enumerates an arbitrary number of dashboard YAML files.
PINS = {
    "digitalhouses_pve_agent": Pin(
        "7a2bc76f7c69312366ea70a6d9236549a978d636",
        "Утверждённые Proxmox/UPS · merged PR #502", True,
    ),
    "digitalhouses_plex_agent": Pin(
        "fd9d257972f0afdf979bfdd27ba7c6c86991fceb",
        "Plex dashboard + Recorder · merged PR #508", True,
    ),
}


class PreviewError(ValueError):
    pass


def _download(url: str, host: str, max_bytes: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "DH-Sync-Preview/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            final = urlsplit(response.geturl())
            if (final.scheme != "https" or final.hostname != host
                    or final.username is not None or final.password is not None
                    or final.port is not None):
                raise PreviewError("GitHub redirected outside pinned source host")
            data = response.read(max_bytes + 1)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        if isinstance(exc, PreviewError):
            raise
        raise PreviewError("GitHub source unavailable") from exc
    if len(data) > max_bytes:
        raise PreviewError("Source response too large")
    return data


def list_views(product: str, commit: str) -> list:
    url = API + product + "/dashboards/ru?ref=" + commit
    try:
        data = json.loads(_download(url, "api.github.com", 150_000))
    except (ValueError, UnicodeError) as exc:
        raise PreviewError("Invalid GitHub directory response") from exc
    if not isinstance(data, list):
        raise PreviewError("Canonical RU dashboards directory not found")
    return data


def read_view(path: str, commit: str) -> bytes:
    return _download(RAW + commit + "/" + path, "raw.githubusercontent.com", 600_000)


def version_tuple(value) -> tuple[int, int, int] | None:
    match = SEMVER.fullmatch(value) if isinstance(value, str) else None
    return tuple(int(n) for n in match.groups()) if match else None


def compatible(installed: str, constraint: str) -> bool:
    match = RANGE.fullmatch(constraint)
    if not match:
        return False
    version = version_tuple(installed)
    lower, upper = version_tuple(match.group(1)), version_tuple(match.group(2))
    return bool(version and lower and upper and lower <= version < upper)


def parse_view(raw: bytes, path: str, product: str) -> dict:
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeError as exc:
        raise PreviewError("Invalid view encoding: " + path) from exc
    header = {}
    for line in text.splitlines()[:10]:
        found = re.fullmatch(
            r"# (DH-View|DH-View-Version|DH-Compatible-(?:Agent|App)): (.+)", line,
        )
        if found:
            if found.group(1) in header:
                raise PreviewError("Duplicate metadata header: " + path)
            header[found.group(1)] = found.group(2)
    compatible_key = "DH-Compatible-Agent" if product.endswith("_agent") else "DH-Compatible-App"
    expected_view = "dh_" + product.removeprefix("digitalhouses_")
    if (header.get("DH-View") != expected_view
            or not version_tuple(header.get("DH-View-Version"))
            or not header.get(compatible_key)):
        raise PreviewError("Missing or mismatched canonical view metadata: " + path)
    try:
        view = yaml.safe_load(text)
    except (yaml.YAMLError, RecursionError) as exc:
        raise PreviewError("Invalid view YAML: " + path) from exc
    if (not isinstance(view, dict) or view.get("type") != "sections"
            or not isinstance(view.get("sections"), list)
            or not isinstance(view.get("title"), str)
            or not isinstance(view.get("path"), str) or not view["path"]
            or "views" in view or "lovelace" in view):
        raise PreviewError("Invalid standalone view: " + path)
    return {
        "file": path.rsplit("/", 1)[-1],
        "title": view["title"],
        "path": view["path"],
        "revision": header["DH-View-Version"],
        "constraint": header[compatible_key],
    }


class PreviewCatalog:
    def __init__(self, *, listing=list_views, reader=read_view):
        self.listing = listing
        self.reader = reader

    def inspect(self, claims: dict[str, dict]) -> list[dict]:
        results = []
        for identity, claim in sorted(claims.items()):
            product = claim.get("product_id")
            entry = {
                "identity": identity, "product": product, "version": claim.get("version"),
                "commit": "", "label": "", "views": [], "error": "",
            }
            results.append(entry)
            if not isinstance(product, str) or not PRODUCT_RE.fullmatch(product):
                entry["error"] = "Некорректный product_id"
                continue
            if claim.get("repository") != MONOREPO or claim.get("product_path") != product:
                entry["error"] = "Источник не совпадает с разрешённым репозиторием пилота"
                continue
            pin = PINS.get(product)
            if pin is None:
                entry["error"] = "Ревизия ресурсов продукта ещё не проверена"
                continue
            entry["commit"], entry["label"] = pin.commit, pin.label
            try:
                listing = self.listing(product, pin.commit)
                if not isinstance(listing, list) or len(listing) > 100:
                    raise PreviewError("Too many or invalid directory entries")
                prefix = product + "/dashboards/ru/"
                files = []
                for obj in listing:
                    if not isinstance(obj, dict):
                        raise PreviewError("Invalid GitHub list item")
                    if obj.get("type") != "file":
                        continue
                    name, path = obj.get("name"), obj.get("path")
                    if (not isinstance(name, str) or not FILE_RE.fullmatch(name)
                            or path != prefix + name):
                        raise PreviewError("Unsafe YAML filename returned by GitHub")
                    files.append(path)
                paths = set()
                for path in sorted(files):
                    view = parse_view(self.reader(path, pin.commit), path, product)
                    if view["path"] in paths:
                        raise PreviewError("Duplicate Lovelace path in product")
                    paths.add(view["path"])
                    reasons = []
                    if not pin.reviewed:
                        reasons.append("Источник не утверждён")
                    if not compatible(claim["version"], view["constraint"]):
                        reasons.append("Нет подтверждения совместимости с установленной версией")
                    view["status"] = "; ".join(reasons) if reasons else "Совместимость подтверждена · только просмотр"
                    view["blocked"] = bool(reasons)
                    entry["views"].append(view)
                if not entry["views"]:
                    entry["error"] = "Нет канонических dashboards/ru/*.yaml"
            except (PreviewError, ValueError, TypeError, UnicodeError) as exc:
                entry["views"] = []
                entry["error"] = str(exc)[:180]
        return results
