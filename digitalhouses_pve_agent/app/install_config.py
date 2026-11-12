"""Installer preparation using the same native editor/validator as the CLI."""
from __future__ import annotations

import configparser
import fcntl
import getpass
import hashlib
import warnings
import os
from pathlib import Path
import sys

from .cli import KEYS, SECRETS, CliError, _atomic_write, _validate, set_config


def prepare(path: Path, pairs: list[str], *, non_interactive: bool) -> None:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding='utf-8')
    host = parser.get('mqtt', 'host', fallback='').strip()
    supplied = set()
    for pair in pairs:
        key, sep, value = pair.partition('=')
        target = KEYS.get(key)
        supplied.add(target)
        if non_interactive and target in SECRETS and not sep:
            raise CliError('non-interactive secrets require stdin sentinel key=-')
        if target == ('mqtt', 'host') and sep:
            host = value.strip()
    hidden_values: dict[tuple[str, str], str] = {}
    if not host:
        if non_interactive:
            raise CliError('mqtt.host is required for non-interactive installation')
        # The stdin stream belongs to secret automation flags. Interactive
        # questions use the controlling terminal, never consume those lines.
        try:
            with open('/dev/tty', 'r+') as tty:
                def prompt(label):
                    tty.write(label)
                    tty.flush()
                    answer = tty.readline()
                    if not answer:
                        raise CliError('terminal input ended')
                    return answer.rstrip('\r\n')
                if ('mqtt', 'host') in supplied:
                    raise CliError('mqtt.host must not be empty')
                pairs = list(pairs) + ['mqtt_host=' + prompt('MQTT host: ')]
                if ('mqtt', 'port') not in supplied:
                    pairs.append('mqtt_port=' + (prompt('MQTT port [1883]: ') or '1883'))
                if ('mqtt', 'username') not in supplied:
                    pairs.append('mqtt_username=' + prompt('MQTT username [optional]: '))
                if ('mqtt', 'password') not in supplied:
                    try:
                        with warnings.catch_warnings():
                            warnings.simplefilter('error', getpass.GetPassWarning)
                            secret = getpass.getpass('MQTT password [optional]: ', stream=tty)
                    except (getpass.GetPassWarning, EOFError) as exc:
                        raise CliError('unable to read hidden MQTT password from terminal') from exc
                    hidden_values[('mqtt', 'password')] = secret
                    pairs.append('mqtt_password')
                tty.write('Confirm MQTT settings (password hidden)? [y/N]: ')
                tty.flush()
                if tty.readline().strip().lower() not in ('y', 'yes'):
                    raise CliError('MQTT configuration was not confirmed')
        except OSError as exc:
            raise CliError('MQTT host required; supply --set mqtt_host=HOST with --non-interactive') from exc
    if pairs:
        set_config(path, pairs, prepare=True, hidden_values=hidden_values)
    else:
        _validate(path)


def commit(prepared: Path, target: Path, expected_sha256: str | None = None) -> None:
    _validate(prepared)
    fd = os.open(target.with_name(target.name + '.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if target.is_symlink():
            raise CliError('refusing symlink configuration')
        if expected_sha256 is not None:
            if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != expected_sha256:
                raise CliError('native configuration changed during installation; refusing to overwrite')
        content = prepared.read_bytes()
        if target.exists() and target.read_bytes() == content:
            return
        metadata = target.stat() if target.exists() else prepared.stat()
        _atomic_write(target, content, metadata)


def main() -> int:
    try:
        if os.geteuid() != 0:
            raise CliError('installer configuration requires root')
        args = sys.argv[1:]
        if len(args) in (3, 4) and args[0] == '--commit':
            commit(Path(args[1]), Path(args[2]), args[3] if len(args) == 4 and args[3] != '-' else None)
        else:
            path = Path(args.pop(0))
            non_interactive = bool(args and args[0] == '--non-interactive')
            if non_interactive:
                args.pop(0)
            prepare(path, args, non_interactive=non_interactive)
        return 0
    except (ValueError, OSError, IndexError, configparser.Error):
        # ConfigParser errors may contain entire source lines including secrets.
        print('ERROR: native configuration preflight failed; check required mqtt.host and key constraints', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
