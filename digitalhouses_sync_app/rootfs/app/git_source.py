"""Public Git transport for DigitalHouses canonical YAML (no REST API or token).

A single shallow git snapshot serves every product from the same repository.
Git operations do not consume GitHub REST API quota. The only repository-source
admission rule remains the exact GitHub owner: DigitalHouses.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from discovery_contract import DiscoveryError, canonical_repository, safe_product_path

ORG = "DigitalHouses"
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
CACHE_SECONDS = 300


class GitSourceError(ValueError):
    pass


class GitSnapshots:
    def __init__(self, root: Path = Path("/tmp/dh-sync-git"), *,
                 ttl: int = CACHE_SECONDS, clock=time.monotonic,
                 runner=subprocess.run):
        self.root = Path(root)
        self.ttl = ttl
        self.clock = clock
        self.runner = runner
        self.lock = threading.RLock()
        self.cached: dict[str, dict] = {}

    def _name(self, repository: str) -> str:
        try:
            url = canonical_repository(repository)
        except DiscoveryError as exc:
            raise GitSourceError("GitHub owner is not DigitalHouses") from exc
        name = url.rsplit("/", 1)[-1]
        if not NAME_RE.fullmatch(name):
            raise GitSourceError("Unsafe GitHub repository name")
        return name

    def _run(self, argv: list[str], *, cwd: Path | None = None,
             timeout: int = 45) -> bytes:
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_LFS_SKIP_SMUDGE"] = "1"
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        try:
            proc = self.runner(argv, cwd=cwd, env=env, timeout=timeout,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitSourceError("Git transport unavailable or timed out") from exc
        if proc.returncode:
            message = proc.stderr.decode("utf-8", "replace").strip()
            if "not found" in message.lower() or "404" in message:
                raise GitSourceError("Public GitHub repository not found")
            raise GitSourceError("Git transport failed (git exit " +
                                 str(proc.returncode) + ")")
        return proc.stdout

    def _snapshot(self, repository: str, expected_sha: str | None = None) -> dict:
        name = self._name(repository)
        with self.lock:
            entry = self.cached.get(name)
            if entry is not None:
                if expected_sha is not None and entry["sha"] == expected_sha:
                    return entry
                if expected_sha is None and self.clock() - entry["at"] < self.ttl:
                    return entry
            self.root.mkdir(parents=True, exist_ok=True)
            temp = Path(tempfile.mkdtemp(prefix=".repo-", dir=self.root))
            checkout = temp / "checkout"
            try:
                # Public owner-only HTTPS URL assembled from a validated repo name.
                url = f"https://github.com/{ORG}/{name}.git"
                self._run(["git", "-c", "credential.helper=", "clone",
                           "--depth=1", "--single-branch", "--no-checkout",
                           "--quiet", url, str(checkout)], timeout=60)
                sha = self._run(["git", "rev-parse", "HEAD"],
                                cwd=checkout).decode("ascii").strip()
                branch = self._run(["git", "branch", "--show-current"],
                                   cwd=checkout).decode("utf-8").strip()
                if not SHA_RE.fullmatch(sha) or not branch:
                    raise GitSourceError("Invalid Git snapshot revision")
                entry = {"sha": sha, "branch": branch,
                         "path": checkout, "at": self.clock()}
                old = self.cached.get(name)
                self.cached[name] = entry
                if old is not None:
                    shutil.rmtree(old["path"].parent, ignore_errors=True)
                return entry
            except Exception:
                shutil.rmtree(temp, ignore_errors=True)
                raise

    def _at_revision(self, repository: str, commit: str) -> dict:
        if not isinstance(commit, str) or not SHA_RE.fullmatch(commit):
            raise GitSourceError("Invalid Git commit")
        entry = self._snapshot(repository, expected_sha=commit)
        if entry["sha"] != commit:
            raise GitSourceError("Git snapshot changed; refresh the preview")
        return entry

    def resolve_revision(self, repository: str) -> tuple[str, str]:
        entry = self._snapshot(repository)
        return entry["sha"], entry["branch"]

    def list_yaml(self, repository: str, folder: str, commit: str) -> list[dict]:
        """List top-level YAML in a canonical resource directory."""
        entry = self._at_revision(repository, commit)
        if (not folder or any(not part or part in (".", "..")
                              or not NAME_RE.fullmatch(part)
                              for part in folder.split("/"))):
            raise GitSourceError("Invalid resource directory")
        tree = self._run(["git", "ls-tree", "-r", "--name-only", commit,
                          "--", folder + "/"], cwd=entry["path"])
        prefix = folder + "/"
        found = []
        for path in tree.decode("utf-8", "strict").splitlines():
            if not path.startswith(prefix):
                continue
            filename = path[len(prefix):]
            if "/" in filename or not filename.endswith(".yaml"):
                continue
            if not NAME_RE.fullmatch(filename):
                raise GitSourceError("Unsafe YAML filename in Git repository")
            found.append({"name": filename, "path": path, "type": "file"})
        return found

    def list_views(self, repository: str, product_path: str,
                   commit: str) -> list[dict]:
        if safe_product_path(product_path, "invalid_product") != product_path:
            raise GitSourceError("Invalid product directory")
        entry = self._at_revision(repository, commit)
        folder = ("dashboards/ru" if product_path == "."
                  else product_path + "/dashboards/ru")
        tree = self._run(["git", "ls-tree", "-r", "--name-only", commit,
                          "--", folder + "/"], cwd=entry["path"])
        prefix = folder + "/"
        found = []
        for path in tree.decode("utf-8", "strict").splitlines():
            if not path.startswith(prefix):
                continue
            filename = path[len(prefix):]
            if "/" in filename or not filename.endswith(".yaml"):
                continue
            if not NAME_RE.fullmatch(filename):
                raise GitSourceError("Unsafe YAML filename in Git repository")
            found.append({"name": filename, "path": path, "type": "file"})
        return found

    def read_view(self, repository: str, path: str, commit: str) -> bytes:
        segments = path.split("/") if isinstance(path, str) else []
        if (not path or not path.endswith(".yaml")
                or any(not part or part in (".", "..")
                       or "\\" in part or "%" in part for part in segments)):
            raise GitSourceError("Unsafe canonical view path")
        entry = self._at_revision(repository, commit)
        # A local git blob read; never an extra outbound GitHub request.
        return self._run(["git", "show", commit + ":" + path],
                         cwd=entry["path"], timeout=15)


BACKEND = GitSnapshots()
resolve_revision = BACKEND.resolve_revision
list_views = BACKEND.list_views
list_yaml = BACKEND.list_yaml
read_view = BACKEND.read_view
