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
            # A deletion of the version file marks the boundary of its lifetime.
            if not git("ls-tree", commit, "--", f"{product}/config.yaml"):
                break
            raise
        if commit_version != version:
            break
        source = commit
    # No adoption if the actual Docker build context changed after the version bump.
    if git("rev-parse", f"{source}:{product}") != git("rev-parse", f"{head}:{product}"):
        raise ValueError("Product changed without version bump; refusing mixed release source")
    return source

def validate_manifest(doc, source, version, platform, digests=None, child_digests=None):
    annotations = doc.get("annotations", {})
    if annotations.get("org.opencontainers.image.revision") != source or annotations.get("org.opencontainers.image.version") != version:
        raise ValueError("Immutable architecture tag exists without matching provenance")
    descriptors = doc.get("manifests", [])
    platforms = [(d.get("platform", {}).get("os"), d.get("platform", {}).get("architecture")) for d in descriptors if d.get("platform", {}).get("os") != "unknown"]
    if platform == "final":
        expected = digests.split(",") if digests else []
        if len(expected) != 2 or any(not re.fullmatch(r"sha256:[0-9a-f]{64}", digest) for digest in expected):
            raise ValueError("Invalid final source digests")
        if annotations.get("org.digitalhouses.source-digests") != digests:
            raise ValueError("Final index source digest mismatch")
        actual = [d for d in descriptors if d.get("platform", {}).get("os") != "unknown"]
        expected_platforms = [("linux", "amd64"), ("linux", "arm64")]
        if len(actual) != len(expected) or len(set(platforms)) != len(expected) or platforms != expected_platforms:
            raise ValueError("Invalid final index platforms")
        # Buildx flattens architecture indexes into image manifests when composing
        # a multi-platform index. Index digests in provenance therefore differ
        # from the child image manifest digests in the final index.
        children = child_digests.split(",") if child_digests else []
        if len(children) != len(expected) or any(not re.fullmatch(r"sha256:[0-9a-f]{64}", d) for d in children):
            raise ValueError("Invalid expected architecture manifest digests")
        if [d.get("digest") for d in actual] != children:
            raise ValueError("Final index child digest mismatch")
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
    validate_manifest(json.load(sys.stdin), source, version, platform,
                      digests[0] if digests else None,
                      digests[1] if len(digests) > 1 else None)

if __name__ == "__main__":
    main()
