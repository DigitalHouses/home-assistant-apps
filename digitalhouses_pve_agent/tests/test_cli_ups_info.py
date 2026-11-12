"""UPS CLI topology from local config and already-cached NUT data only."""
import contextlib
import io
from pathlib import Path
from unittest.mock import patch

from app import cli
from app.config import load_config
from app.runtime_status import FIELDS


def test_snmp_device_ip_and_selected_nut_name_without_credentials(tmp_path):
    config = tmp_path/'agent.conf'
    config.write_text('[mqtt]\nhost=broker\n[ups]\nenabled=true\nhost=127.0.0.1\nname=stale\n')
    nut = tmp_path/'ups.conf'
    nut.write_text('[ups]\ndriver = snmp-ups\nport = 192.168.11.10\nsnmp_version = v1\ncommunity = SECRET-COMMUNITY\n')
    selection = tmp_path/'selection.json'
    selection.write_text('{"selected_name":"ups"}')
    target, link = cli.ups_connection_details(load_config(config), nut_path=nut, selection_path=selection)
    assert target == 'ups@127.0.0.1:3493'
    assert link == 'SNMP v1 -> 192.168.11.10 (configured)'
    assert 'SECRET' not in link


def test_remote_nut_and_unsupported_or_invalid_local_driver(tmp_path):
    config = tmp_path/'agent.conf'
    config.write_text('[mqtt]\nhost=broker\n[ups]\nenabled=true\nhost=192.168.11.222\n')
    nut = tmp_path/'ups.conf'
    nut.write_text('[ups]\ndriver=snmp-ups\nport=192.168.11.10\ncommunity = SECRET\n')
    target, link = cli.ups_connection_details(load_config(config), nut_path=nut,
                                               selection_path=tmp_path/'missing')
    assert target == 'ups@192.168.11.222:3493'
    assert link is None

    config.write_text('[mqtt]\nhost=broker\n[ups]\nenabled=true\nhost=127.0.0.1\n')
    nut.write_text('[ups]\ndriver = snmp-ups\nport = auto\ncommunity = SECRET\n')
    _, link = cli.ups_connection_details(load_config(config), nut_path=nut,
                                         selection_path=tmp_path/'missing')
    assert link is None


def test_cached_identity_appears_and_no_raw_ups_or_serial_in_runtime():
    assert {'manufacturer','model','driver_name','status_raw','load_percent'} <= set(FIELDS['ups'])
    assert {'raw','serial','command_password','community'}.isdisjoint(FIELDS['ups'])


def test_cli_outputs_topology_model_and_load_without_nut_queries(tmp_path):
    conf = tmp_path/'agent.conf'
    conf.write_text('[mqtt]\nhost=broker\n[ups]\nenabled=true\nhost=127.0.0.1\n')
    cached = {
        'primary_status':'online','status_raw':'OL','manufacturer':'CPS',
        'model':'PR1500ELCD','battery_charge_percent':100,
        'runtime_seconds':3900,'load_percent':18,
    }
    runtime = {'samples': {'ups': {'available':True, 'last_success':'now', 'data':cached}},
               'ups_configured':True}
    with patch.object(cli, 'service_info', return_value={'ActiveState':'active'}), \
         patch('app.runtime_status.read_status', return_value=(runtime,True)), \
         patch('app.runtime_status.sample_live', side_effect=lambda section,value:section=='ups'), \
         patch('app.runtime_status.host_identity', return_value={'hostname':'pve','ip':'192.168.11.220'}), \
         patch.object(cli,'ups_connection_details',return_value=('ups@127.0.0.1:3493','SNMP v1 -> 192.168.11.10 (configured)')), \
         patch('app.runtime_status.load_build_info', return_value=type('B',(),{'version':'0.5.86','commit':'test'})()), \
         contextlib.redirect_stdout(io.StringIO()) as out:
        cli.print_status(conf)
    result=out.getvalue()
    for expected in ('NUT:       ups@127.0.0.1:3493',
                     'SNMP v1 -> 192.168.11.10 (configured)',
                     'Device:    CPS PR1500ELCD',
                     'Status:    online (OL)',
                     'Battery:   100% | runtime 65 min',
                     'Load:      18%'):
        assert expected in result
    assert 'SECRET' not in result
