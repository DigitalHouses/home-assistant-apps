"""Offline dh-pve-agent update reuses the published-release update worker."""
import contextlib
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import cli
from app.state_store import StateStore


def test_no_new_release_is_idempotent(tmp_path):
    app=tmp_path/'app'
    app.mkdir()
    (app/'VERSION').write_text('0.5.85\n')
    with patch.object(cli,'service_info',return_value={'ActiveState':'active'}), \
         patch('app.update_manager.latest_release',return_value=('digitalhouses_pve_agent-v0.5.85','0.5.85')), \
         patch.object(cli.subprocess,'run',side_effect=AssertionError('no systemctl for current release')):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cli.update_agent(state_dir=tmp_path/'state',app_dir=app)
    assert 'UP_TO_DATE 0.5.85' in out.getvalue()


def test_offline_update_uses_existing_transactional_worker(tmp_path):
    app=tmp_path/'app'
    app.mkdir()
    (app/'VERSION').write_text('0.5.84\n')
    state=tmp_path/'state'
    calls=[]
    def fake_run(cmd,**kw):
        calls.append(cmd)
        if cmd[1]=='is-active':
            return SimpleNamespace(returncode=3)
        if cmd[1]=='start':
            request=StateStore(state/'update_request.json').load()
            assert request['tag']=='digitalhouses_pve_agent-v0.5.85'
            (app/'VERSION').write_text('0.5.85\n')
            StateStore(state/'update_worker.json').save({'state':'completed'})
            return SimpleNamespace(returncode=0)
        raise AssertionError(cmd)
    with patch.object(cli,'service_info',return_value={'ActiveState':'active'}), \
         patch('app.update_manager.latest_release',return_value=('digitalhouses_pve_agent-v0.5.85','0.5.85')), \
         patch.object(cli.subprocess,'run',side_effect=fake_run):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cli.update_agent(state_dir=state,app_dir=app)
    assert calls == [
        ['systemctl','is-active','--quiet','digitalhouses_pve_agent-update.service'],
        ['systemctl','start','digitalhouses_pve_agent-update.service'],
    ]
    assert 'UPDATED 0.5.85' in out.getvalue()


def test_busy_and_failed_worker_are_rejected(tmp_path):
    app=tmp_path/'app'
    app.mkdir()
    (app/'VERSION').write_text('0.5.84\n')
    state=tmp_path/'state'
    StateStore(state/'update_worker.json').save({'state':'queued'})
    with patch.object(cli,'service_info',return_value={'ActiveState':'active'}), \
         patch('app.update_manager.latest_release',return_value=('digitalhouses_pve_agent-v0.5.85','0.5.85')), \
         patch.object(cli.subprocess,'run',return_value=SimpleNamespace(returncode=3)):
        with pytest.raises(cli.CliError,match='still pending'):
            cli.update_agent(state_dir=state,app_dir=app)

    StateStore(state/'update_worker.json').save({'state':'idle'})
    def failed(cmd,**kw):
        if cmd[1]=='start':
            StateStore(state/'update_worker.json').save({'state':'error','error':'simulated'})
            return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=3)
    with patch.object(cli,'service_info',return_value={'ActiveState':'active'}), \
         patch('app.update_manager.latest_release',return_value=('digitalhouses_pve_agent-v0.5.85','0.5.85')), \
         patch.object(cli.subprocess,'run',side_effect=failed):
        with pytest.raises(RuntimeError,match='rolled back'):
            cli.update_agent(state_dir=state,app_dir=app)


def test_cli_routes_update_command_without_mqtt():
    with patch.object(cli.os,'geteuid',return_value=0), patch.object(cli,'update_agent') as update:
        assert cli.main(['update']) == 0
        update.assert_called_once_with()
