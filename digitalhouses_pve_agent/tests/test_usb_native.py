from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.pci_native import parse_native_usb_inventory

SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "pve-pci-inventory"


def test_native_usb_parses_ruslan_and_home_contracts():
    payload = {
        "schema": 1,
        "devices": [], "errors": [],
        "usb_devices": [
            {"guest_id": "100", "config_key": "usb0", "vendor_id": "1a86", "product_id": "7523"},
            {"guest_id": "100", "config_key": "usb1", "vendor_id": "1a86", "product_id": "55d4"},
            {"guest_id": "110", "config_key": "usb0", "vendor_id": "1a86", "product_id": "7523"},
            {"guest_id": "120", "config_key": "usb0", "physical_port": "1-4"},
        ],
        "usb_errors": [],
    }
    data, errors = parse_native_usb_inventory(json.dumps(payload), {"100", "110", "120"})
    assert not errors
    assert [x.usb_id for x in data["100"]] == ["1a86:7523", "1a86:55d4"]
    assert data["110"][0].config_key == "usb0"
    assert data["120"][0].physical_port == "1-4"


@pytest.mark.parametrize("item", [
    {"guest_id": "100", "config_key": "usb0", "vendor_id": "bad", "product_id": "7523"},
    {"guest_id": "100", "config_key": "usb0", "physical_port": "bogus"},
    {"guest_id": "100", "config_key": "hostpci0", "physical_port": "1-4"},
    {"guest_id": "666", "config_key": "usb0", "physical_port": "1-4"},
    {"guest_id": "100", "config_key": "usb0", "physical_port": "1-4", "vendor_id": "1a86"},
])
def test_native_usb_rejects_invalid_identity(item):
    with pytest.raises(ValueError):
        parse_native_usb_inventory(
            json.dumps({"schema": 1, "usb_devices": [item], "usb_errors": []}),
            {"100"},
        )


@pytest.mark.skipif(shutil.which("perl") is None, reason="Perl missing")
def test_real_native_helper_decodes_vid_port_mapping_and_spice(tmp_path: Path):
    (tmp_path / "PVE" / "QemuServer").mkdir(parents=True)
    (tmp_path / "PVE" / "QemuConfig.pm").write_text(r"""package PVE::QemuConfig;
sub load_config {
    my ($class, $vmid) = @_;
    return { usb0 => "host=1a86:7523", usb1 => "host=1a86:55d4" } if $vmid == 100;
    return { usb0 => "host=1a86:7523" } if $vmid == 110;
    return { usb0 => "host=1-4" } if $vmid == 120;
    return { usb0 => "mapping=zwave" } if $vmid == 121;
    return { usb0 => "host=spice" } if $vmid == 122;
    return { usb0 => "mapping=invalid" } if $vmid == 123;
    return {};
}
1;
""")
    (tmp_path / "PVE" / "QemuServer" / "PCI.pm").write_text(r"""package PVE::QemuServer::PCI;
sub parse_hostpci { die "unexpected PCI call"; }
1;
""")
    (tmp_path / "PVE" / "JSONSchema.pm").write_text(r"""package PVE::JSONSchema;
sub parse_property_string {
    my ($format, $value) = @_;
    die "bad format" unless $format eq "pve-qm-usb";
    die "bad USB config" unless $value =~ /^(host|mapping)=([a-z0-9:.-]+)$/i;
    return {$1 => $2};
}
1;
""")
    (tmp_path / "PVE" / "QemuServer" / "USB.pm").write_text(r"""package PVE::QemuServer::USB;
sub parse_usb_device {
    my ($value, $mapping) = @_;
    $value = "1-2" if defined($mapping) && $mapping eq "zwave";
    die "invalid mapping" if defined($mapping) && $mapping eq "invalid";
    return {spice => 1} if $value eq "spice";
    return {vendorid => lc($1), productid => lc($2)}
        if $value =~ /^([0-9a-f]{4}):([0-9a-f]{4})$/i;
    return {hostbus => $1, hostport => $2}
        if $value =~ /^([0-9]+)-([0-9]+(?:\.[0-9]+)*)$/;
    die "invalid USB selector";
}
1;
""")
    p = subprocess.run(
        ["perl", "-I", str(tmp_path), str(SCRIPT),
         "100", "110", "120", "121", "122", "123"],
        capture_output=True, text=True, check=True, timeout=15,
    )
    payload = json.loads(p.stdout)
    actual, errors = parse_native_usb_inventory(
        p.stdout, {"100", "110", "120", "121", "122", "123"},
    )
    assert [x.usb_id for x in actual["100"]] == ["1a86:7523", "1a86:55d4"]
    assert actual["110"][0].usb_id == "1a86:7523"
    assert actual["120"][0].physical_port == "1-4"
    assert actual["121"][0].physical_port == "1-2"
    assert "122" not in actual  # SPICE redirection is not a physical USB assignment.
    assert "123" in errors and "invalid mapping" in errors["123"]
    assert payload["devices"] == []  # native PCI remains independent
