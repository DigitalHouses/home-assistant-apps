import json
import sys
import tempfile
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from core import (  # noqa: E402
    atomic_write_json,
    build_success_state,
    load_json,
    migrate_state,
    parse_server_list,
)


class CoreTests(unittest.TestCase):
    def test_parse_server_table(self):
        output = """
    ID  Name                           Location             Country
==============================================================================
 38516  Kazakhtelecom                 Almaty               Kazakhstan
 70668  Hoster.KZ                     Almaty               Kazakhstan
"""
        self.assertEqual(
            parse_server_list(output),
            [
                {
                    "id": 38516,
                    "provider": "Kazakhtelecom",
                    "location": "Almaty",
                    "country": "Kazakhstan",
                },
                {
                    "id": 70668,
                    "provider": "Hoster.KZ",
                    "location": "Almaty",
                    "country": "Kazakhstan",
                },
            ],
        )

    def test_build_success_state(self):
        raw = {
            "type": "result",
            "timestamp": "2026-07-24T00:00:00Z",
            "ping": {"jitter": 0.08, "latency": 3.1},
            "download": {"bandwidth": 25_000_000},
            "upload": {"bandwidth": 12_500_000},
            "packetLoss": 0,
            "isp": "Example ISP",
            "interface": {"externalIp": "203.0.113.10"},
            "server": {
                "id": 12345,
                "name": "Example Provider",
                "location": "Almaty",
                "country": "Kazakhstan",
            },
            "result": {"url": "https://www.speedtest.net/result/c/example"},
        }
        state = build_success_state(raw, "2026-07-24T00:00:01Z")
        self.assertEqual(state["download_mbps"], 200.0)
        self.assertEqual(state["upload_mbps"], 100.0)
        self.assertEqual(state["server_id"], "12345")
        self.assertEqual(
            state["server"], "Example Provider — Almaty, Kazakhstan"
        )

    def test_legacy_status_migration(self):
        state = migrate_state({"status": "\u0423\u0441\u043f\u0435\u0448\u043d\u043e", "download_mbps": 100})
        self.assertEqual(state["status"], "Success")
        self.assertEqual(state["download_mbps"], 100)

    def test_atomic_json_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            atomic_write_json(path, {"ok": True})
            self.assertEqual(load_json(path, {}), {"ok": True})
            json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
