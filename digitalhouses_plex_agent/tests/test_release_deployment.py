import re
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = APP_ROOT / "install.sh"
README = APP_ROOT / "README.md"
VERSION = APP_ROOT / "VERSION"


class ReleaseDeploymentContractTests(unittest.TestCase):
    def test_installer_has_no_main_default_for_production_source(self):
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertNotIn(
            'SOURCE_REF="${DIGITALHOUSES_SOURCE_REF:-main}"',
            installer,
        )
        self.assertIn(
            'SOURCE_REF="${DIGITALHOUSES_SOURCE_REF:-}"',
            installer,
        )

    def test_installer_requires_canonical_plex_release_tag_by_default(self):
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertIn('RELEASE_IDENTIFIER="digitalhouses_plex_agent"', installer)
        self.assertIn(
            'ALLOW_NON_RELEASE_REF="${DIGITALHOUSES_ALLOW_NON_RELEASE_REF:-0}"',
            installer,
        )
        self.assertIn('EXPECTED_VERSION="${BASH_REMATCH[1]}"', installer)
        self.assertIn(
            'if [[ "${ALLOW_NON_RELEASE_REF}" != "1" ]]; then',
            installer,
        )
        self.assertIn(
            'if [[ -n "${EXPECTED_VERSION}" && "${SOURCE_VERSION}" != "${EXPECTED_VERSION}" ]]; then',
            installer,
        )

    def test_installer_separates_repo_source_from_legacy_runtime_identity(self):
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertIn('APP_NAME="digitalhouses_plex_monitoring"', installer)
        self.assertIn('SOURCE_PRODUCT_DIR="digitalhouses_plex_agent"', installer)
        self.assertIn(
            'SOURCE_APP="${tmp_dir}/repo/${SOURCE_PRODUCT_DIR}"',
            installer,
        )

    def test_readme_production_install_uses_current_release_tag(self):
        version = VERSION.read_text(encoding="utf-8").strip()
        expected_tag = f"digitalhouses_plex_agent-v{version}"
        readme = README.read_text(encoding="utf-8")

        self.assertIn(f'RELEASE_TAG="{expected_tag}"', readme)
        self.assertIn(
            "raw.githubusercontent.com/DigitalHouses/home-assistant-apps/"
            "${RELEASE_TAG}/digitalhouses_plex_agent/install.sh",
            readme,
        )
        self.assertIn(
            'DIGITALHOUSES_SOURCE_REF="${RELEASE_TAG}"',
            readme,
        )

    def test_readme_does_not_present_main_as_normal_update_source(self):
        readme = README.read_text(encoding="utf-8")
        self.assertNotIn(
            "Run the same command again to update from `main`.",
            readme,
        )


if __name__ == "__main__":
    unittest.main()
