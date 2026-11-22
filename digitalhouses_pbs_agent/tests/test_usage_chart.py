"""30-day PBS RRD datastore capacity chart: all calculations in Agent."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
import math
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock

from app.collector import collect, SourceError
from app.config import load_config
from app.mqtt import Publisher, HA_TIMEZONE_TOPIC, discovery
from app.state import StateStore, ViewLimits
from app.usage_chart import GIB, daily_usage, render_usage_chart

ROOT = Path(__file__).resolve().parents[1]
OBSERVED = "2026-11-22T02:15:00+00:00"


def ts(day: int, hour: int, minute: int = 0) -> int:
    return int(datetime(2026, 11, day, hour, minute, tzinfo=timezone.utc).timestamp())


class UsageChartTests(unittest.TestCase):
    def test_thirty_local_days_midnight_latest_and_missing_not_zero(self):
        rows = [
            {"time": ts(21, 18, 59), "used": 113 * GIB},  # 21 Nov 23:59 in HA
            {"time": ts(21, 19, 20), "used": 115 * GIB},  # 22 Nov 00:20 in HA
            {"time": ts(21, 20, 10), "used": 117 * GIB},  # same local day, later
            {"time": ts(20, 19, 0), "used": 110 * GIB},   # 21 Nov 00:00 in HA
            {"time": ts(22, 3), "used": 500 * GIB},       # future, ignore
            {"time": ts(21, 12), "used": None},            # missing, ignore
            {"time": "bad", "used": 0},
            {"time": ts(21, 15), "used": -50},
            {"time": float("nan"), "used": 222},
        ]
        output = daily_usage(rows, OBSERVED, "Asia/Almaty", 119 * GIB)
        self.assertEqual(len(output), 30)
        self.assertEqual(output[0]["date"], "2026-10-24")
        self.assertEqual(output[-1]["date"], "2026-11-22")
        self.assertEqual(output[-1]["used_gib"], 119)
        self.assertEqual(output[-1]["source"], "live")
        self.assertEqual(output[-2]["used_gib"], 113)
        self.assertEqual(output[-3]["used_gib"], None)
        self.assertEqual(sum(p["used_gib"] is not None for p in output), 2)
        self.assertTrue(all(p["used_gib"] is None for p in output[:27]))

    def test_last_month_day_and_utc_are_different(self):
        sample = [{"time": ts(21, 19, 20), "used": 100 * GIB}]
        local = daily_usage(sample, OBSERVED, "Asia/Almaty")
        utc = daily_usage(sample, OBSERVED, "UTC")
        self.assertEqual(local[-1]["used_gib"], 100)
        self.assertEqual(utc[-1]["used_gib"], None)
        self.assertEqual(utc[-2]["used_gib"], 100)

    def test_positive_zero_and_negative_delta_are_not_invented(self):
        rows = [
            {"time": ts(19, 19), "used": 130 * GIB},
            {"time": ts(20, 19), "used": 129 * GIB},
        ]
        result = render_usage_chart({"pbs-serzhan": {"rows": rows}}, [
            {"name": "pbs-serzhan", "used_bytes": 125 * GIB, "health": "HEALTHY"}
        ], OBSERVED, "Asia/Almaty")
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["available"], 3)
        self.assertEqual(result["latest_used_gib"], 125.0)
        self.assertEqual(result["delta_gib"], -5.0)
        self.assertIn("Изменение с 20.11: -5.00 GiB", result["html"])
        self.assertIn("Шкала", result["html"])
        self.assertIn("(не от нуля)", result["html"])
        self.assertEqual(result["html"].count("<g>"), 30)
        self.assertEqual(result["html"].count("<rect "), 3)
        self.assertIn('<svg role="img"', result["html"])
        self.assertIn("нет измерений", result["html"])
        self.assertIn("Пропуски не заменяются нулями", result["html"])
        self.assertNotIn("Группы резервных копий", result["html"])

    def test_genuinely_zero_rrd_is_valid_not_fake(self):
        rows = [{"time": ts(21, 18, 50), "used": 0}]
        days = daily_usage(rows, OBSERVED, "Asia/Almaty")
        self.assertEqual(days[-2]["used_gib"], 0.0)
        self.assertEqual(days[-1]["used_gib"], None)

    def test_missing_rrd_and_live_status_explicit(self):
        result = render_usage_chart({"pbs-home": {
            "rows": [], "error": "PBS local CLI failed (exit 1)"
        }}, [{"name": "pbs-home", "health": "HEALTHY",
              "used_bytes": 119 * GIB}], OBSERVED, "Asia/Almaty")
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["available"], 1)
        self.assertIsNone(result["delta_gib"])
        self.assertIn("RRD недоступен", result["html"])
        self.assertIn("Измерений: 1/30", result["html"])
        self.assertIn("История пока не накоплена", result["html"])
        all_missing = render_usage_chart({"pbs-home": {
            "rows": [], "error": "PBS no history"
        }}, [{"name": "pbs-home", "health": "UNAVAILABLE"}],
            OBSERVED, "Asia/Almaty")
        self.assertEqual(all_missing["status"], "NO_DATA")
        self.assertEqual(all_missing["available"], 0)
        self.assertIn("Нет достоверной истории", all_missing["html"])

    def test_dynamic_multiple_datastores_and_html_escaping(self):
        stores = [
            {"name": "home<&>", "health": "HEALTHY", "used_bytes": 20 * GIB},
            {"name": "core-archive", "health": "HEALTHY", "used_bytes": 30 * GIB},
            {"name": "cloud-s3", "backend": "S3", "health": "HEALTHY"},
        ]
        output = render_usage_chart({}, stores, OBSERVED, "Asia/Almaty")
        self.assertIn("home&lt;&amp;&gt;", output["html"])
        self.assertIn("core-archive", output["html"])
        self.assertNotIn("cloud-s3", output["html"])
        self.assertEqual(output["available"], 2)

    def test_mqtt_discovery_and_yaml_chart_have_no_js_data_logic(self):
        with tempfile.TemporaryDirectory() as d:
            conf = Path(d) / "agent.ini"
            conf.write_text("[mqtt]\nhost=broker\n[pbs]\ndatastores=pbs-home\n")
            item = discovery(load_config(conf))["components"]["usage_chart"]
        self.assertEqual(item["default_entity_id"], "sensor.dh_pbs_agent_usage_chart")
        self.assertTrue(item["state_topic"].endswith("/usage-chart"))
        self.assertIn("value_json.html", item["json_attributes_template"])
        view = (ROOT / "dashboards/ru/13_pbs.yaml").read_text()
        section = view.split("heading: Занято на диске PBS · 30 дней", 1)[1].split(
            "heading: Задания PBS", 1)[0]
        self.assertIn("column_span: 2", view)
        self.assertIn("custom:button-card", section)
        self.assertIn("entity?.attributes?.html", section)
        self.assertNotIn("data_generator:", section)
        self.assertNotIn("apexcharts-card", section)
        self.assertNotIn("new Date(", section)
        self.assertNotIn(".map(", section)

    def test_publisher_keeps_full_rrd_in_ram_only_and_timezone_reformats_chart(self):
        with tempfile.TemporaryDirectory() as d:
            conf = Path(d) / "agent.ini"
            conf.write_text("[mqtt]\nhost=broker\n[pbs]\ndatastores=pbs-home\n")
            config = load_config(conf)
            pub = Publisher.__new__(Publisher)
            pub.config = config
            pub.base = "DigitalHouses/Global/digitalhouses_pbs_agent/pbs_home"
            pub.discovery_topic = "homeassistant/device/dh_pbs_agent_pbs_home/config"
            pub._state_lock = threading.Lock()
            pub._known_jobs = set()
            pub._discovery_primed = False
            pub.job_registry = StateStore(Path(d) / "jobs.json")
            pub.timezone_store = StateStore(Path(d) / "timezone.json")
            pub.ha_timezone = "UTC"
            pub.view_limits = ViewLimits()
            pub.last_state = None
            pub.last_ack_at = None
            pub.connected = True
            pub.client = Mock()
            pub.client.publish.return_value.rc = 0
            pub.client.publish.return_value.is_published.return_value = True
            msg = {
                "status": "HEALTHY", "observed_at": OBSERVED,
                "datastores": [{
                    "name": "pbs-home", "used_bytes": 125 * GIB,
                    "health": "HEALTHY", "backend": "LOCAL",
                }],
                "maintenance_jobs": [], "task_history": [],
                "usage_rrd": {"pbs-home": {"rows": [
                    {"time": ts(21, 19, 20), "used": 120 * GIB},
                ]}},
            }
            self.assertTrue(pub.state(msg))
            self.assertNotIn("usage_rrd", pub.last_state)
            state_calls = [x for x in pub.client.publish.call_args_list
                           if x.args[0].endswith("/state")]
            self.assertEqual(len(state_calls), 1)
            self.assertNotIn("usage_rrd", state_calls[0].args[1])
            charts = [x for x in pub.client.publish.call_args_list
                      if x.args[0].endswith("/usage-chart")]
            self.assertEqual(len(charts), 1)
            before = json.loads(charts[-1].args[1])
            self.assertEqual(before["available"], 2)  # UTC days 21 and 22
            self.assertTrue(charts[-1].kwargs["retain"])
            pub.client.reset_mock()
            pub._on_message(pub.client, None, types.SimpleNamespace(
                topic=HA_TIMEZONE_TOPIC, payload=b"Asia/Almaty", retain=True))
            charts = [x for x in pub.client.publish.call_args_list
                      if x.args[0].endswith("/usage-chart")]
            self.assertEqual(len(charts), 1)
            after = json.loads(charts[-1].args[1])
            self.assertEqual(after["available"], 1)  # both same HA day
            self.assertEqual(after["ha_timezone"], "Asia/Almaty")
            self.assertIn("Измерений: 1/30", after["html"])
            self.assertNotIn("usage_rrd", pub.last_state)
            self.assertEqual(pub.timezone_store.load()["timezone"], "Asia/Almaty")


if __name__ == "__main__":
    unittest.main()
