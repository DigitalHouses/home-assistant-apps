#!/usr/bin/env python3
"""Create a native runner matrix from validated release candidates."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNERS = {"amd64": "ubuntu-latest", "aarch64": "ubuntu-24.04-arm"}


def build_matrix(root, candidates):
    registry = json.loads((root / "digitalhouses-stats/digitalhouses_stats/product_registry.json").read_text())
    products = {p["id"]: p for p in registry["products"]}
    jobs = []
    seen = set()
    for candidate in candidates:
        product, version = candidate["product"], candidate["version"]
        if product in seen:
            raise ValueError(f"Duplicate candidate: {product}")
        seen.add(product)
        if products[product]["type"] != "app":
            continue
        lines = (root / product / "config.yaml").read_text().splitlines()
        arches = []
        active = False
        for line in lines:
            if re.fullmatch(r"arch:\s*", line):
                active = True
                continue
            if active and line and not line[0].isspace():
                break
            if active:
                match = re.fullmatch(r"\s+-\s+([^\s#]+)\s*(?:#.*)?", line)
                if match:
                    arches.append(match.group(1))
        if not arches or len(set(arches)) != len(arches):
            raise ValueError(f"Invalid architecture list: {product}")
        for arch in arches:
            jobs.append(dict(product=product, version=version, arch=arch, runner=RUNNERS[arch]))
    return {"include": jobs}


if __name__ == "__main__":
    candidates = json.loads(Path(sys.argv[1]).read_text())
    print("matrix=" + json.dumps(build_matrix(ROOT, candidates), separators=(",", ":")))
