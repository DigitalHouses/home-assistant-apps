from pathlib import Path

ROOT = Path(__file__).parents[1]
DASHBOARD = ROOT / "examples" / "dh_pve_dashboard.yaml"


def _text() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


def test_vm_lxc_section_is_compact_markdown_tree():
    text = _text()
    assert "type: markdown" in text
    assert "heading: VM / LXC" in text
    assert "sensor.dh_pve_vms" in text
    assert "sensor.dh_pve_lxcs" in text
    assert "proxmox_subject') in ['vm', 'lxc']" in text
    assert "proxmox_subject') == 'passthrough'" in text
    assert "owner_id" in text
    assert "PCI " in text
    assert "🟢" in text
    assert "🟠" in text
    assert "⚪" in text
    assert "🔴" in text


def test_vm_lxc_tree_renders_as_single_preformatted_block_without_blank_rows():
    text = _text()
    assert "ns.lines | join('\\n')" in text
    assert "```text" in text
    assert "pass_text = (' · passthrough '" not in text
    assert "primary: VM · {{ states(entity) }} запущено" not in text
    assert "primary: LXC · {{ states(entity) }} запущено" not in text


def test_internal_collector_diagnostics_are_not_rendered_on_user_dashboard():
    text = _text()
    assert "heading: Диагностика\n" not in text
    assert "proxmox_subject: collector" not in text
    assert "proxmox_section: diagnostic" not in text
