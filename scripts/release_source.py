"""Resolve a product's immutable release source and verify OCI provenance."""
import json
import re
import subprocess
import sys

def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()

def version_at(commit, product):
    config = git("show", f"{commit}:{product}/config.yaml")
    matches = re.findall(r"^version:\s*['\"]?([^'\"\s#]+)", config, re.M)
    if len(matches) != 1:
        raise ValueError("Invalid config version")
    return matches[0]

def source_for(product, version, head):
    if not re.fullmatch(r"[a-z0-9_-]+", product) or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("Invalid release identity")
    if version_at(head, product) != version:
        raise ValueError("Release version mismatch")
    # Only commits on main's first-parent history can introduce a release.
    source = head
    for commit in git("log", "--first-parent", "--format=%H", head, "--", f"{product}/config.yaml").splitlines():
        try:
            commit_version = version_at(commit, product)
        except subprocess.CalledProcessError:
            raise ValueError("Cannot resolve product history")
        if commit_version != version:
            break
        source = commit
    # No adoption if the actual Docker build context changed after the version bump.
    if git("rev-parse", f"{source}:{product}") != git("rev-parse", f"{head}:{product}"):
        raise ValueError("Product changed without version bump; refusing mixed release source")
    return source

def validate_manifest(doc, source, version, platform, digests=None):
    annotations = doc.get("annotations", {})
    if annotations.get("org.opencontainers.image.revision") != source or annotations.get("org.opencontainers.image.version") != version:
        raise ValueError("Immutable architecture tag exists without matching provenance")
    descriptors = doc.get("manifests", [])
    platforms = [(d.get("platform", {}).get("os"), d.get("platform", {}).get("architecture")) for d in descriptors if d.get("platform", {}).get("os") != "unknown"]
    if platform == "final":
        if annotations.get("org.digitalhouses.source-digests") != digests:
            raise ValueError("Final index source digest mismatch")
        if not platforms or len(platforms) != len(set(platforms)) or any(p not in [("linux", "amd64"), ("linux", "arm64")] for p in platforms):
            raise ValueError("Invalid final index platforms")
    elif platforms != [tuple(platform.split("/"))]:
        raise ValueError("Architecture index platform mismatch")

def main():
    product, version, head, *extra = sys.argv[1:]
    source = source_for(product, version, head)
    if not extra:
        print(source)
        return
    expected, platform, *digests = extra
    if expected != source:
        raise ValueError("Source mismatch")
    validate_manifest(json.load(sys.stdin), source, version, platform, digests[0] if digests else None)

if __name__ == "__main__":
    main()
