"""Retired detection controls: only router trackers may determine runtime Wi-Fi."""

import unittest
from pathlib import Path

from dh_presence.discovery import discovery, with_cleanup, topic
from dh_presence.core import Engine
from app import MqttOutput

class RetiredProbeControlsTests(unittest.TestCase):
    def test_new_mqtt_discovery_does_not_publish_ping_or_arp_switches(self):
        cfg=discovery("0.1.25", list(Engine().residents.values()))
        keys=cfg["components"]
        self.assertNotIn("ping", keys)
        self.assertNotIn("arp", keys)
        self.assertEqual({key for key in keys if key.startswith("notify_")},
                         {"notify_presence", "notify_gps", "notify_wifi"})

    def test_retired_entities_receive_discovery_cleanup(self):
        cfg=discovery("0.1.25", [])
        previous={"components":{"ping":{"platform":"switch"},
                                "arp":{"platform":"switch"}}}
        result=with_cleanup(previous,cfg)["components"]
        self.assertEqual(result["ping"], {"platform":"switch"})
        self.assertEqual(result["arp"], {"platform":"switch"})

    def test_no_runtime_probe_command_subscriptions(self):
        code=Path(MqttOutput.__module__.replace(".", "/")).as_posix()
        import app
        runtime=Path(app.__file__).read_text(encoding="utf-8")
        self.assertNotIn('topic("probes/"',runtime)
        self.assertNotIn("self.probe_commands",runtime)
        self.assertNotIn("ProbeSelection(",runtime)
        self.assertIn("poll_router_trackers(",runtime)


if __name__=="__main__":
    unittest.main()
