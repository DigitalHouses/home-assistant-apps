from types import SimpleNamespace
from pathlib import Path

from app.disk_temperature import DiskTemperatureSample
from app.production_v1 import ResilientProductionCollectors
from app.state_store import StateStore
from app.topology import GuestStorageSource


class FakePciTopology:
    def __init__(self):
        self.snapshot = SimpleNamespace(pci={
            '0000:00:17.0': SimpleNamespace(
                owner_id='2223',
                device=SimpleNamespace(config_key='hostpci0', pci_class='0106')
            )
        })
        self.source=GuestStorageSource(
            guest_id='2223', guest_name='media', guest_status='running',
            device_path='/dev/sdb', model='Samsung SSD 850 EVO',
            serial='S2PWNX0H603177N', wwn='0x5002538d41046527',
            size_bytes=1000204886016, transport='sata',
            passthrough_hostpci='hostpci0',
        )
    def vm_storage_sources(self):
        return (self.source,)
    def guest_status(self,guest_id):
        return 'running'
    def qga_state(self,guest_id):
        return 'available'
    def guest_exec(self, guest_id, command, timeout=30):
        if '-a -j' in command:
            return (Path(__file__).parent / 'fixtures/guests/samsung_850_evo_smart.json').read_text()
        if '-A -j' in command:
            return '{"temperature":{"current":43}}'
        raise AssertionError(command)


def test_pci_controller_resolves_from_existing_native_topology(tmp_path, monkeypatch):
    topology=FakePciTopology()
    collector=ResilientProductionCollectors(node_name='PVE',
            disk_state_store=StateStore(tmp_path/'disks.json'),topology=topology)
    monkeypatch.setattr(collector,'_smart_scan',lambda:())
    health=collector.smart()
    disk_id=next(iter(health.data))
    temp=collector.disk_temperature()
    item=temp.data[disk_id]
    assert item['source_guest_id']=='2223'
    assert item['passthrough_hostpci']=='hostpci0'
    assert item['passthrough_pci_address']=='0000:00:17.0'
    assert item['temperature_c']==43.0

    # If more than one storage controller matches, preserve guest owner
    # but do not pretend an individual physical disk maps to one PCI BDF.
    topology.snapshot.pci['0000:00:18.0']=SimpleNamespace(
        owner_id='2223',device=SimpleNamespace(config_key='hostpci0',pci_class='0106'))
    ambiguous=collector.disk_temperature().data[disk_id]
    assert 'passthrough_pci_address' not in ambiguous
    assert ambiguous['passthrough_hostpci']=='hostpci0'
