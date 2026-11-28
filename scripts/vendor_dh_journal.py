"""Materialize/check a deterministic journal snapshot inside each build context."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "shared/dh_journal/dh_journal"
TARGETS = [ROOT / "digitalhouses_system_globals_app/rootfs/app/dh_journal"]

def files(path):
    return {p.relative_to(path): p.read_bytes() for p in path.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
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
    print("DH Journal snapshots verified" if args.check else "DH Journal snapshots updated")

if __name__ == "__main__":
    main()
