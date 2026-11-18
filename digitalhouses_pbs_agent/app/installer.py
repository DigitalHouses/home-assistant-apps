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
    config = load_config(args.config)
    if not config.pbs_token_id:
        raise ValueError("pbs_token_id is required")
    # Validate that a configured token secret exists without reading it into logs.
    if not config.pbs_token_secret_file.is_file():
        raise ValueError("pbs_token_secret_file does not exist")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
