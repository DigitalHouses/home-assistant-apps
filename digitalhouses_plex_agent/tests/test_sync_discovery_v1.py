"""DH Sync Discovery Contract v1: Plex product source over the existing MQTT."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

from app.build_info import load_build_info
from app.config import load_config
from app.discovery import (
    SYNC_PRODUCT_ID,
    SYNC_REPOSITORY,
    build_discovery_payload,
    build_sync_payload,
    build_topics,
)
from app.models import BuildInfo
from app.mqtt_bridge import MqttBridge

PRODUCT = Path(__file__).resolve().parents[1]
REGISTRY = PRODUCT.parent / "digitalhouses-stats/digitalhouses_stats/product_registry.json"
EXPECTED_KEYS = {"schema", "product_id", "type", "version", "repository", "product_path"}


def _is_exact_organization_repo(url: str) -> bool:
    """Structural owner check, mirroring the DH Sync contract's security rule."""
    if not url.isascii() or any(char.isspace() for char in url):
        return False
    if any(char in url for char in ("\\", "%")):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    names = parts.path.split("/")
    return (
        parts.scheme == "https"
        and parts.netloc.lower() == "github.com"
        and parts.username is None
        and parts.password is None
        and parts.port is None
        and not parts.query
        and not parts.fragment
        and len(names) == 3
        and names[0] == ""
        and names[1].casefold() == "digitalhouses"
        and names[2] not in ("", ".", "..")
        and all(c.isascii() and (c.isalnum() or c in "._-") for c in names[2])
    )


