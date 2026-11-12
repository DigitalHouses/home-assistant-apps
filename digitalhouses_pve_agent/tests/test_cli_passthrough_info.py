"""Read-only owner labels for GPU and physical guest/host disks."""
import contextlib
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import cli
from app.runtime_status import FIELDS


def test_runtime_fields_whitelist_pci_ownership_without_raw_guest_inventory():
    assert {'pci_address', 'source_id', 'source_type', 'connection'} <= set(FIELDS['gpu'])
    assert {'passthrough_pci_address', 'passthrough_hostpci', 'source_guest_id'} <= set(FIELDS['disk_temperature'])
    assert 'serial' not in FIELDS['gpu']
    assert 'serial' not in FIELDS['disk_temperature']


def test_disk_pci_requires_verified_single_address():
    pci = {'source_type': 'guest', 'source_guest_id': '2223',
           'passthrough_pci_address': '0000:00:17.0',
           'passthrough_hostpci': 'hostpci0'}
    assert cli.disk_vm_passthrough(pci, {}) == 'PCI Passthrough (controller) | 0000:00:17.0 | VM 2223'
    pci.pop('passthrough_pci_address')
    assert 'address unresolved' in cli.disk_vm_passthrough(pci, {})
    pci['source_guest_id'] = 'bad'
    assert cli.disk_vm_passthrough(pci, {}) is None


def test_disk_byid_config_mapping_and_ambiguous_owner(tmp_path):
    pve = tmp_path/'qemu-server'
    pve.mkdir()
    block=tmp_path/'sdg'
    block.write_text('fixture')
    # Preserve the actual /dev path contract without modifying the host's /dev.
    byid='/dev/disk/by-id/ata-EXAMPLE-850'
    original=Path.resolve
    def resolve(path, strict=False):
        if str(path)==byid:
            return block
        return original(path, strict=strict)
    (pve/'2223.conf').write_text('name: vm\nscsi0: '+byid+',size=1000G\n')
    with patch.object(Path, 'resolve', resolve):
        direct=cli.physical_disk_vm_assignments(pve)
        assert direct=={str(block):('2223',byid)}
        assert cli.disk_vm_passthrough({'source_type':'host','device_path':byid},direct)==(
            'Disk Passthrough | '+byid+' | VM 2223'
        )
        (pve/'2250.conf').write_text('scsi0: '+byid+'\n')
        assert cli.physical_disk_vm_assignments(pve)=={}


def test_cli_uses_cache_for_gpu_and_disk_owner(tmp_path):
    config=tmp_path/'agent.conf'
    config.write_text('[mqtt]\nhost=broker\n')
    disk={'model':'Samsung SSD 850 EVO 1TB','temperature_c':43,
          'available':True,'fresh':True,'source_type':'guest',
          'source_guest_id':'2223','passthrough_hostpci':'hostpci0',
          'passthrough_pci_address':'0000:00:17.0'}
    gpu={'model':'Intel Corporation Alder Lake-N [UHD Graphics]',
         'connection':'passthrough_pci', 'source_type':'vm',
         'source_id':'2223', 'pci_address':'0000:00:02.0','temperature_c':None}
    cached={'samples':{
        'gpu':{'available':True,'data':{'pci_0000_00_02_0':gpu}},
        'disk_temperature':{'available':True,'data':{'disk1':disk}},
        'smart':{'available':True,'data':{'disk1':{'health_state':'HEALTHY'}}},
    }}
    with patch.object(cli,'service_info',return_value={'ActiveState':'active'}), \
         patch('app.runtime_status.read_status',return_value=(cached,True)), \
         patch('app.runtime_status.sample_live',return_value=True), \
         patch('app.runtime_status.host_identity',return_value={'hostname':'pve','ip':'192.168.11.220'}), \
         patch.object(cli,'physical_disk_vm_assignments',return_value={}), \
         contextlib.redirect_stdout(io.StringIO()) as output:
        cli.print_status(config)
    text=output.getvalue()
    assert 'GPU Intel Corporation Alder Lake-N [UHD Graphics]: PCI Passthrough | 0000:00:02.0 | VM 2223' in text
    assert 'Samsung SSD 850 EVO 1TB: 43.0°C | SMART HEALTHY' in text
    assert 'PCI Passthrough (controller) | 0000:00:17.0 | VM 2223' in text
    assert 'GPU Intel Corporation Alder Lake-N [UHD Graphics]: unavailable' not in text


def test_gpu_vfio_without_owner_does_not_invent_vmid(tmp_path):
    config=tmp_path/'agent.conf'
    config.write_text('[mqtt]\nhost=broker\n')
    cached={'samples':{'gpu':{'available':True,'data':{
        'pci_0000_00_02_0':{'model':'Intel GPU','connection':'passthrough_or_reserved',
                          'source_type':'unknown', 'pci_address':'0000:00:02.0',
                          'temperature_c':None}
    }}}}
    with patch.object(cli,'service_info',return_value={'ActiveState':'active'}), \
         patch('app.runtime_status.read_status',return_value=(cached,True)), \
         patch('app.runtime_status.sample_live',return_value=True), \
         patch('app.runtime_status.host_identity',return_value={'hostname':'pve','ip':'192.168.11.220'}), \
         contextlib.redirect_stdout(io.StringIO()) as output:
        cli.print_status(config)
    assert 'VFIO (VM unknown)' in output.getvalue()
    assert 'VM 2223' not in output.getvalue()
