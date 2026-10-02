"""Statistics collection consent regression tests for Internet App."""
from __future__ import annotations

import importlib.util
import logging
import os
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


APP_DIR = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from config import parse_options


def load_app_without_mqtt_dependency():
    """Load startup code without requiring paho-mqtt in the CI test environment."""
    paho = ModuleType("paho")
    mqtt = ModuleType("paho.mqtt")
    client = ModuleType("paho.mqtt.client")
    paho.mqtt = mqtt
    mqtt.client = client
    spec = importlib.util.spec_from_file_location(
        "internet_app_consent_test", APP_DIR / "app.py"
    )
    module = importlib.util.module_from_spec(spec)
    with (
        patch.dict(sys.modules, {
            "paho": paho,
            "paho.mqtt": mqtt,
            "paho.mqtt.client": client,
        }),
        patch.dict(os.environ, {"APP_VERSION": "0.1.21"}),
    ):
        spec.loader.exec_module(module)
    return module


internet_app = load_app_without_mqtt_dependency()


MESSAGE = "Statistics collection consent not granted. Stopping application."


class ConsentTests(unittest.TestCase):
    def test_absent_consent_defaults_to_false(self) -> None:
        self.assertFalse(parse_options({}).telemetry_enabled)

    def test_false_stops_before_loading_state_or_creating_clients(self) -> None:
        for consent in (False, None):
            config = SimpleNamespace(
                telemetry_enabled=consent,
                log_level="info",
            )
            with (
                patch.object(internet_app, "load_config", return_value=config),
                patch.object(internet_app.OutageTracker, "load") as state,
                patch.object(internet_app, "HomeAssistantApi") as ha_api,
                patch.object(internet_app, "TelemetryClient") as telemetry,
                patch.object(internet_app, "create_mqtt_client") as mqtt,
                self.assertLogs("digitalhouses_internet_app", level=logging.ERROR) as log,
            ):
                with self.assertRaises(SystemExit) as result:
                    internet_app.InternetApp()
            self.assertEqual(result.exception.code, 1)
            self.assertTrue(any(MESSAGE in entry for entry in log.output))
            state.assert_not_called()
            ha_api.assert_not_called()
            telemetry.assert_not_called()
            mqtt.assert_not_called()

    def test_true_enters_normal_runtime(self) -> None:
        config = SimpleNamespace(telemetry_enabled=True, log_level="info")
        with (
            patch.object(internet_app, "load_config", return_value=config),
            patch.object(
                internet_app.OutageTracker,
                "load",
                side_effect=RuntimeError("state initialization reached"),
            ) as state,
        ):
            with self.assertRaisesRegex(RuntimeError, "state initialization reached"):
                internet_app.InternetApp()
        state.assert_called_once()

    def test_config_contract_and_release_version(self) -> None:
        root = APP_DIR.parents[1]
        config = (root / "config.yaml").read_text(encoding="utf-8")
        self.assertIn("  telemetry_enabled: false", config)
        self.assertIn("  telemetry_enabled: bool", config)
        self.assertIn("version: 0.1.21", config)
        for locale in ("en", "ru"):
            text = (root / "translations" / f"{locale}.yaml").read_text(encoding="utf-8")
            self.assertIn(
                "description: Consent to collect statistics (product name, version, installation ID).",
                text,
            )


if __name__ == "__main__":
    unittest.main()
