"""Source admission is ONLY the GitHub owner DigitalHouses."""
import json
import tempfile
import unittest
from pathlib import Path

from discovery_contract import (
    DiscoveryError, ProductSources, canonical_repository,
    parse_sync_topic, safe_product_path, validate_sync_message,
)

PVE = "DigitalHouses/Global/digitalhouses_pve_agent/server-1/sync"
RECORDER = "DigitalHouses/Global/digitalhouses_recorder_app/sync"


def payload(**fields):
    entry = {
        "schema": 1,
        "product_id": "digitalhouses_pve_agent",
        "type": "agent",
        "version": "0.5.89",
        "repository": "https://github.com/DigitalHouses/home-assistant-apps",
        "product_path": "digitalhouses_pve_agent",
    }
    entry.update(fields)
    return json.dumps(entry)


class SourceOwnershipTests(unittest.TestCase):
    def test_accept_any_repository_belonging_to_digitalhouses(self):
        for url in (
            "https://github.com/DigitalHouses/home-assistant-apps",
            "https://github.com/digitalhouses/recorder",
            "https://GITHUB.COM/DigitalHouses/another_repo",
            "https://github.com/DigitalHouses/another_repo/",
        ):
            with self.subTest(url=url):
                self.assertTrue(canonical_repository(url).startswith(
                    "https://github.com/DigitalHouses/"
                ))

    def test_other_owners_and_ambiguous_urls_are_not_admitted(self):
        for bad in (
            "https://github.com/OtherUser/repo",
            "https://github.com/DigitalHouses-malicious/repo",
            "https://github.com/DigitalHouses/repo/../../OtherUser/repo",
            "https://github.com@evil.example/repo",
            "http://github.com/DigitalHouses/repo",
            "https://github.com.evil.example/DigitalHouses/repo",
            "https://github.com:443/DigitalHouses/repo",
            "https://github.com/DigitalHouses/repo?redirect=evil",
            "https://github.com/DigitalHouses/%2e%2e",
            "https://github.com/DigitalHоuses/repo",
            " https://github.com/DigitalHouses/repo",
            "https://github.com/DigitalHouses/repo\n",
            "https://github.com:invalid/DigitalHouses/repo",
        ):
            with self.subTest(bad=bad):
                with self.assertRaises((DiscoveryError, ValueError)):
                    canonical_repository(bad)

    def test_transport_topic_parsing_is_still_bounded(self):
        self.assertEqual(parse_sync_topic(PVE), ("digitalhouses_pve_agent", "server-1"))
        self.assertEqual(parse_sync_topic(RECORDER), ("digitalhouses_recorder_app", "default"))
        self.assertEqual(parse_sync_topic("DigitalHouses/Global/custom_tool/sync"),
                         ("custom_tool", "default"))
        for invalid in ("DigitalHouses/Global/a/b/c/sync",
                        "DigitalHouses/Global/a/+/sync",
                        "DigitalHouses/Global/a/availability"):
            self.assertIsNone(parse_sync_topic(invalid))

    def test_product_version_schema_type_and_path_no_longer_gate(self):
        topic = PVE
        odd = payload(
            schema=200, type="other", version="future-release",
            product_id="unrelated_claim",
            repository="https://github.com/DigitalHouses/anything",
            product_path="../invalid",
        )
        key, val = validate_sync_message(topic, odd)
        self.assertEqual(key, "digitalhouses_pve_agent/server-1")
        self.assertEqual(val["repository"], "https://github.com/DigitalHouses/anything")
        self.assertEqual(val["product_id"], "digitalhouses_pve_agent")
        self.assertEqual(val["version"], "future-release")
        self.assertEqual(val["product_path"], "digitalhouses_pve_agent")
        self.assertEqual(val["type"], "other")

    def test_only_repository_needed_in_valid_json(self):
        identity, info = validate_sync_message(
            RECORDER, '{"repository":"https://github.com/DigitalHouses/custom"}'
        )
        self.assertEqual(identity, "digitalhouses_recorder_app/default")
        self.assertEqual(info["version"], "unknown")
        self.assertEqual(info["product_path"], "digitalhouses_recorder_app")
        self.assertEqual(info["type"], "unknown")

    def test_nested_product_folder_and_dedicated_repo_allowed(self):
        for folder in (".", "digitalhouses_recorder_app", "apps/recorder"):
            _, item = validate_sync_message(
                RECORDER, json.dumps({
                    "repository": "https://github.com/DigitalHouses/recorder",
                    "product_path": folder,
                }),
            )
            self.assertEqual(item["product_path"], folder)
        self.assertEqual(safe_product_path("../secrets", "recorder"), "recorder")

    def test_non_owner_is_always_rejected(self):
        with self.assertRaises(DiscoveryError):
            validate_sync_message(PVE, payload(
                repository="https://github.com/OtherUser/anything"))
        with self.assertRaises(DiscoveryError):
            validate_sync_message(RECORDER, '{"version":"1.0.0"}')

    def test_invalid_transport_messages_are_rejected(self):
        for raw in ("", "[]", "{broken}", "A" * 4097):
            with self.subTest(raw=raw[:12]):
                with self.assertRaises(DiscoveryError):
                    validate_sync_message(PVE, raw)

    def test_snapshot_persistence_and_owner_revalidation(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "sources.json"
            src = ProductSources(path)
            self.assertTrue(src.apply(RECORDER, payload(
                repository="https://github.com/DigitalHouses/recorder")))
            self.assertFalse(src.apply(RECORDER, payload(
                repository="https://github.com/DigitalHouses/recorder")))
            src.save()
            self.assertEqual(ProductSources(path).snapshot(), src.snapshot())
            bad = src.snapshot()
            bad["digitalhouses_recorder_app/default"]["repository"] = (
                "https://github.com/attacker/repo"
            )
            path.write_text(json.dumps(bad))
            self.assertEqual(ProductSources(path).snapshot(), {})

    def test_claimed_download_and_revision_are_not_used(self):
        data = json.loads(payload())
        data.update(commit="untrusted", download_url="https://evil.example/file")
        _, val = validate_sync_message(PVE, json.dumps(data))
        self.assertNotIn("commit", val)
        self.assertNotIn("download_url", val)


if __name__ == "__main__":
    unittest.main()
