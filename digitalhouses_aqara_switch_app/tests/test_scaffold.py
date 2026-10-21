"""Smoke tests for deliberately inert Aqara Switch App bootstrap."""

import importlib.util
import io
import os
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


class ScaffoldTests(TestCase):
    @staticmethod
    def entrypoint():
        path = Path(__file__).resolve().parents[1] / "rootfs/app/app.py"
        spec = importlib.util.spec_from_file_location("aqara_switch_entrypoint", path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Failed to load Aqara Switch App")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_scaffold_is_not_an_active_controller(self):
        buffer = io.StringIO()
        with patch.dict(os.environ, {"APP_VERSION": "0.1.0"}), redirect_stdout(buffer):
            self.assertEqual(self.entrypoint().main(), 0)
        self.assertIn("no scan or device control implemented", buffer.getvalue())

    def test_missing_version_is_an_error(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "APP_VERSION"):
                self.entrypoint().main()
