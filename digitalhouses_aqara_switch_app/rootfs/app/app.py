"""Inert initial project scaffold; does not subscribe, scan, or control devices."""

import os


def main() -> int:
    version = os.environ.get("APP_VERSION")
    if not version:
        raise RuntimeError("APP_VERSION must be set by the image")
    print(
        f"DigitalHouses Aqara Switch App v{version}: "
        "scaffold only; no scan or device control implemented.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
