"""Materialize/check a deterministic journal snapshot inside each build context."""
import argparse
import hashlib
import json
import subprocess
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "shared/dh_journal/dh_journal"
TARGETS = [ROOT / "digitalhouses_system_globals_app/rootfs/app/dh_journal"]
SYNC_PACKAGE = ROOT / "digitalhouses_sync_app/rootfs/app/dh_journal"
SYNC_LOCK = ROOT / "digitalhouses_sync_app/dh-journal.lock.json"
STATS_WEB = ROOT / "digitalhouses-stats/dashboard"
STATS_PACKAGE = ROOT / "digitalhouses-stats/digitalhouses_stats/dh_journal"
STATS_LOCK = ROOT / "digitalhouses-stats/dh-journal.lock.json"
WEB_FILES = {"index.html": "log.html", "journal.css": "journal.css", "journal.js": "journal.js",
             "toast.js": "toast.js", "toast.css": "toast.css"}

def files(path):
    return {p.relative_to(path): p.read_bytes() for p in path.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--stats-source", type=Path, help="Local checkout of the pinned external library release")
    parser.add_argument("--sync-source", type=Path, help="Local checkout of the pinned external Sync library release")
    args = parser.parse_args()
    if args.check:
        version = re.search(r'^VERSION = "([^"]+)"$', (SOURCE / "__init__.py").read_text(), re.M).group(1)
        title = (ROOT / "docs/standards/DH_JOURNAL_STANDARD.md").read_text().splitlines()[0]
        if title != "# DH Journal Standard " + version:
            raise SystemExit("DH Journal standard version differs from library")
    for target in TARGETS:
        if args.check:
            if files(target) != files(SOURCE):
                raise SystemExit(f"DH Journal snapshot differs: {target.relative_to(ROOT)}")
        else:
            target.mkdir(parents=True, exist_ok=True)
            for path in set(files(target)) - set(files(SOURCE)):
                (target / path).unlink()
            for path, content in files(SOURCE).items():
                dest = target / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
    for package, lock_path, source_checkout in ((STATS_PACKAGE, STATS_LOCK, args.stats_source),
                                                (SYNC_PACKAGE, SYNC_LOCK, args.sync_source)):
        lock = json.loads(lock_path.read_text())
        if source_checkout:
            checkout = source_checkout.resolve()
            commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
            if commit != lock["commit"]:
                raise SystemExit(f"Journal source commit differs from lock: {lock_path}")
            external = files(checkout / "dh_journal/dh_journal")
            if {str(p): hashlib.sha256(data).hexdigest() for p, data in external.items()} != lock["files"]:
                raise SystemExit(f"Journal source differs from lock: {lock_path}")
            if not args.check:
                for path in set(files(package)) - set(external):
                    (package / path).unlink()
                for path, content in external.items():
                    dest = package / path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(content)
        actual = files(package)
        if {str(p): hashlib.sha256(data).hexdigest() for p, data in actual.items()} != lock["files"]:
            raise SystemExit(f"Journal snapshot differs from pinned release: {lock_path}")
    for source, dest in WEB_FILES.items():
        content = (STATS_PACKAGE / "web" / source).read_bytes()
        target = STATS_WEB / dest
        if args.check:
            if not target.is_file() or target.read_bytes() != content:
                raise SystemExit(f"DH Journal web asset differs: {target.relative_to(ROOT)}")
        else:
            target.write_bytes(content)
    print("DH Journal snapshots verified" if args.check else "DH Journal snapshots updated")

if __name__ == "__main__":
    main()
