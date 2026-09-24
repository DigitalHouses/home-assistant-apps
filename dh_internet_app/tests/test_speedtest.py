from __future__ import annotations

import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from speedtest import parse_result, parse_server_list


class SpeedtestTests(unittest.TestCase):
    def test_parse_result(self) -> None:
        result = parse_result(
            {
                "type": "result",
                "download": {"bandwidth": 12_500_000},
                "upload": {"bandwidth": 6_250_000},
                "ping": {"latency": 12.34, "jitter": 1.25},
                "packetLoss": 0.5,
                "isp": "Example ISP",
                "interface": {"externalIp": "203.0.113.10"},
                "server": {
                    "id": 12345,
                    "name": "Example Server",
                    "location": "Almaty",
                    "country": "Kazakhstan",
                },
                "result": {"url": "https://www.speedtest.net/result/1"},
            }
        )
        self.assertEqual(result["download_mbps"], 100.0)
        self.assertEqual(result["upload_mbps"], 50.0)
        self.assertEqual(result["ping_ms"], 12.34)
        self.assertEqual(result["jitter_ms"], 1.25)
        self.assertEqual(result["packet_loss_pct"], 0.5)
        self.assertEqual(result["provider"], "Example ISP")
        self.assertEqual(result["server_id"], 12345)
        self.assertEqual(result["server"], "Example Server — Almaty, Kazakhstan")
        self.assertEqual(result["status"], "success")
        self.assertIsNotNone(result["tested_at"])

    def test_parse_server_list(self) -> None:
        servers = parse_server_list(
            "12345  Example ISP  Almaty  Kazakhstan\n"
            "67890  Other ISP  Astana  Kazakhstan\n"
        )
        self.assertEqual([item["id"] for item in servers], [12345, 67890])

    def test_rejects_missing_result_shape(self) -> None:
        with self.assertRaises(RuntimeError):
            parse_result({"type": "log"})


if __name__ == "__main__":
    unittest.main()
