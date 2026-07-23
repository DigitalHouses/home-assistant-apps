from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "digitalhouses_speedtest"

required = [
    ROOT / "repository.yaml",
    ROOT / "README.md",
    ROOT / "LICENSE",
    APP / "config.yaml",
    APP / "Dockerfile",
    APP / "README.md",
    APP / "DOCS.md",
    APP / "CHANGELOG.md",
    APP / "rootfs" / "run.sh",
    APP / "rootfs" / "app" / "app.py",
    APP / "rootfs" / "app" / "core.py",
    APP / "translations" / "en.yaml",
    ROOT / "examples" / "packages" / "internet_speedtest_package.yaml",
]

missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
if missing:
    raise SystemExit("Missing required files: " + ", ".join(missing))

for path in [
    ROOT / "repository.yaml",
    APP / "config.yaml",
    APP / "translations" / "en.yaml",
    ROOT / "examples" / "packages" / "internet_speedtest_package.yaml",
]:
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if not isinstance(data, dict):
        raise SystemExit(f"{path.relative_to(ROOT)} must contain a YAML mapping")

config = yaml.safe_load((APP / "config.yaml").read_text(encoding="utf-8"))
assert config["version"] == "1.0.0"
assert config["stage"] == "stable"
assert config["arch"] == ["amd64"]
assert config["slug"] == "digitalhouses_speedtest"
assert config["services"] == ["mqtt:need"]

package = yaml.safe_load(
    (ROOT / "examples" / "packages" / "internet_speedtest_package.yaml").read_text(
        encoding="utf-8"
    )
)
entities = package["recorder"]["include"]["entities"]
assert len(entities) == 18
assert len(entities) == len(set(entities))

print("Repository validation passed")