class DiscoverySourceContractTests(unittest.TestCase):
    def config(self, instance="plex", prefix=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = Path(tmp.name) / "agent.ini"
        p.write_text(
            f"[general]\ninstance_id = {instance}\n[mqtt]\nhost = broker\n"
            + (f"topic_prefix = {prefix}\n" if prefix else ""),
            encoding="utf-8",
        )
        return load_config(p)

    def test_canonical_registry_identity_and_source(self):
        entry = next(x for x in json.loads(REGISTRY.read_text())["products"]
                     if x["id"] == SYNC_PRODUCT_ID)
        self.assertEqual(entry["type"], "agent")
        self.assertEqual(entry["repository_directory"], SYNC_PRODUCT_ID)
        self.assertEqual(entry["release"]["version_source"], "version_file")
        self.assertEqual(SYNC_REPOSITORY,
                         "https://github.com/DigitalHouses/home-assistant-apps")

    def test_default_and_custom_instance_topic_and_legacy_topics(self):
        default = build_topics(self.config())
        self.assertEqual(default.sync,
                         "DigitalHouses/Global/digitalhouses_plex_agent/sync")
        self.assertEqual(default.app_availability,
                         "DigitalHouses/Global/digitalhouses_plex_agent/availability")
        self.assertEqual(default.discovery,
                         "homeassistant/device/digitalhouses_plex_agent_plex/config")
        other = build_topics(self.config("plex_guest"))
        self.assertEqual(other.sync,
                         "DigitalHouses/Global/digitalhouses_plex_agent/plex_guest/sync")
        self.assertEqual(other.app_availability,
                         "DigitalHouses/Global/digitalhouses_plex_agent/plex_guest/availability")
        custom = build_topics(self.config("plex_guest", "DigitalHouses/Custom/Plex"))
        self.assertEqual(custom.sync, other.sync)
        self.assertEqual(custom.app_availability,
                         "DigitalHouses/Custom/Plex/plex_guest/availability")

    def test_payload_exact_fields_type_and_runtime_version(self):
        installed = load_build_info(PRODUCT)
        payload = build_sync_payload(installed)
        self.assertEqual(set(payload), EXPECTED_KEYS)
        self.assertEqual(payload["schema"], 1)
        self.assertIs(type(payload["schema"]), int)
        self.assertEqual(payload["product_id"], SYNC_PRODUCT_ID)
        self.assertEqual(payload["type"], "agent")
        self.assertEqual(payload["version"], installed.version)
        self.assertEqual(payload["product_path"], SYNC_PRODUCT_ID)
        self.assertTrue(_is_exact_organization_repo(payload["repository"]))
        self.assertEqual(build_sync_payload(BuildInfo("1.2.3","release","sha"))["version"],"1.2.3")
        self.assertNotIn("commit", payload)
        for forbidden in ("password","token","ip","username","hostname","secret",
                          "mqtt","customer","serial","instance_id"):
            self.assertNotIn(forbidden,payload)
        self.assertNotIn("192.168.",json.dumps(payload))
        self.assertNotIn("MQTT_",json.dumps(payload))

    def test_structural_repository_allowlist_rejects_spoofs(self):
        self.assertTrue(_is_exact_organization_repo(SYNC_REPOSITORY))
        self.assertTrue(_is_exact_organization_repo(
            "https://github.com/digitalhouses/another-agent"))
        for bad in (
            "https://github.com/OtherUser/repo",
            "https://github.com/DigitalHouses-malicious/repo",
            "https://github.com/DigitalHouses/repo/../../OtherUser/repo",
            "https://github.com@evil.example/repo",
            "https://github.com.evil.example/DigitalHouses/repo",
            "http://github.com/DigitalHouses/repo",
            "https://github.com:443/DigitalHouses/repo",
            "https://github.com/DigitalHouses/repo?foo=bar",
            "https://github.com/DigitalHouses/repo#rev",
            "https://github.com/DigitalHouses/%2e%2e",
        ):
            with self.subTest(url=bad):
                self.assertFalse(_is_exact_organization_repo(bad))

    def test_home_assistant_discovery_remains_unchanged(self):
        cfg = self.config()
        payload = build_discovery_payload(cfg,BuildInfo("0.8.17","tag","sha"))
        self.assertEqual(payload["device"]["identifiers"],
                         ["digitalhouses_plex_agent_plex"])
        components = payload["components"]
        self.assertEqual(components["agent_version"]["default_entity_id"],
                         "sensor.dh_plex_agent_version")
        self.assertEqual(components["agent_started_at"]["default_entity_id"],
                         "sensor.dh_plex_agent_started_at")
        self.assertNotIn("sync", components)


class SyncPublishTests(unittest.TestCase):
    def new_bridge(self, *, with_metadata=True, instance="plex"):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            path.write_text(
                f"[general]\ninstance_id = {instance}\n"
                "[mqtt]\nhost = broker\n", encoding="utf-8",
            )
            config = load_config(path)
        topics=build_topics(config)
        discovery=build_discovery_payload(config,BuildInfo("0.8.17","tag","sha"))
        payload=build_sync_payload(BuildInfo("0.8.17","tag","sha"))
        client=Mock()
        client.publish.return_value=Mock(rc=0,mid=17)
        with patch("app.mqtt_bridge.mqtt.Client",return_value=client):
            bridge=MqttBridge(config,topics,discovery,
                              sync_payload=payload if with_metadata else None)
        return bridge,client,payload

    @staticmethod
    def connect(bridge,client,success=True):
        bridge._on_connect(client,None,SimpleNamespace(),
                           SimpleNamespace(is_failure=not success),None)

    def test_retained_qos1_publish_on_connect_reconnect_without_wait(self):
        bridge,client,payload=self.new_bridge()
        self.connect(bridge,client)
        first=list(client.publish.call_args_list)
        sync=[c for c in first if c.args and c.args[0]==bridge.topics.sync]
        self.assertEqual(len(sync),1)
        self.assertEqual(json.loads(sync[0].kwargs["payload"]),payload)
        self.assertEqual(sync[0].kwargs["qos"],1)
        self.assertIs(sync[0].kwargs["retain"],True)
        client.publish.return_value.wait_for_publish.assert_not_called()
        avail=[c for c in first if c.args and c.args[0]==bridge.topics.app_availability]
        self.assertEqual(len(avail),1)
        self.assertEqual(avail[0].kwargs["qos"],0)
        self.assertTrue(avail[0].kwargs["retain"])
        self.assertEqual(avail[0].kwargs["payload"],"online")
        bridge._on_disconnect(client,None,SimpleNamespace(),"lost",None)
        self.connect(bridge,client)
        sync=[c for c in client.publish.call_args_list
              if c.args and c.args[0]==bridge.topics.sync]
        self.assertEqual(len(sync),2)
        self.assertEqual([c.kwargs["payload"] for c in sync],
                         [sync[0].kwargs["payload"]]*2)
        self.assertEqual(client.subscribe.call_count,10)
        self.assertEqual(bridge.config.mqtt.keepalive_seconds,60)

    def test_multi_instance_publish_and_updated_version_on_next_connect(self):
        bridge,client,_=self.new_bridge(instance="plex_guest")
        self.connect(bridge,client)
        first=[c for c in client.publish.call_args_list
               if c.args and c.args[0]==bridge.topics.sync]
        self.assertEqual(len(first),1)
        self.assertEqual(bridge.topics.sync,
                         "DigitalHouses/Global/digitalhouses_plex_agent/plex_guest/sync")
        self.assertEqual(json.loads(first[0].kwargs["payload"])["version"],"0.8.17")
        bridge._on_disconnect(client,None,SimpleNamespace(),"lost",None)
        # A normal agent upgrade restarts this process; simulate the resulting
        # next-connect payload without an actual installer or broker.
        bridge.sync_payload=build_sync_payload(BuildInfo("0.8.18","tag","sha"))
        self.connect(bridge,client)
        sent=[c for c in client.publish.call_args_list
              if c.args and c.args[0]==bridge.topics.sync]
        self.assertEqual(len(sent),2)
        self.assertEqual(json.loads(sent[1].kwargs["payload"])["version"],"0.8.18")
        self.assertEqual(sent[1].kwargs["qos"],1)
        self.assertTrue(sent[1].kwargs["retain"])

    def test_rejected_connection_and_offline_do_not_publish_sync(self):
        bridge,client,_=self.new_bridge()
        self.connect(bridge,client,success=False)
        self.assertEqual(client.publish.call_count,0)
        self.assertFalse(bridge.connected.is_set())
        self.assertEqual(bridge.diagnostics()["state"],"MQTT_PAUSED")
        self.assertEqual(bridge.client.reconnect_delay_set.call_count,1)
        self.assertEqual(bridge.client.reconnect_delay_set.call_args.args,(60,60))
        self.assertEqual(bridge.client.connect_timeout,5.0)

    def test_legacy_callers_do_not_require_new_argument(self):
        bridge,client,_=self.new_bridge(with_metadata=False)
        self.connect(bridge,client)
        self.assertEqual(
            [c.args[0] for c in client.publish.call_args_list],
            [bridge.topics.app_availability],
        )
        self.assertEqual(client.will_set.call_args.kwargs,
                         {"payload":"offline","qos":0,"retain":True})
        self.assertEqual(client.will_set.call_args.args[0],
                         bridge.topics.app_availability)
