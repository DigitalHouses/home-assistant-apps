import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from validators.common import ValidationError, parse_application_metadata
from validators.types.haos_addon import validate_haos_addon
from validators.types.linux_agent import validate_linux_agent


class MetadataTests(unittest.TestCase):
    def test_flat_metadata_parses_type(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "digitalhouses.app"
            path.write_text(
                "# DigitalHouses metadata\n\n type = linux_agent \n",
                encoding="utf-8",
            )
            self.assertEqual(
                parse_application_metadata(path),
                {"type": "linux_agent"},
            )

    def test_duplicate_metadata_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "digitalhouses.app"
            path.write_text(
                "type = haos_addon\ntype = linux_agent\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValidationError, "duplicate key"):
                parse_application_metadata(path)

    def test_unknown_application_type_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "digitalhouses.app"
            path.write_text("type = mystery\n", encoding="utf-8")
            with self.assertRaisesRegex(
                ValidationError,
                "unsupported application type",
            ):
                parse_application_metadata(path)


class TypeContractTests(unittest.TestCase):
    def _write(self, path: Path, text: str = "") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_minimal_haos_addon_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / "digitalhouses_example"
            self._write(
                app / "config.yaml",
                "version: 1.2.3\nslug: digitalhouses_example\narch:\n  - amd64\n",
            )
            self._write(
                app / "Dockerfile",
                'ARG BUILD_VERSION="1.2.3"\nARG BUILD_ARCH\n',
            )
            self._write(app / "DOCS.md", "# Docs\n")
            self._write(app / "CHANGELOG.md", "## 1.2.3\n")
            self._write(app / "rootfs/run.sh", "#!/usr/bin/env bash\n")
            self._write(app / "rootfs/app/app.py", "pass\n")
            self._write(app / "translations/en.yaml", "configuration: {}\n")
            self._write(app / "translations/ru.yaml", "configuration: {}\n")
            (app / "images").mkdir(parents=True)

            context = validate_haos_addon(root, app)
            self.assertEqual(context["version"], "1.2.3")

    def test_haos_version_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / "digitalhouses_example"
            self._write(
                app / "config.yaml",
                "version: 1.2.3\nslug: digitalhouses_example\narch:\n  - amd64\n",
            )
            self._write(
                app / "Dockerfile",
                'ARG BUILD_VERSION="1.2.2"\nARG BUILD_ARCH\n',
            )
            self._write(app / "DOCS.md", "# Docs\n")
            self._write(app / "CHANGELOG.md", "## 1.2.3\n")
            self._write(app / "rootfs/run.sh", "#!/usr/bin/env bash\n")
            self._write(app / "rootfs/app/app.py", "pass\n")
            self._write(app / "translations/en.yaml", "configuration: {}\n")
            self._write(app / "translations/ru.yaml", "configuration: {}\n")
            (app / "images").mkdir(parents=True)

            with self.assertRaisesRegex(
                ValidationError,
                "does not match config version",
            ):
                validate_haos_addon(root, app)

    def test_minimal_linux_agent_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / "digitalhouses_example"
            self._write(app / "VERSION", "0.1.0\n")
            self._write(app / "CHANGELOG.md", "## 0.1.0\n")
            self._write(app / "install.sh", "#!/usr/bin/env bash\n")
            self._write(app / "app/app.py", "pass\n")
            self._write(
                app / "systemd/digitalhouses_example.service",
                "[Service]\nExecStart=/bin/true\n",
            )

            context = validate_linux_agent(root, app)
            self.assertEqual(context["version"], "0.1.0")

    def test_linux_agent_requires_systemd_service(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / "digitalhouses_example"
            self._write(app / "VERSION", "0.1.0\n")
            self._write(app / "CHANGELOG.md", "## 0.1.0\n")
            self._write(app / "install.sh", "#!/usr/bin/env bash\n")
            self._write(app / "app/app.py", "pass\n")
            (app / "systemd").mkdir(parents=True)

            with self.assertRaisesRegex(ValidationError, r"\.service"):
                validate_linux_agent(root, app)


if __name__ == "__main__":
    unittest.main()
