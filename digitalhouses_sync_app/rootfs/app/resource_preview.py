"""Read-only dynamic dashboard preview: GitHub owner DigitalHouses is the only
product-source admission rule. No per-product pins, registry or version gates.

Each explicit preview resolves the repository's default branch to an exact
commit SHA first, then reads all views from that single immutable revision.
No YAML is installed, and no request uses an MQTT URL as a network endpoint.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit

import yaml

from discovery_contract import DiscoveryError, canonical_repository, safe_product_path

FILE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.yaml\Z")
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
ORG = "DigitalHouses"
API = "https://api.github.com/repos/" + ORG + "/"
RAW = "https://raw.githubusercontent.com/" + ORG + "/"


class PreviewError(ValueError):
    pass


def _download(url: str, host: str, max_bytes: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "DH-Sync-Preview/0.2"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            final = urlsplit(response.geturl())
            if (final.scheme != "https" or final.hostname != host
                    or final.username is not None or final.password is not None
                    or final.port is not None):
                raise PreviewError("GitHub redirected outside the fixed source host")
            data = response.read(max_bytes + 1)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        if isinstance(exc, PreviewError):
            raise
        raise PreviewError("GitHub source unavailable") from exc
    if len(data) > max_bytes:
        raise PreviewError("Source response too large")
    return data


def _repo_name(repository: str) -> str:
    try:
        return canonical_repository(repository).rsplit("/", 1)[-1]
    except DiscoveryError as exc:
        raise PreviewError("GitHub owner is not DigitalHouses") from exc


def _repository_api(repository: str) -> str:
    return API + quote(_repo_name(repository), safe="")


def resolve_revision(repository: str) -> tuple[str, str]:
    """Capture the current Git revision; not a source approval or version gate."""
    base = _repository_api(repository)
    try:
        metadata = json.loads(_download(base, "api.github.com", 120_000))
        owner = metadata["owner"]["login"]
        branch = metadata["default_branch"]
        if (not isinstance(owner, str) or owner.lower() != ORG.lower()
                or not isinstance(branch, str) or not branch or len(branch) > 200):
            raise PreviewError("GitHub repository owner or default branch invalid")
        revision = json.loads(_download(
            base + "/branches/" + quote(branch, safe=""),
            "api.github.com", 120_000,
        ))["commit"]["sha"]
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        if isinstance(exc, PreviewError):
            raise
        raise PreviewError("Unable to resolve GitHub repository revision") from exc
    if not isinstance(revision, str) or not SHA_RE.fullmatch(revision):
        raise PreviewError("Invalid GitHub commit identifier")
    return revision, branch


def _directory(product_path: str) -> str:
    return ("dashboards/ru" if product_path == "."
            else product_path + "/dashboards/ru")


def list_views(repository: str, product_path: str, commit: str) -> list:
    if not SHA_RE.fullmatch(commit):
        raise PreviewError("Invalid GitHub commit")
    safe_path = safe_product_path(product_path, "invalid_product")
    if safe_path != product_path:
        raise PreviewError("Invalid GitHub product directory")
    folder = _directory(product_path)
    path = quote(folder, safe="/")
    url = _repository_api(repository) + "/contents/" + path + "?ref=" + commit
    try:
        data = json.loads(_download(url, "api.github.com", 150_000))
    except (ValueError, UnicodeError) as exc:
        raise PreviewError("Invalid GitHub directory response") from exc
    if not isinstance(data, list):
        raise PreviewError("Canonical RU dashboard folder is not present")
    return data


def read_view(repository: str, path: str, commit: str) -> bytes:
    if not SHA_RE.fullmatch(commit):
        raise PreviewError("Invalid GitHub commit")
    if not isinstance(path, str) or not path.endswith(".yaml"):
        raise PreviewError("Invalid canonical view path")
    segments = path.split("/")
    if any(not part or part in (".", "..") or "%" in part or "\\" in part
           for part in segments):
        raise PreviewError("Unsafe canonical view path")
    return _download(
        RAW + quote(_repo_name(repository), safe="") + "/" + commit + "/" +
        quote(path, safe="/"),
        "raw.githubusercontent.com", 600_000,
    )


def parse_view(raw: bytes, path: str, product: str) -> dict:
    """Recognize a standalone Lovelace view; metadata headers are optional."""
    try:
        text = raw.decode("utf-8", "strict")
        view = yaml.safe_load(text)
    except (UnicodeError, yaml.YAMLError, RecursionError) as exc:
        raise PreviewError("Invalid canonical view YAML: " + path) from exc
    if (not isinstance(view, dict) or view.get("type") != "sections"
            or not isinstance(view.get("sections"), list)
            or not isinstance(view.get("title"), str)
            or not isinstance(view.get("path"), str) or not view["path"]):
        raise PreviewError("Not a standalone sections view: " + path)
    metadata = {}
    for line in text.splitlines()[:15]:
        found = re.fullmatch(
            r"# (DH-View|DH-View-Version|DH-Compatible-(?:Agent|App)): (.+)", line,
        )
        if found:
            metadata[found.group(1)] = found.group(2)
    return {
        "file": path.rsplit("/", 1)[-1],
        "title": view["title"],
        "path": view["path"],
        "revision": metadata.get("DH-View-Version", "—"),
        "constraint": metadata.get(
            "DH-Compatible-Agent" if product.endswith("_agent")
            else "DH-Compatible-App", "—",
        ),
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
                    view["blocked"] = False
                    row["views"].append(view)
                if not row["views"]:
                    row["error"] = "В GitHub нет dashboards/ru/*.yaml"
            except (PreviewError, DiscoveryError, ValueError, TypeError, UnicodeError) as exc:
                row["views"] = []
                row["error"] = str(exc)[:180]
        return results
