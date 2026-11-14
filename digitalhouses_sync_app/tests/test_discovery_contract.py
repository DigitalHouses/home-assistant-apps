import json
import tempfile
import unittest
from pathlib import Path

from discovery_contract import (
    DiscoveryError, ProductSources, canonical_repository,
    parse_sync_topic, validate_sync_message,
)

PVE = "DigitalHouses/Global/digitalhouses_pve_agent/server-1/sync"
PLEX = "DigitalHouses/Global/digitalhouses_plex_agent/sync"
APP = "DigitalHouses/Global/digitalhouses_sync_app/sync"


def metadata(**fields):
    base = {
        "schema": 1,
        "product_id": "digitalhouses_pve_agent",
        "type": "agent",
        "version": "0.5.88",
        "repository": "https://github.com/DigitalHouses/home-assistant-apps",
        "product_path": "digitalhouses_pve_agent",
    }
    base.update(fields)
    return json.dumps(base)


class DiscoveryContractTests(unittest.TestCase):
    def test_accepted_digitalhouses_repository_and_case(self):
        for url in (
            "https://github.com/DigitalHouses/home-assistant-apps",
            "https://github.com/digitalhouses/new-agent",
            "https://GITHUB.COM/DigitalHouses/another_repo",
        ):
            with self.subTest(url=url):
                self.assertTrue(canonical_repository(url).startswith(
                    "https://github.com/DigitalHouses/"
                ))

    def test_repository_host_and_owner_bypass_attempts_blocked(self):
        bad = (
            "https://github.com/OtherUser/repo",
            "https://github.com/DigitalHouses-malicious/repo",
            "https://github.com/DigitalHouses/repo/../../OtherUser/repo",
            "https://github.com@evil.example/repo",
            "http://github.com/DigitalHouses/repo",
            "https://github.com.evil.example/DigitalHouses/repo",
            "https://evil.example/github.com/DigitalHouses/repo",
            "https://github.com:443/DigitalHouses/repo",
            "https://github.com/DigitalHouses/repo?redirect=evil",
            "https://github.com/DigitalHouses/repo#fragment",
            "https://github.com/DigitalHouses/repo/",
            "https://github.com/DigitalHouses/%2e%2e",
            "https://github.com/DigitalHouses/%2Frepo",
            "https://github.com/DigitalHouses\\@evil.example/repo",
            "https://github.com/DigitalHouses/..",
            "https://github.com/DigitalHouses/.",
            "https://github.com/DigitalHouses/repo.git",
            "https://github.com/DigitalHоuses/repo",  # Cyrillic 'о'
            " https://github.com/DigitalHouses/repo",
            "https://github.com/DigitalHouses/repo\n",
        )
        for url in bad:
            with self.subTest(url=url):
                with self.assertRaises(DiscoveryError):
                    canonical_repository(url)

    def test_mqtt_topic_binds_the_identity(self):
        self.assertEqual(
            parse_sync_topic(PVE), ("digitalhouses_pve_agent", "server-1")
        )
        self.assertEqual(
            parse_sync_topic(PLEX), ("digitalhouses_plex_agent", "default")
        )
        for bad in (
            "DigitalHouses/Global/evil_agent/sync",
            "DigitalHouses/Global/digitalhouses_pve_agent/x/y/sync",
            "DigitalHouses/Global/digitalhouses_pve_agent/x/../sync",
            "DigitalHouses/Global/digitalhouses_pve_agent/+/sync",
            "DigitalHouses/Global/digitalhouses_pve_agent/x/availability",
        ):
            self.assertIsNone(parse_sync_topic(bad))

    def test_good_metadata_returns_structured_repo(self):
        key, value = validate_sync_message(PVE, metadata())
        self.assertEqual(key, "digitalhouses_pve_agent/server-1")
        self.assertEqual(value["repository"], "https://github.com/DigitalHouses/home-assistant-apps")
        self.assertEqual(value["product_path"], "digitalhouses_pve_agent")

    def test_no_other_org_even_if_topic_looks_legitimate(self):
        for url in (
            "https://github.com/OtherUser/repo",
            "https://github.com/DigitalHouses-malicious/repo",
        ):
            with self.assertRaises(DiscoveryError):
                validate_sync_message(PVE, metadata(repository=url))

    def test_topic_and_payload_mismatch_blocked(self):
        with self.assertRaises(DiscoveryError):
            validate_sync_message(PVE, metadata(product_id="digitalhouses_plex_agent"))
        with self.assertRaises(DiscoveryError):
            validate_sync_message(PVE, metadata(type="app"))
        with self.assertRaises(DiscoveryError):
            validate_sync_message(PVE, metadata(product_path="../secret"))
        with self.assertRaises(DiscoveryError):
            validate_sync_message(PVE, metadata(product_path="digitalhouses_plex_agent"))
        with self.assertRaises(DiscoveryError):
            validate_sync_message(PVE, metadata(version="0.5.88/../../"))
        with self.assertRaises(DiscoveryError):
            validate_sync_message(PVE, metadata(schema=True))

    def test_independent_repository_can_use_root(self):
        src = metadata(
            repository="https://github.com/DigitalHouses/pve-agent",
            product_path="."
        )
        key, value = validate_sync_message(PVE, src)
        self.assertEqual(value["product_path"], ".")

    def test_unsupported_schema_and_oversized_json_blocked(self):
        for payload in ("", "[]", "{broken}", metadata(schema=2), "A" * 4097):
            with self.subTest(payload=payload[:12]):
                with self.assertRaises(DiscoveryError):
                    validate_sync_message(PVE, payload)

    def test_product_sources_retained_and_revalidated_on_load(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "sources.json"
            source = ProductSources(path)
            self.assertTrue(source.apply(PVE, metadata()))
            self.assertFalse(source.apply(PVE, metadata()))
            with self.assertRaises(DiscoveryError):
                source.apply(PVE, metadata(repository="https://attacker.example/repo"))
            source.save()
            restored = ProductSources(path)
            self.assertEqual(restored.snapshot(), source.snapshot())
            bad = restored.snapshot()
            bad["digitalhouses_pve_agent/server-1"]["repository"] = (
                "https://attacker.example/repo"
            )
            path.write_text(json.dumps(bad))
            self.assertEqual(ProductSources(path).snapshot(), {})

    def test_untrusted_product_metadata_cannot_choose_git_revision(self):
        # No arbitrary Git commit/ref, download URL or YAML body is accepted
        # as the source of truth for the SyncEngine pinned pilot.
        msg = json.loads(metadata())
        msg["commit"] = "untrusted-branch"
        msg["download_url"] = "https://evil.example/config.yaml"
        _, value = validate_sync_message(PVE, json.dumps(msg))
        self.assertNotIn("commit", value)
        self.assertNotIn("download_url", value)


if __name__ == "__main__":
    unittest.main()
