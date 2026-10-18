"""MQTT selection + destructive phone button: App is the sole authority."""
from __future__ import annotations

import json
import queue
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import (MqttOutput, build_engine, execute_mqtt_phone_deletion,
                 publish_snapshot, synchronize_discovery)
from dh_presence.discovery import discovery, topic
from dh_presence.phone_removal import EMPTY, PhoneRemovalSelection, phone_removal_choices
from dh_presence.registration import load_registry_state, save_registry

FIRST = {"user_id": "u1", "user_name": "Serzhan",
         "device_name": "13ProMAX .SKY", "device_id": "d1",
         "entry_id": "gps:device_tracker.phone_a",
         "tracker": "device_tracker.phone_a",
         "ip": "192.168.8.54", "mac": "88:b9:45:80:a7:55",
         "wifi_tracker": "device_tracker.wifi_a"}
SECOND = {"user_id": "u2", "user_name": "Anel",
          "device_name": "Anelkin15", "device_id": "d2",
          "entry_id": "gps:device_tracker.phone_b",
          "tracker": "device_tracker.phone_b",
          "ip": "192.168.8.55", "mac": "8a:43:3e:74:09:83",
          "wifi_tracker": "device_tracker.iphone"}


def settings(**kw):
    return {"presence_mode": "gps", "wifi_absence_minutes": 15,
            "gps_freshness_seconds": 300,
            "residents": [], "exclude_users": [],
            "resident_names": [], **kw}


