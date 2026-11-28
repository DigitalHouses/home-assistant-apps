"""Materialize/check a deterministic journal snapshot inside each build context."""
import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "shared/dh_journal/dh_journal"
TARGETS = [ROOT / "digitalhouses_system_globals_app/rootfs/app/dh_journal",
           ROOT / "digitalhouses-stats/digitalhouses_stats/dh_journal",
           ROOT / "digitalhouses_sync_app/rootfs/app/dh_journal"]
STATS_WEB = ROOT / "digitalhouses-stats/dashboard"
WEB_FILES = {"index.html": "log.html", "journal.css": "journal.css", "journal.js": "journal.js"}

def files(path):
    return {p.relative_to(path): p.read_bytes() for p in path.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
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
    for source, dest in WEB_FILES.items():
        content = (SOURCE / "web" / source).read_bytes()
        target = STATS_WEB / dest
        if args.check:
            if not target.is_file() or target.read_bytes() != content:
                raise SystemExit(f"DH Journal web asset differs: {target.relative_to(ROOT)}")
        else:
            target.write_bytes(content)
    print("DH Journal snapshots verified" if args.check else "DH Journal snapshots updated")

if __name__ == "__main__":
    main()
