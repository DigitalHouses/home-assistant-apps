"""Contract for the opt-in DigitalHouses admin-chat HA notification package.

Public portable examples intentionally keep persistent_notification.create.
"""
from __future__ import annotations

import re
from pathlib import Path

PACKAGE = (
    Path(__file__).resolve().parents[1]
    / "examples/packages/locales/ru/dh_pve_agent_notification_write2admins.yaml"
)


def test_admin_notifications_have_one_direct_action_per_machine_event() -> None:
    source = PACKAGE.read_text(encoding="utf-8")
    trigger_section = source.split("      triggers:", 1)[1].split(
        "      conditions:", 1
    )[0]
    action_section = source.split("      actions:", 1)[1]

    trigger_ids = re.findall(
        r"(?m)^          id: ([a-z][a-z0-9_]*)$", trigger_section
    )
    branch_ids = re.findall(
        r"(?m)^                    - ([a-z][a-z0-9_]*)$", action_section
    )

    assert len(trigger_ids) == len(branch_ids) == 48
    assert len(trigger_ids) == len(set(trigger_ids))
    assert trigger_ids == branch_ids
    assert source.count("trigger: event.received") == 48
    assert source.count("condition: trigger") == 48
    assert source.count("action: script.write2admins") == 48
    assert source.count("title:") == 48
    assert source.count("message:") == 48
    assert "script.write2log" not in source
    assert "persistent_notification.create" not in source
    assert "id: storage_nfs_unavailable" in source
    assert "id: storage_nfs_restored" in source


def test_admin_notifications_keep_the_existing_ha_automation_contract() -> None:
    source = PACKAGE.read_text(encoding="utf-8")

    assert "dh_pve_agent_notification_local_package:" in source
    assert "id: dh_pve_agent_notifications" in source
    assert "alias: DH PVE Agent · Notifications" in source
    assert "mode: queued" in source
    assert "entity_id: event.dh_pve_agent_diagnostic" in source
    assert "entity_id: event.dh_pve_agent_ups_diagnostic" in source
    assert "trigger.to_state.attributes" in source
    # The delivery script itself inserts the home identifier.
    assert "Дом Асыл" not in source