class TestMqttPhoneRemoval(unittest.TestCase):
    def engine(self, registered=None, options=None):
        return build_engine(options or settings(),
                            {"schema_version": 2, "residents": []},
                            FIRST_AND_SECOND if registered is None else registered)

    def test_choices_are_dynamic_unique_and_only_eligible(self):
        e = self.engine()
        choices = phone_removal_choices([FIRST, SECOND], list(e.residents.values()))
        self.assertEqual(len(choices), 2)
        self.assertEqual(set(choices.values()),
                         {"device_tracker.phone_a", "device_tracker.phone_b"})
        self.assertTrue(next(k for k, v in choices.items()
                             if v == "device_tracker.phone_a").startswith("Serzhan (13ProMAX .SKY)"))
        self.assertIn("device_tracker.phone_a", next(k for k, v in choices.items()
                                                    if v == "device_tracker.phone_a"))
        excluded = self.engine(options=settings(exclude_users=["u1"]))
        options = phone_removal_choices([FIRST, SECOND], list(excluded.residents.values()))
        self.assertEqual(list(options.values()), ["device_tracker.phone_b"])
        self.assertEqual(phone_removal_choices([], list(e.residents.values())), {})

    def test_select_unselected_stale_invalid_and_durable_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "registry.json")
            save_registry(path, [FIRST, SECOND])
            cfg = settings(residents=["device_tracker.phone_a", "device_tracker.phone_b"])
            engine = self.engine(options=cfg)
            selection = PhoneRemovalSelection()
            choices = phone_removal_choices([FIRST, SECOND], list(engine.residents.values()))
            self.assertEqual(selection.selected, EMPTY)
            self.assertIsNone(selection.target(choices))
            result = execute_mqtt_phone_deletion(selection, engine, cfg, path,
                                                [FIRST, SECOND], set())
            self.assertFalse(result[0])
            self.assertEqual(len(load_registry_state(path)[0]), 2)
            self.assertFalse(selection.select("device_tracker.phone_a", choices))
            self.assertFalse(selection.select("not a phone", choices))
            label_a = next(k for k, v in choices.items() if v == FIRST["tracker"])
            self.assertTrue(selection.select(label_a, choices))
            self.assertEqual(selection.target(choices), FIRST["tracker"])
            deleted, changed, registrations, disabled = execute_mqtt_phone_deletion(
                selection, engine, cfg, path, [FIRST, SECOND], set())
            self.assertTrue(deleted)
            self.assertTrue(changed)
            self.assertEqual(selection.selected, EMPTY)
            self.assertEqual([x["tracker"] for x in registrations], [SECOND["tracker"]])
            self.assertEqual(disabled, {FIRST["tracker"]})
            self.assertNotIn(FIRST["tracker"], engine.residents)
            self.assertEqual(set(engine.residents), {SECOND["tracker"]})
            self.assertEqual(registrations, load_registry_state(path)[0])
            # Duplicate QoS1 button with selection already cleared is harmless.
            deleted_again, _, _, _ = execute_mqtt_phone_deletion(
                selection, engine, cfg, path, registrations, disabled)
            self.assertFalse(deleted_again)
            self.assertEqual([x["tracker"] for x in load_registry_state(path)[0]],
                             [SECOND["tracker"]])
            # Legacy configuration must not resurrect a deleted phone.
            restarted = build_engine(cfg, {"schema_version": 2, "residents": []},
                                     registrations, disabled)
            self.assertEqual(set(restarted.residents), {SECOND["tracker"]})

    def test_deleted_in_other_session_cannot_be_removed_again(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "registry.json")
            save_registry(path, [FIRST, SECOND])
            engine = self.engine()
            selection = PhoneRemovalSelection()
            label = next(k for k, v in phone_removal_choices([FIRST, SECOND],
                   list(engine.residents.values())).items() if v == FIRST["tracker"])
            self.assertTrue(selection.select(label, phone_removal_choices(
                [FIRST, SECOND], list(engine.residents.values()))))
            # Another UI already removed the record before this MQTT command.
            save_registry(path, [SECOND], disabled_trackers={FIRST["tracker"]})
            deleted, changed, remaining, disabled = execute_mqtt_phone_deletion(
                selection, engine, settings(), path, [FIRST, SECOND], set())
            self.assertFalse(deleted)
            self.assertTrue(changed)
            self.assertEqual(remaining, [SECOND])
            self.assertEqual(disabled, {FIRST["tracker"]})
            self.assertEqual(selection.selected, EMPTY)
            self.assertEqual(set(engine.residents), {SECOND["tracker"]})

    def test_mqtt_command_listener_rejects_retained_and_invalid_messages(self):
        output = object.__new__(MqttOutput)
        output.phone_commands = queue.SimpleQueue()
        def message(suffix, payload, retained=False):
            m = SimpleNamespace(topic=topic(suffix), payload=payload, retain=retained)
            output._message(None, None, m)
        with patch("app.WAKE") as wake:
            message("registrations/remove/press", b"DELETE", retained=True)
            message("registrations/remove/select/set", b"whatever", retained=True)
            message("registrations/remove/press", b"WRONG")
            message("registrations/remove/select/set", b"\xff")
            message("registrations/remove/select/set", b"x" * 513)
            self.assertTrue(output.phone_commands.empty())
            wake.set.assert_not_called()
            label = "Serzhan (13ProMAX .SKY) · device_tracker.phone_a"
            message("registrations/remove/select/set", label.encode())
            message("registrations/remove/press", b"DELETE")
            self.assertEqual(output.phone_commands.get_nowait(), ("select", label))
            self.assertEqual(output.phone_commands.get_nowait(), ("delete", None))
            self.assertTrue(output.phone_commands.empty())
            self.assertEqual(wake.set.call_count, 2)

    def test_discovery_dynamic_select_and_button_same_mqtt_device(self):
        e = self.engine()
        choices = phone_removal_choices([FIRST, SECOND], list(e.residents.values()))
        components = discovery("0.1.33", list(e.residents.values()),
                               phone_options=[EMPTY, *choices])["components"]
        self.assertEqual(len(components), 25)  # 20 global + 3 x 2 residents +? dynamic
        selection = components["remove_phone_select"]
        button = components["delete_registration"]
        self.assertEqual(selection["default_entity_id"],
                         "select.dh_presence_app_remove_phone")
        self.assertEqual(selection["options"], [EMPTY, *choices])
        self.assertEqual(selection["command_topic"],
                         topic("registrations/remove/select/set"))
        self.assertEqual(selection["state_topic"],
                         topic("registrations/remove/select/state"))
        self.assertIs(selection["retain"], False)
        self.assertEqual(button["default_entity_id"],
                         "button.dh_presence_app_delete_registration")
        self.assertEqual(button["command_topic"], topic("registrations/remove/press"))
        self.assertEqual(button["payload_press"], "DELETE")
        self.assertIs(button["retain"], False)
        self.assertEqual(set(c["platform"] for c in (selection, button)),
                         {"select", "button"})
        self.assertNotIn("remove/press", json.dumps(components["residents_home"]))
        self.assertEqual(discovery("0.1.33", [])["components"]["remove_phone_select"]["options"],
                         [EMPTY])

    def test_discovery_change_is_regenerated_on_roster_mutation(self):
        e = self.engine()
        fake = Mock()
        fake.publish.return_value = True
        with patch("app.load_discovery", return_value={"components": {}}), \
             patch("app.save_discovery") as storage:
            self.assertTrue(synchronize_discovery(
                fake, "0.1.33", e, registrations=[FIRST, SECOND]))
            discovered = storage.call_args.args[0]["components"]["remove_phone_select"]
            self.assertEqual(len(discovered["options"]), 3)
            del e.residents[FIRST["tracker"]]
            self.assertTrue(synchronize_discovery(
                fake, "0.1.33", e, registrations=[SECOND]))
            updated = storage.call_args.args[0]["components"]["remove_phone_select"]
            self.assertEqual(len(updated["options"]), 2)
            self.assertTrue(all(FIRST["tracker"] not in option for option in updated["options"]))

    def test_publish_only_selection_state_not_phone_identity_on_presence(self):
        e = self.engine()
        fake = Mock()
        fake.publish.return_value = True
        operations = Mock()
        operations.snapshot.return_value = {"card": {"state": "idle"}}
        selection = PhoneRemovalSelection()
        selection.select(next(iter(phone_removal_choices([FIRST, SECOND],
                                list(e.residents.values())))),
                         phone_removal_choices([FIRST, SECOND], list(e.residents.values())))
        self.assertTrue(publish_snapshot(fake, e, "0.1.33", "2026-10-19T10:00:00+00:00",
                                         operations, None, registrations=[FIRST, SECOND],
                                         phone_selection=selection))
        published = {x.args[0]: x.args[1] for x in fake.publish.call_args_list}
        self.assertEqual(published[topic("registrations/remove/select/state")],
                         selection.selected)
        self.assertNotIn(FIRST["ip"], json.dumps(published[topic("state")]))
        self.assertNotIn(FIRST["mac"], json.dumps(published[topic("state")]))


FIRST_AND_SECOND = [FIRST, SECOND]

if __name__ == "__main__":
    unittest.main()
