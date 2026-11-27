"""System Globals repository contract."""
from pathlib import Path
import os
import subprocess
import sys
from validators.common import fail, require_files, load_yaml

def validate_system_globals(root, app, context):
    c=context["config"]
    product="digitalhouses_system_globals_app"
    if c.get("slug")!=product or c.get("image")!="ghcr.io/digitalhouses/"+product:
        fail("System Globals canonical identity mismatch")
    if not c.get("ingress") or c.get("panel_admin") is not True or c.get("homeassistant_api") is not True:
        fail("System Globals ingress/read-only readiness contract missing")
    if c.get("options",{}).get("telemetry_enabled") is not False:
        fail("System Globals requires explicit telemetry acceptance")
    if c.get("boot")!="manual" or c.get("stage")!="experimental":
        fail("System Globals initial migration must be manual/experimental")
    require_files(root,[app/p for p in ("rootfs/app/core.py","rootfs/app/runtime.py","rootfs/app/service.py",
                  "rootfs/app/gates.py","rootfs/app/discovery.py","rootfs/app/index.html",
                  "rootfs/app/ingress.py","rootfs/app/lifecycle.py","rootfs/app/telemetry.py",
                  "tests/test_core.py","tests/test_gates.py","tests/test_mqtt_integration.py",
                  "tests/test_service.py","tests/test_telemetry.py","dashboards/ru/10_system_globals.yaml",
                  "packages/common/dh_system_globals_app.yaml","examples/lovelace/system_globals_card_ru.yaml",
                  "icon.png","logo.png")])
    for language in ("en","ru"):
        t=load_yaml(app/f"translations/{language}.yaml",root)["configuration"]
        if set(t)!=set(c["schema"]):
            fail("System Globals missing config translations")
    v=load_yaml(app/"dashboards/ru/10_system_globals.yaml",root)
    if v.get("path")!="system-globals" or v.get("type")!="sections":
        fail("System Globals canonical View path/shape")
    ref=load_yaml(app/"examples/lovelace/system_globals_card_ru.yaml",root)
    if v["sections"][0]["cards"][1]!=ref:
        fail("System Globals canonical status card diverged")
    env=dict(os.environ,PYTHONPATH=str(app/"rootfs/app"))
    # Preserve caller's dependency search paths (isolated local validation).
    if os.environ.get("PYTHONPATH"):
        env["PYTHONPATH"]+=os.pathsep+os.environ["PYTHONPATH"]
    p=subprocess.run([sys.executable,"-m","unittest","discover","-s",str(app/"tests"),"-v"],env=env,capture_output=True,text=True)
    if p.returncode:
        fail("System Globals tests failed:\n"+p.stdout+p.stderr)
