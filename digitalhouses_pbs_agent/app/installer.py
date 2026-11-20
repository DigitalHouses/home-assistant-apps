"""Validate unattended installer settings with the native CLI/INI schema."""
from __future__ import annotations

import argparse
from pathlib import Path

from .cli import change_config
from .config import load_config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--set", dest="changes", action="append", default=[])
    args = parser.parse_args()
    if args.changes:
        print(change_config(args.config, args.changes, restart=False))
    load_config(args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
