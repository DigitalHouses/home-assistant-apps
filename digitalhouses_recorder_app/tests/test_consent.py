"""Обязательное согласие на сбор статистики Recorder App."""
from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from test_events import APP_MODULE


ROOT = Path(__file__).resolve().parents[1]
MESSAGE = "Statistics collection consent not granted. Stopping application."


def app_options(consent: bool):
    return SimpleNamespace(
        telemetry_enabled=consent,
        timezone="UTC",
        log_level="info",
        database=object(),
    )


class ConsentTests(TestCase):
    def test_disabled_stops_before_connectors_and_telemetry(self):
        with (
            patch.dict(APP_MODULE.os.environ, {"APP_VERSION": "0.1.19"}),
            patch.object(APP_MODULE, "load_config", return_value=app_options(False)),
            patch.object(APP_MODULE, "create_adapter") as adapter,
            patch.object(APP_MODULE, "TelemetryClient") as telemetry,
            patch.object(APP_MODULE, "StorageCollector") as storage,
            self.assertLogs("digitalhouses_recorder_app", level=logging.ERROR) as log,
        ):
            with self.assertRaises(SystemExit) as result:
                APP_MODULE.DatabaseMonitorApp()
        self.assertEqual(result.exception.code, 1)
        self.assertTrue(any(MESSAGE in line for line in log.output))
        adapter.assert_not_called()
        telemetry.assert_not_called()
        storage.assert_not_called()

    def test_enabled_reaches_normal_runtime(self):
        with (
            patch.dict(APP_MODULE.os.environ, {"APP_VERSION": "0.1.19"}),
            patch.object(APP_MODULE, "load_config", return_value=app_options(True)),
            patch.object(APP_MODULE, "create_adapter", side_effect=RuntimeError("entered runtime")) as adapter,
        ):
            with self.assertRaisesRegex(RuntimeError, "entered runtime"):
                APP_MODULE.DatabaseMonitorApp()
        adapter.assert_called_once()

    def test_configuration_contract_default_and_translations(self):
        config = (ROOT / "config.yaml").read_text(encoding="utf-8")
        self.assertIn("  telemetry_enabled: false", config)
        self.assertIn("  telemetry_enabled: bool", config)
        for lang in ("en", "ru"):
            translation = (ROOT / "translations" / f"{lang}.yaml").read_text(encoding="utf-8")
            self.assertIn(
                "description: Consent to collect statistics (product name, version, installation ID).",
                translation,
            )
        source = (ROOT / "rootfs" / "app" / "app.py").read_text(encoding="utf-8")
        self.assertLess(
            source.index("if not self.config.telemetry_enabled:"),
            source.index("self.adapter = create_adapter("),
        )
        self.assertLess(
            source.index("if not self.config.telemetry_enabled:"),
            source.index("self.telemetry = TelemetryClient("),
        )


if __name__ == "__main__":
    import unittest
    unittest.main()
