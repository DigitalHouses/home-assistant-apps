"""PBS occupied disk capacity: native HA Recorder daily bar history + hover."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock

from app.config import load_config
from app.mqtt import Publisher, HA_TIMEZONE_TOPIC, discovery
from app.state import StateStore, ViewLimits


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
VIEW = ROOT / "dashboards/ru/13_pbs.yaml"
REFERENCE = REPO / "digitalhouses_backblaze_app/dashboards/ru/backblaze.yaml"


def config_in(root: Path, stores: str = "pbs-serzhan"):
    p = root / "agent.ini"
    p.write_text("[mqtt]\nhost=broker\n[pbs]\ndatastores=" + stores + "\n",
                 encoding="utf-8")
    return load_config(p)


class PBSHistoryTests(unittest.TestCase):
    def test_numeric_capacity_sensor_is_long_term_statistics_eligible(self):
        with tempfile.TemporaryDirectory() as d:
            parts = discovery(config_in(Path(d)))["components"]
        key = "datastore_pbs_serzhan_used_gib"
        sensor = parts[key]
        self.assertEqual(sensor["platform"], "sensor")
        self.assertEqual(sensor["default_entity_id"],
                         "sensor.dh_pbs_agent_datastore_pbs_serzhan_used_gib")
        self.assertEqual(sensor["state_class"], "measurement")
        self.assertEqual(sensor["unit_of_measurement"], "GiB")
        self.assertEqual(sensor["suggested_display_precision"], 2)
        self.assertEqual(sensor["entity_category"], "diagnostic")
        self.assertNotIn("device_class", sensor)  # same as working Backblaze example
        self.assertIn(".used_bytes / 1073741824", sensor["value_template"])
        self.assertIn("| round(2)", sensor["value_template"])
        self.assertIn("else none", sensor["value_template"])
        self.assertIn("!= 'S3'", sensor["value_template"])
        self.assertIn("'pbs_metric':", sensor["json_attributes_template"].replace('"pbs_metric"', "'pbs_metric'"))
        self.assertIn("used_gib", sensor["json_attributes_template"])
        self.assertIn("datastore", sensor["json_attributes_template"])
        self.assertNotIn("usage_chart", parts)

    def test_clickable_percent_sensor_is_numeric_and_statistics_eligible(self):
        """The progress row targets its own % history in native HA more-info."""
        with tempfile.TemporaryDirectory() as d:
            parts = discovery(config_in(Path(d), "pbs-serzhan,pbs-core"))["components"]
        for store in ("pbs_serzhan", "pbs_core"):
            key = f"datastore_{store}_used_percent"
            sensor = parts[key]
            self.assertEqual(sensor["default_entity_id"],
                             f"sensor.dh_pbs_agent_{key}")
            self.assertEqual(sensor["state_class"], "measurement")
            self.assertEqual(sensor["unit_of_measurement"], "%")
            self.assertEqual(sensor["suggested_display_precision"], 1)
            self.assertEqual(sensor["entity_category"], "diagnostic")
            self.assertIn(".used_percent", sensor["value_template"])
            self.assertIn("is number", sensor["value_template"])
            self.assertIn("else none", sensor["value_template"])
            self.assertIn("!= 'S3'", sensor["value_template"])
            self.assertIn(f'"{store.replace("_", "-")}"', sensor["value_template"])
            self.assertIn('"pbs_metric": "used_percent"',
                          sensor["json_attributes_template"])

    def test_clicking_progress_row_opens_own_percent_more_info_not_gib(self):
        from jinja2 import Environment

        import yaml
        parsed = yaml.safe_load(VIEW.read_text())
        template = parsed["sections"][1]["cards"][1]["filter"]["template"]
        assert "entity-progress-card-template" in template
        sensors = {
            "sensor.dh_pbs_agent_datastore_pbs_serzhan_used_percent": {
                "state": "13.3",
                "attrs": {
                    "pbs_product": "digitalhouses_pbs_agent",
                    "pbs_section": "datastore",
                    "pbs_metric": "used_percent",
                    "card_name": "pbs-serzhan · занято 13.3%",
                },
            },
            "sensor.dh_pbs_agent_datastore_pbs_core_used_percent": {
                "state": "47.8",
                "attrs": {
                    "pbs_product": "digitalhouses_pbs_agent",
                    "pbs_section": "datastore",
                    "pbs_metric": "used_percent",
                    "card_name": "pbs-core · занято 47.8%",
                },
            },
        }
        class SensorRef:
            def __init__(self, eid):
                self.entity_id = eid
                self.name = eid

        def state_attr(eid, attr):
            return sensors[eid]["attrs"].get(attr)

        def states(eid):
            return sensors[eid]["state"]

        rendered = Environment().from_string(template).render(
            states=type("States", (), {"sensor": [SensorRef(eid) for eid in sensors]})(),
            state_attr=state_attr,
        )
        # HA uses the per-card entity as the target. An explicit tap entity is
        # essential for generated multi-datastore cards and future template changes.
        for entity in sensors:
            self.assertIn("'entity': '" + entity + "'", rendered)
            self.assertIn("'action': 'more-info', 'entity': '" + entity + "'", rendered)
        self.assertEqual(rendered.count("'action': 'more-info'"), 2)
        self.assertNotIn("used_gib", rendered)

    def test_discovery_supports_multiple_datastores_and_never_hardcodes_a_store(self):
        with tempfile.TemporaryDirectory() as d:
            parts = discovery(config_in(Path(d), "pbs-serzhan,pbs-core"))["components"]
        first = parts["datastore_pbs_serzhan_used_gib"]
        second = parts["datastore_pbs_core_used_gib"]
        self.assertNotEqual(first["unique_id"], second["unique_id"])
        self.assertIn('"pbs-serzhan"', first["value_template"])
        self.assertIn('"pbs-core"', second["value_template"])
        self.assertEqual(first["state_topic"], second["state_topic"])
        self.assertEqual(first["unit_of_measurement"], second["unit_of_measurement"])

    def test_canonical_recorder_package_includes_dynamic_numeric_datastores_only(self):
        """Mirror the proven PVE include.entity_globs Recorder package."""
        from fnmatch import fnmatchcase
        root = ROOT / "packages/common"
        package = root / "dh_pbs_agent_recorder_package.yaml"
        self.assertTrue(package.is_file(), "DH Sync must discover the Recorder package")
        source = package.read_text(encoding="utf-8")
        self.assertIn("dh_pbs_agent_recorder_package:\n", source)
        self.assertIn("  recorder:\n    include:\n      entity_globs:", source)
        globs = [line.strip()[2:] for line in source.splitlines()
                 if line.startswith("        - sensor.")]
        self.assertEqual(globs, [
            "sensor.dh_pbs_agent_datastore_*_used_gib",
            "sensor.dh_pbs_agent_datastore_*_used_percent",
        ])
        with tempfile.TemporaryDirectory() as d:
            parts = discovery(config_in(Path(d), "pbs-serzhan,pbs-core"))["components"]
        for name in ("pbs_serzhan", "pbs_core"):
            for metric in ("used_gib", "used_percent"):
                entity = parts[f"datastore_{name}_{metric}"]["default_entity_id"]
                self.assertTrue(any(fnmatchcase(entity, pattern) for pattern in globs), entity)
                self.assertTrue(all(
                    fnmatchcase(entity, pattern) == pattern.endswith(metric)
                    for pattern in globs
                ))
        for not_numeric in (
            "sensor.dh_pbs_agent_health",
            "sensor.dh_pbs_agent_datastore_pbs_serzhan_available_gib",
            "sensor.dh_pbs_agent_backup_tree",
            "sensor.dh_pbs_agent_usage_chart",
            "event.dh_pbs_agent_backup_event",
        ):
            self.assertFalse(any(fnmatchcase(not_numeric, glob) for glob in globs),
                             not_numeric)

        # Distinct package root prevents collision with the existing timezone
        # automation, and there are no host/database overrides.
        timezone_package = (root / "dh_pbs_agent_timezone_package.yaml").read_text()
        self.assertIn("dh_pbs_agent_timezone_package:", timezone_package)
        self.assertNotIn("dh_pbs_agent_recorder_package:", timezone_package)
        for forbidden in ("db_url:", "purge_keep_days:", "host:", "password:",
                          "sensor.dh_pbs_agent_datastore_pbs_serzhan_used_gib"):
            self.assertNotIn(forbidden, source)

    def test_use_existing_backblaze_native_stat_graph_pattern(self):
        example = REFERENCE.read_text()
        config = VIEW.read_text()
        for expected in ("type: statistics-graph", "chart_type: bar",
                         "period: day", "days_to_show: 30", "stat_types:",
                         "- max", "card_param: entities"):
            self.assertIn(expected, config)
            if expected != "card_param: entities":
                self.assertIn(expected, example)
        self.assertIn("pbs_metric') == 'used_gib'", config)
        self.assertIn("states.sensor | sort(attribute='entity_id')", config)
        self.assertIn("'entity': storage.entity_id", config)
        self.assertNotIn("sensor.dh_pbs_agent_usage_chart", config)
        self.assertNotIn("custom_fields:", config)

    def test_layout_remains_original_four_sections_and_graph_last_in_second(self):
        source = VIEW.read_text()
        sections = source.split("\n  - type: grid\n")
        self.assertEqual(len(sections), 5)
        second = sections[2]
        self.assertLess(second.index("heading: Хранилища PBS"),
                        second.index("heading: Резервные копии"))
        self.assertLess(second.index("heading: Резервные копии"),
                        second.index("heading: Занято на диске PBS · 30 дней"))
        self.assertIn("title: Занято за день (максимум)", second)
        self.assertIn("heading: Задания PBS", sections[3])
        self.assertIn("heading: Диагностика", sections[4])

    def test_mqtt_stays_numeric_and_does_not_publish_inline_svg_or_rrd_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)
            cfg = config_in(p)
            pub = Publisher.__new__(Publisher)
            pub.config = cfg
            pub.base = "DigitalHouses/Global/digitalhouses_pbs_agent/pbs_serzhan"
            pub.discovery_topic = "homeassistant/device/dh_pbs_agent_pbs_serzhan/config"
            pub._state_lock = threading.Lock()
            pub._known_jobs = set()
            pub._discovery_primed = False
            pub.job_registry = StateStore(p / "jobs.json")
            pub.timezone_store = StateStore(p / "timezone.json")
            pub.ha_timezone = "Asia/Almaty"
            pub.view_limits = ViewLimits()
            pub.last_state = None
            pub.last_ack_at = None
            pub.connected = True
            pub.client = Mock()
            pub.client.publish.return_value.rc = 0
            pub.client.publish.return_value.is_published.return_value = True
            payload = {
                "status": "HEALTHY",
                "observed_at": "2026-11-22T01:00:00+00:00",
                "datastores": [{"name": "pbs-serzhan",
                                "used_bytes": 143_000_000_000,
                                "available_bytes": 900_000_000_000,
                                "health": "HEALTHY", "backend": "LOCAL"}],
                "maintenance_jobs": [], "backup_groups": [], "task_history": [],
            }
            self.assertTrue(pub.state(payload))
            state_messages = [call for call in pub.client.publish.call_args_list
                              if call.args[0].endswith("/state")]
            self.assertEqual(len(state_messages), 1)
            posted = json.loads(state_messages[0].args[1])
            self.assertEqual(posted["datastores"][0]["used_bytes"], 143_000_000_000)
            self.assertEqual(posted["datastores"][0]["backend"], "LOCAL")
            self.assertTrue(state_messages[0].kwargs.get("retain"))
            self.assertFalse(any(call.args[0].endswith("/usage-chart")
                                 for call in pub.client.publish.call_args_list))
            pub.client.reset_mock()
            pub._on_message(pub.client, None, types.SimpleNamespace(
                topic=HA_TIMEZONE_TOPIC, payload=b"UTC", retain=True))
            self.assertFalse(any(call.args[0].endswith("/usage-chart")
                                 for call in pub.client.publish.call_args_list))
            self.assertEqual(pub.last_state["ha_timezone"], "UTC")

    def test_removed_custom_rrd_pipeline_keeps_collector_simple(self):
        collector = (ROOT / "app/collector.py").read_text()
        mqtt = (ROOT / "app/mqtt.py").read_text()
        self.assertNotIn("get_rrd", collector)
        self.assertNotIn("usage_rrd", collector)
        self.assertNotIn("usage_chart", mqtt)
        self.assertFalse((ROOT / "app/usage_chart.py").exists())


if __name__ == "__main__":
    unittest.main()
