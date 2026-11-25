"""Runtime entrypoint smoke verification; never enter an MQTT loop in CI."""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


class RuntimeEntrypointTests(TestCase):
    def test_entrypoint_requires_version(self):
        path = Path(__file__).resolve().parents[1] / "rootfs" / "app" / "app.py"
        spec = importlib.util.spec_from_file_location("aqara_app_entrypoint", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        # Runtime has local Python dependencies; configured CI PYTHONPATH loads them.
        obj = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(obj)
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "APP_VERSION"):
                obj.main()
