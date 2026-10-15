from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.pci_native import parse_native_pci_inventory

APP = Path(__file__).resolve().parents[1]
SCRIPT = APP / "bin" / "pve-pci-inventory"
CATALOG = {
    "0000:00:17.0": {
        "model": "Intel SATA controller",
        "class_name": "SATA controller",
    },
}


def _item(vmid="700", address="0000:00:17.0", key="hostpci0", cls="0x010601"):
    return {
        "guest_id": vmid,
        "config_key": key,
        "pci_address": address,
        "pci_class": cls,
        "vendor_id": "0x8086",
        "device_id": "0x54d3",
    }


def test_native_decoder_resolves_class_and_preserves_real_function():
    payload = {
        "schema": 1,
        "devices": [_item(), _item(address="0000:00:17.1")],
        "errors": [],
    }
    result, errors = parse_native_pci_inventory(json.dumps(payload), {"700"}, CATALOG)

    assert not errors
    assert result["0000:00:17.0"][1].pci_class == "0106"
    assert result["0000:00:17.0"][1].model == "Intel SATA controller"
    assert result["0000:00:17.1"][1].pci_address == "0000:00:17.1"


@pytest.mark.parametrize("payload", [
    {"schema": 2, "devices": [], "errors": []},
    {"schema": 1, "devices": [_item(address="0000:00:17")], "errors": []},
    {"schema": 1, "devices": [_item(cls="broken")], "errors": []},
    {"schema": 1, "devices": [_item(), _item()], "errors": []},
    {"schema": 1, "devices": [_item(vmid="123")], "errors": []},
    {"schema": 1, "devices": [], "errors": [{"guest_id": "123", "message": "bad"}]},
])
def test_native_decoder_rejects_untrustworthy_inventory(payload):
    with pytest.raises(ValueError):
        parse_native_pci_inventory(json.dumps(payload), {"700"}, CATALOG)


@pytest.mark.skipif(shutil.which("perl") is None, reason="Perl is not installed")
def test_native_helper_handles_slot_multifunction_mapping_and_ambiguity(tmp_path):
    """Stub PVE Perl modules to exercise the real helper's output contract."""
    qemu = tmp_path / "PVE" / "QemuConfig.pm"
    pci = tmp_path / "PVE" / "QemuServer" / "PCI.pm"
    qemu.parent.mkdir(parents=True)
    pci.parent.mkdir(parents=True)
    qemu.write_text(r"""package PVE::QemuConfig;
sub load_config {
    my ($class, $vmid) = @_;
    return { hostpci0 => "0000:00:17" } if $vmid == 700;
    return { hostpci0 => "mapping=storage" } if $vmid == 701;
    return { hostpci0 => "mapping=ambiguous" } if $vmid == 702;
    return {};
}
1;
""")
    pci.write_text(r"""package PVE::QemuServer::PCI;
sub parse_hostpci {
    my ($config) = @_;
    my $function = sub {
        my ($id) = @_;
        return {
            id => $id, class => "0x010601",
            vendor => "0x8086", device => "0x54d3",
        };
    };
    if ($config eq "0000:00:17") {
        return {ids => [[ $function->("0000:00:17.0"),
                          $function->("0000:00:17.1") ]]};
    }
    if ($config eq "mapping=storage") {
        return {ids => [[ $function->("0000:00:17.0") ]]};
    }
    if ($config eq "mapping=ambiguous") {
        return {ids => [[ $function->("0000:00:17.0") ],
                        [ $function->("0000:00:18.0") ]]};
    }
    die "unexpected native parse input";
}
1;
""")
    jsonschema = tmp_path / "PVE" / "JSONSchema.pm"
    usb = tmp_path / "PVE" / "QemuServer" / "USB.pm"
    jsonschema.write_text("package PVE::JSONSchema; 1;\\n".replace("\\\\n", "\\n"))
    usb.write_text("package PVE::QemuServer::USB; 1;\\n".replace("\\\\n", "\\n"))
    result = subprocess.run(
        ["perl", "-I", str(tmp_path), str(SCRIPT), "700", "701", "702"],
        capture_output=True, text=True, check=True, timeout=10,
    )
    payload = json.loads(result.stdout)
    assert payload["schema"] == 1
    assert [
        (item["guest_id"], item["pci_address"])
        for item in payload["devices"]
    ] == [
        ("700", "0000:00:17.0"), ("700", "0000:00:17.1"),
        ("701", "0000:00:17.0"),
    ]
    assert payload["errors"][0]["guest_id"] == "702"
    assert "ambiguous" in payload["errors"][0]["message"]
