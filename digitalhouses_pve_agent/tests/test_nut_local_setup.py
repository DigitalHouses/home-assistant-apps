"""Read-only/isolated tests for NUT listener reconciliation at install time."""
import ipaddress
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.nut_local_setup import configure, management_ip, reconcile_nut_listener


def fixture(tmp_path):
    nut = tmp_path / 'nut'
    nut.mkdir()
    (nut / 'nut.conf').write_text('MODE=netserver\n')
    (nut / 'upsmon.conf').write_text('MONITOR ups@127.0.0.1 1 user secret primary\n')
    (nut / 'upsd.conf').write_text('LISTEN 127.0.0.1 3493\nLISTEN 192.168.11.30 3493\n')
    state = tmp_path / 'state'
    state.mkdir()
    (state / 'ups_selection.json').write_text(json.dumps({'selected_name':'ups'}))
    prepared = tmp_path / 'prepared.ini'
    prepared.write_text('[mqtt]\nhost=broker\n[ups]\nenabled=true\nname=ups\nhost=192.168.11.222\nport=3493\n')
    return nut, state, prepared


def fake_runner(calls, *, ups='OL', restart_fail=False):
    def run(cmd, **kw):
        calls.append(cmd)
        if cmd[0] == 'upsc':
            return SimpleNamespace(stdout=ups+'\n')
        if cmd == ['ip', '-4', '-o', 'addr', 'show', 'dev', 'vmbr0']:
            return SimpleNamespace(stdout='5: vmbr0 inet 192.168.11.220/24 scope global vmbr0\n')
        if cmd == ['ip', '-4', '-o', 'addr', 'show']:
            return SimpleNamespace(stdout='5: vmbr0 inet 192.168.11.220/24 scope global vmbr0\n')
        if cmd[0] == 'systemctl':
            if restart_fail:
                raise subprocess.CalledProcessError(1, cmd)
            return SimpleNamespace(stdout='')
        raise AssertionError(cmd)
    return run


def test_rehomes_local_nut_and_replaces_old_pve_listener(tmp_path):
    nut, state, prepared = fixture(tmp_path)
    calls=[]
    with patch('app.nut_local_setup.guard_restart') as guard:
        configure(prepared, state, nut_dir=nut, run=fake_runner(calls))
        guard.assert_called_once()
    contents=(nut/'upsd.conf').read_text()
    assert 'LISTEN 127.0.0.1 3493' in contents
    assert 'LISTEN 192.168.11.220 3493' in contents
    assert '192.168.11.30' not in contents
    assert len(list(nut.glob('upsd.conf.dh-pre-ip-*'))) == 1
    assert next(nut.glob('upsd.conf.dh-pre-ip-*')).read_text().endswith('LISTEN 192.168.11.30 3493\n')
    assert 'host=127.0.0.1' in prepared.read_text() or 'host = 127.0.0.1' in prepared.read_text()
    assert sum(cmd[0]=='systemctl' for cmd in calls)==1


def test_idempotent_no_nut_restart_if_current(tmp_path):
    nut, state, prepared = fixture(tmp_path)
    (nut/'upsd.conf').write_text('LISTEN 127.0.0.1 3493\nLISTEN 192.168.11.220 3493\n')
    calls=[]
    with patch('app.nut_local_setup.guard_restart'):
        configure(prepared, state, nut_dir=nut, run=fake_runner(calls))
    assert not any(cmd[0]=='systemctl' for cmd in calls)


def test_remote_only_nut_preserves_existing_config(tmp_path):
    nut, state, prepared = fixture(tmp_path)
    before = prepared.read_text()
    def unavailable(cmd, **kw):
        raise subprocess.CalledProcessError(1,cmd)
    with patch('app.nut_local_setup.guard_restart') as guard:
        configure(prepared,state,nut_dir=nut,run=unavailable)
        guard.assert_not_called()
    assert prepared.read_text()==before
    assert (nut/'upsd.conf').read_text().endswith('192.168.11.30 3493\n')


def test_no_netserver_change_other_subnet_or_multiple_listeners(tmp_path):
    nut, state, prepared = fixture(tmp_path)
    run = fake_runner([])
    pve_ip = management_ip(run=run)
    assert str(pve_ip.ip)=='192.168.11.220'
    (nut/'upsd.conf').write_text('LISTEN 127.0.0.1 3493\nLISTEN 10.0.0.30 3493\n')
    assert not reconcile_nut_listener(nut_dir=nut,pve_ip=pve_ip,selected='ups',run=run)
    (nut/'upsd.conf').write_text('LISTEN 127.0.0.1 3493\nLISTEN 192.168.11.30 3493\nLISTEN 192.168.11.31 3493\n')
    assert not reconcile_nut_listener(nut_dir=nut,pve_ip=pve_ip,selected='ups',run=run)


def test_unsafe_guard_prevents_nut_mutation(tmp_path):
    nut, state, prepared = fixture(tmp_path)
    old = (nut/'upsd.conf').read_text()
    with patch('app.nut_local_setup.guard_restart',side_effect=RuntimeError('battery power')):
        with pytest.raises(RuntimeError,match='battery power'):
            configure(prepared,state,nut_dir=nut,run=fake_runner([]))
    assert (nut/'upsd.conf').read_text()==old


def test_restart_failure_rolls_nut_configuration_back(tmp_path):
    nut, state, prepared = fixture(tmp_path)
    old=(nut/'upsd.conf').read_text()
    with pytest.raises(subprocess.CalledProcessError):
        reconcile_nut_listener(nut_dir=nut,pve_ip=ipaddress.IPv4Interface('192.168.11.220/24'),
                               selected='ups',run=fake_runner([],restart_fail=True))
    assert (nut/'upsd.conf').read_text()==old
