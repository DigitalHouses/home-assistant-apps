"""Product-local PBS Agent release contract, no access to other products."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from validators.common import fail, require_files, load_yaml


def validate_pbs_agent(root: Path, app: Path, context: dict[str, Any]) -> None:
    require_files(root, [
        app / "VERSION", app / "install.sh", app / "requirements.txt",
        app / "bin/dh-pbs-agent", app / "systemd/digitalhouses_pbs_agent.service",
        app / "app/collector.py", app / "app/events.py", app / "app/config.py",
        app / "app/cli.py", app / "app/mqtt.py", app / "app/main.py",
        app / "dashboards/ru/13_pbs.yaml",
        app / "packages/locales/ru/dh_pbs_agent_notification_local_package.yaml",
    ])
    if context.get("type") != "linux_agent":
        fail("PBS Agent must remain a Linux Agent")
    view = load_yaml(app / "dashboards/ru/13_pbs.yaml", root)
    if not isinstance(view, dict) or view.get("path") != "dh_pbs_agent":
        fail("PBS Agent must publish one stable dh_pbs_agent View")
    if view.get("type") != "sections" or not isinstance(view.get("sections"), list):
        fail("PBS View must be a standalone Lovelace sections View")
    if "views" in view or "dashboard" in view:
        fail("PBS View must not own Dashboard placement")
    pack = load_yaml(app / "packages/locales/ru/dh_pbs_agent_notification_local_package.yaml", root)
    if not isinstance(pack, dict) or list(pack) != ["dh_pbs_agent_notification_local_package"]:
        fail("PBS Agent notification package must have one stable top-level key")
    source = (app / "app/mqtt.py").read_text(encoding="utf-8")
    if "product_path" not in source or "self.synctopic" not in source:
        fail("PBS Agent must publish retained DH Sync identity")
    if "dashboard" in source.lower():
        fail("PBS Agent MQTT declaration must not control Dashboard placement")
