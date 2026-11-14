"""Canonical Dashboard discovery from cached shallow Git snapshots.

Source admission is the repository owner DigitalHouses; no product/version gate.
Git transport does not use the GitHub REST API or require credentials.
"""
from __future__ import annotations

import re
import yaml

from discovery_contract import DiscoveryError, canonical_repository, safe_product_path
from git_source import GitSourceError, resolve_revision, list_views, read_view

FILE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.yaml\Z")


class PreviewError(ValueError):
    pass


def _directory(product_path: str) -> str:
    return ('dashboards/ru' if product_path == '.' else product_path + '/dashboards/ru')


def parse_view(raw: bytes, path: str, product: str) -> dict:
    """Recognize a standalone Lovelace view; metadata headers are optional."""
    try:
        text = raw.decode("utf-8", "strict")
        view = yaml.safe_load(text)
    except (UnicodeError, yaml.YAMLError, RecursionError) as exc:
        raise PreviewError("Invalid canonical view YAML: " + path) from exc
    if (not isinstance(view, dict)
            or not isinstance(view.get("title"), str) or not view["title"]
            or not isinstance(view.get("path"), str) or not view["path"]
            or not isinstance(view.get("type", "masonry"), str)):
        raise PreviewError("Not a standalone Lovelace view: " + path)
    metadata = {}
    for line in text.splitlines()[:15]:
        found = re.fullmatch(
            r"# (DH-View|DH-View-Version): (.+)", line,
        )
        if found:
            metadata[found.group(1)] = found.group(2)
    return {
        "file": path.rsplit("/", 1)[-1],
        "title": view["title"],
        "path": view["path"],
        "revision": metadata.get("DH-View-Version", "—"),
    }


class PreviewCatalog:
    def __init__(self, *, resolver=resolve_revision, listing=list_views, reader=read_view):
        self.resolver = resolver
        self.listing = listing
        self.reader = reader

    def inspect(self, claims: dict[str, dict]) -> list[dict]:
        results = []
        for identity, claim in sorted(claims.items()):
            product = claim["product_id"]
            repo = claim["repository"]
            folder = safe_product_path(claim.get("product_path"), product)
            row = {
                "identity": identity, "product": product, "version": claim.get("version", "unknown"),
                "repository": repo, "product_path": folder,
                "commit": "", "label": "", "views": [], "error": "",
            }
            results.append(row)
            try:
                canonical_repository(repo)  # only source-owner admission rule
                sha, branch = self.resolver(repo)
                row["commit"] = sha
                row["label"] = "DigitalHouses · " + branch
                listing = self.listing(repo, folder, sha)
                if not isinstance(listing, list) or len(listing) > 100:
                    raise PreviewError("Invalid or oversized GitHub directory listing")
                prefix = _directory(folder) + "/"
                filenames = []
                for item in listing:
                    if not isinstance(item, dict):
                        raise PreviewError("Invalid GitHub directory item")
                    if item.get("type") != "file":
                        continue
                    name, path = item.get("name"), item.get("path")
                    if (not isinstance(name, str) or not FILE_RE.fullmatch(name)
                            or path != prefix + name):
                        raise PreviewError("Unsafe GitHub YAML filename")
                    filenames.append(path)
                seen_paths = set()
                for path in sorted(filenames):
                    view = parse_view(self.reader(repo, path, sha), path, product)
                    if view["path"] in seen_paths:
                        raise PreviewError("Duplicate Lovelace view path")
                    seen_paths.add(view["path"])
                    view["status"] = "Владелец DigitalHouses · только просмотр"
                    row["views"].append(view)
                if not row["views"]:
                    row["error"] = "Нет опубликованных ресурсов"
            except (PreviewError, GitSourceError, DiscoveryError, ValueError, TypeError, UnicodeError) as exc:
                row["views"] = []
                row["error"] = str(exc)[:180]
        return results
