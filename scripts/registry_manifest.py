"""Read GHCR manifests with authenticated HTTP status and exact content digest."""
import base64
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

ACCEPT = ", ".join(("application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json", "application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"))

def get_manifest(ref):
    match = re.fullmatch(r"ghcr.io/(digitalhouses/[a-z0-9_-]+):([a-zA-Z0-9_.-]+)", ref)
    if not match:
        raise ValueError("Invalid GHCR reference")
    repo, tag = match.groups()
    credentials = base64.b64encode((os.environ["GITHUB_ACTOR"] + ":" + os.environ["GH_TOKEN"]).encode()).decode()
    query = urllib.parse.urlencode({"service": "ghcr.io", "scope": f"repository:{repo}:pull"})
    request = urllib.request.Request("https://ghcr.io/token?" + query, headers={"Authorization": "Basic " + credentials})
    with urllib.request.urlopen(request, timeout=30) as response:
        token = json.load(response)["token"]
    request = urllib.request.Request(f"https://ghcr.io/v2/{repo}/manifests/{tag}", headers={"Authorization": "Bearer " + token, "Accept": ACCEPT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            digest = "sha256:" + hashlib.sha256(body).hexdigest()
            if response.headers.get("Docker-Content-Digest") != digest:
                raise ValueError("Registry digest differs from exact response bytes")
            return digest, body
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise

def main():
    ref, mode = sys.argv[1:]
    result = get_manifest(ref)
    if mode == "absent":
        if result is not None:
            raise SystemExit("Immutable tag already exists: " + ref)
        return
    if result is None:
        raise SystemExit("Manifest not found: " + ref)
    digest, body = result
    if mode == "digest":
        print(digest)
    elif mode == "raw":
        sys.stdout.buffer.write(body)
    else:
        raise ValueError("Invalid mode")

if __name__ == "__main__":
    main()
