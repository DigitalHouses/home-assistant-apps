from pathlib import Path

from app.collectors.storage import parse_pvesm_status

FIX = Path(__file__).parent / "fixtures" / "disks"


def test_storage_exposes_used_and_total_gib_for_ui_without_ha_math():
    items = parse_pvesm_status((FIX / "shahristan_pvesm.txt").read_text())
    by_name = {item.name: item for item in items}

    local_lvm = by_name["local-lvm"]
    assert local_lvm.used_gib == 358.79
    assert local_lvm.total_gib == 794.30
    assert local_lvm.usage_percent == 45.17


def test_storage_used_total_contract_supports_legacy_server_and_cifs():
    items = parse_pvesm_status((FIX / "legacy_pvesm.txt").read_text())
    by_name = {item.name: item for item in items}

    assert by_name["local-lvm"].used_gib == 121.45
    assert by_name["local-lvm"].total_gib == 140.56
    assert by_name["local-lvm"].usage_percent == 86.40
    assert by_name["TrueNAS25"].storage_type == "cifs"
