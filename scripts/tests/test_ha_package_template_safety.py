"""Guard the normative ban on Jinja tojson in Home Assistant package YAML."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
BANNED = re.compile(r"\|\s*tojson\b", re.IGNORECASE)


class HomeAssistantPackageTemplateSafetyTests(unittest.TestCase):
    def test_no_tojson_filter_in_home_assistant_packages(self):
        files = sorted(
            p for p in ROOT.rglob("*")
            if p.is_file()
            and p.suffix.lower() in {".yaml", ".yml"}
            and "packages" in p.parts
            and not any(part.startswith(".") for part in p.relative_to(ROOT).parts)
        )
        self.assertTrue(files, "No HA package YAML examples found")
        violations = []
        for package in files:
            contents = package.read_text(encoding="utf-8")
            for line_number, line in enumerate(contents.splitlines(), start=1):
                if BANNED.search(line):
                    violations.append(f"{package.relative_to(ROOT)}:{line_number}")
        self.assertEqual([], violations, "Remove tojson from HA package templates")


if __name__ == "__main__":
    unittest.main()
