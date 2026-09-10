import json
from pathlib import Path
from app.collectors.smart import parse_smart_json, smart_wwn
from app.collectors.disks import stable_disk_id

FIX = Path(__file__).parent / "fixtures" / "disks"


def load(name):
    return json.loads((FIX / name).read_text())


def test_parse_real_nvme_samsung_990_evo():
    snap = parse_smart_json(load("nvme_samsung_990_evo.json"), "/dev/nvme0")
    assert snap.protocol == "NVMe"
    assert snap.model == "Samsung SSD 990 EVO 1TB"
    assert snap.serial == "S7M3NL0Y413841D"
    assert snap.smart_passed is True
    assert snap.temperature_c == 57.0
    assert snap.temperature_max_c == 67.0
    assert snap.wear_used_percent == 3.0
    assert snap.power_on_hours == 8938
    assert snap.unsafe_shutdowns == 25
    assert snap.media_errors == 0
    assert snap.data_written_tb == 20.7
    assert snap.wwn == "eui.0025382451a05c68"


def test_parse_real_seagate_hdd():
    snap = parse_smart_json(load("seagate_st500dm002.json"), "/dev/sdb")
    assert snap.protocol == "ATA"
    assert snap.disk_type == "HDD"
    assert snap.wwn == "naa.5000c50065349b93"
    assert snap.temperature_c == 33.0
    assert snap.power_on_hours == 21310
    assert snap.reallocated_sectors == 0
    assert snap.pending_sectors == 0
    assert snap.offline_uncorrectable == 0
    assert snap.uncorrectable_errors == 0
    assert snap.crc_errors == 0


def test_ata_ssd_wear_uses_existing_bash_compatible_life_remaining_rule():
    snap = parse_smart_json(load("ata_ssd_partial.json"), "/dev/sda")
    assert snap.disk_type == "SSD"
    assert snap.wear_used_percent == 0.0
    assert snap.program_failures == 0
    assert snap.erase_failures == 0


def test_stable_id_prefers_wwn_then_serial_then_fallback():
    assert stable_disk_id(wwn="eui.0025382451a05c68", serial="S7", path="/dev/nvme0", model="Samsung", size_bytes=1) == "wwn_eui_0025382451a05c68"
    assert stable_disk_id(wwn=None, serial="Z3TT2FMD", path="/dev/sdb", model="Seagate", size_bytes=1) == "serial_z3tt2fmd"
    value = stable_disk_id(wwn=None, serial=None, path="/dev/sdc", model="Unknown", size_bytes=500)
    assert value.startswith("fallback_") and len(value) == 21


def test_smart_wwn_reconstructs_ata_and_nvme_values():
    assert smart_wwn(load("seagate_st500dm002.json")) == "naa.5000c50065349b93"
    assert smart_wwn(load("nvme_samsung_990_evo.json")) == "eui.0025382451a05c68"
