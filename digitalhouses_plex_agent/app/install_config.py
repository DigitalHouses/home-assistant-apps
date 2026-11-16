"""Stage and commit Plex Agent native INI using the same validator as CLI set.

First-install automation uses the existing key aliases and never adds an
installer-specific configuration namespace. Secrets arrive only via stdin.
"""
from __future__ import annotations

import configparser
import fcntl
import getpass
import hashlib
import os
from pathlib import Path
import sys
import warnings

from .cli import KEYS, CliError, _atomic_write, _validate, set_config


def prepare(path: Path, pairs: list[str], *, non_interactive: bool) -> None:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8")
    host = parser.get("mqtt", "host", fallback="").strip()
    supplied: set[tuple[str, str]] = set()
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if key not in KEYS:
            raise CliError("unknown configuration key (see dh-plex-agent help)")
        target = KEYS[key]
        supplied.add(target)
        if target == ("mqtt", "host") and sep:
            host = value.strip()

    if not host:
        if non_interactive:
            raise CliError("mqtt.host is required for non-interactive installation")
        try:
            with open("/dev/tty", "r+") as tty:
                def ask(prompt: str) -> str:
                    tty.write(prompt)
                    tty.flush()
                    response = tty.readline()
                    if not response:
                        raise CliError("terminal input ended")
                    return response.rstrip("\r\n")

                if ("mqtt", "host") in supplied:
                    raise CliError("mqtt.host must not be empty")
                pairs = list(pairs) + ["mqtt_host=" + ask("MQTT host: ")]
                if ("mqtt", "port") not in supplied:
                    pairs.append("mqtt_port=" + (ask("MQTT port [1883]: ") or "1883"))
                if ("mqtt", "username") not in supplied:
                    pairs.append("mqtt_username=" + ask("MQTT username [optional]: "))
                if ("mqtt", "password") not in supplied:
                    try:
                        with warnings.catch_warnings():
                            warnings.simplefilter("error", getpass.GetPassWarning)
                            secret = getpass.getpass("MQTT password [optional]: ", stream=tty)
                    except (getpass.GetPassWarning, EOFError) as exc:
                        raise CliError("cannot securely read MQTT password") from exc
                    # Don't put the password into arguments or config logs.
                    # The existing native editor reads the one-line stdin sentinel.
                    from io import StringIO
                    old_stdin = sys.stdin
                    try:
                        sys.stdin = StringIO(secret + "\n")
                        pairs.append("mqtt_password=-")
                        if ask("Confirm MQTT settings (password hidden)? [y/N]: ").lower() not in ("y", "yes"):
                            raise CliError("MQTT configuration was not confirmed")
                        set_config(path, pairs, prepare=True)
                    finally:
                        sys.stdin = old_stdin
                    return
                if ask("Confirm MQTT settings? [y/N]: ").lower() not in ("y", "yes"):
                    raise CliError("MQTT configuration was not confirmed")
        except OSError as exc:
            raise CliError("mqtt.host is required; pass --set mqtt_ip=HOST --non-interactive") from exc

    if pairs:
        set_config(path, pairs, prepare=True)
    else:
        _validate(path)


def commit(prepared: Path, target: Path, expected_sha256: str | None) -> None:
    _validate(prepared)
    fd = os.open(target.with_name(target.name + ".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if target.is_symlink():
            raise CliError("refusing symlink configuration")
        if expected_sha256 is not None:
            if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != expected_sha256:
                raise CliError("native configuration changed during installation; refusing to overwrite")
        proposed = prepared.read_bytes()
        if target.exists() and target.read_bytes() == proposed:
            return
        metadata = target.stat() if target.exists() else prepared.stat()
        _atomic_write(target, proposed, metadata)


def main() -> int:
    try:
        if os.geteuid() != 0:
            raise CliError("installer configuration requires root")
        argv = sys.argv[1:]
        if len(argv) in (3, 4) and argv[0] == "--commit":
            commit(Path(argv[1]), Path(argv[2]), None if len(argv) == 3 or argv[3] == "-" else argv[3])
        else:
            if not argv:
                raise CliError("missing prepared INI file")
            path = Path(argv.pop(0))
            non_interactive = bool(argv and argv[0] == "--non-interactive")
            if non_interactive:
                argv.pop(0)
            prepare(path, argv, non_interactive=non_interactive)
        return 0
    except (CliError, RuntimeError, ValueError, OSError, IndexError, configparser.Error):
        # Avoid echoing user-supplied INI lines; they may contain credentials.
        print("ERROR: native configuration preflight/commit failed; check MQTT host and configuration constraints", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
