"""Проверка контракта обязательного согласия для Apps и Agents."""
import ast
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
MESSAGE = "Statistics collection consent not granted. Stopping application."
DESCRIPTION = "Consent to collect statistics (product name, version, installation ID)."


class Log:
    def __init__(self):
        self.errors = []

    def error(self, message):
        self.errors.append(message)


class ConsentTests(unittest.TestCase):
    def test_apps_guard_and_configuration(self):
        for name, cls, first_effect in (
            ("recorder", "DatabaseMonitorApp", "adapter"),
            ("internet", "InternetApp", "started_at"),
            ("backblaze", "BackblazeMonitorApp", "api"),
        ):
            with self.subTest(name=name):
                base = ROOT / f"digitalhouses_{name}_app"
                options = (base / "config.yaml").read_text()
                self.assertIn("  telemetry_enabled: false", options)
                self.assertIn("  telemetry_enabled: bool", options)
                for lang in ("en", "ru"):
                    self.assertIn(
                        DESCRIPTION,
                        (base / "translations" / f"{lang}.yaml").read_text(),
                    )
                module = ast.parse((base / "rootfs/app/app.py").read_text())
                cls_ast = next(n for n in module.body
                               if isinstance(n, ast.ClassDef) and n.name == cls)
                init = next(n for n in cls_ast.body
                            if isinstance(n, ast.FunctionDef) and n.name == "__init__")
                guard = next(n for n in init.body if isinstance(n, ast.If)
                             and ast.unparse(n.test) == "not self.config.telemetry_enabled")
                effect = next(i for i, n in enumerate(init.body)
                              if isinstance(n, ast.Assign)
                              and any(isinstance(t, ast.Attribute)
                                      and t.attr == first_effect for t in n.targets))
                self.assertLess(init.body.index(guard), effect)
                snippet = compile(
                    ast.fix_missing_locations(ast.Module(body=[guard], type_ignores=[])),
                    str(base / "rootfs/app/app.py"), "exec",
                )
                for enabled in (False, True):
                    log = Log()
                    self_obj = SimpleNamespace(
                        config=SimpleNamespace(telemetry_enabled=enabled), log=log
                    )
                    if enabled:
                        exec(snippet, {"self": self_obj})
                        self.assertEqual(log.errors, [])
                    else:
                        with self.assertRaises(SystemExit) as stopped:
                            exec(snippet, {"self": self_obj})
                        self.assertEqual(stopped.exception.code, 1)
                        self.assertEqual(log.errors, [MESSAGE])

    def test_agents_guard(self):
        for name, filename, first_effect in (
            ("plex", "app.py", "build"),
            ("pve", "main.py", "shutdown_history_tracker"),
        ):
            with self.subTest(name=name):
                file = ROOT / f"digitalhouses_{name}_agent/app/{filename}"
                module = ast.parse(file.read_text())
                run = next(n for n in module.body
                           if isinstance(n, ast.FunctionDef) and n.name == "run")
                guard = next(n for n in run.body if isinstance(n, ast.If)
                             and ast.unparse(n.test) == "not config.telemetry.enabled")
                effect = next(i for i, n in enumerate(run.body)
                              if isinstance(n, ast.Assign)
                              and any(isinstance(t, ast.Name) and t.id == first_effect
                                      for t in n.targets))
                self.assertLess(run.body.index(guard), effect)
                wrapper = ast.FunctionDef(
                    name="check",
                    args=ast.arguments(posonlyargs=[], args=[], vararg=None,
                                       kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[]),
                    body=[guard, ast.Return(value=ast.Constant(None))],
                    decorator_list=[], returns=None, type_comment=None, type_params=[],
                )
                code = compile(
                    ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[])),
                    str(file), "exec",
                )
                for enabled in (False, True):
                    log = Log()
                    namespace = {
                        "config": SimpleNamespace(telemetry=SimpleNamespace(enabled=enabled)),
                        "log": log,
                    }
                    exec(code, namespace)
                    self.assertEqual(namespace["check"](), None if enabled else 1)
                    self.assertEqual(log.errors, [] if enabled else [MESSAGE])

    def test_installers_preserve_old_service_on_refusal_and_write_consent(self):
        for name in ("plex", "pve"):
            with self.subTest(name=name):
                source = (ROOT / f"digitalhouses_{name}_agent/install.sh").read_text()
                self.assertLess(source.index("CONSENT_NEEDS_SAVE=0"),
                                source.index("need_apt=0"))
                self.assertLess(source.index("persist_telemetry_consent"),
                                source.index("systemctl restart"))
                self.assertIn(
                    "Consent to collect statistics (product name, version, installation ID)? [y/N]",
                    source,
                )
                helpers = ("telemetry_consent_granted() {"
                           + source.split("telemetry_consent_granted() {", 1)[1]
                           .split("CONSENT_NEEDS_SAVE=0", 1)[0])
                with tempfile.TemporaryDirectory() as tmp:
                    file = Path(tmp) / "agent.conf"
                    for original, consent in (
                        ("[general]\nname = test\n", False),
                        ("[general]\nname = test\n[telemetry]\nenabled = false\n", False),
                        ("[general]\nname = test\n[telemetry]\nenabled = true\n", True),
                    ):
                        file.write_text(original)
                        check = subprocess.run(
                            ["bash", "-c", helpers + '\ntelemetry_consent_granted "$1"',
                             "test", str(file)], capture_output=True, text=True,
                        )
                        self.assertEqual(check.returncode == 0, consent, check.stderr)
                        if not consent:
                            write = subprocess.run(
                                ["bash", "-c", helpers + '\npersist_telemetry_consent "$1"',
                                 "test", str(file)], capture_output=True, text=True,
                            )
                            self.assertEqual(write.returncode, 0, write.stderr)
                            self.assertIn("name = test", file.read_text())
                            self.assertIn("enabled = true", file.read_text())
                            retry = subprocess.run(
                                ["bash", "-c", helpers + '\ntelemetry_consent_granted "$1"',
                                 "test", str(file)], capture_output=True, text=True,
                            )
                            self.assertEqual(retry.returncode, 0, retry.stderr)


if __name__ == "__main__":
    unittest.main()
