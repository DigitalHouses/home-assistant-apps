from pathlib import Path
from app.collectors.storage import parse_pvesm_status

FIX = Path(__file__).parent / "fixtures" / "disks"


def test_parse_real_pvesm_status():
    items = parse_pvesm_status((FIX / "shahristan_pvesm.txt").read_text())
    assert len(items) == 5
    by_name = {item.name: item for item in items}
    assert by_name["local"].usage_percent == 29.25
    assert by_name["local-lvm"].storage_type == "lvmthin"
    assert by_name["truenas_data"].available_kib == 184961536
