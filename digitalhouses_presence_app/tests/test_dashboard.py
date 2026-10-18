"""DH Presence dashboard uses only genuinely implemented product operations."""
from pathlib import Path
import json
import re
import shutil
import subprocess
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "examples/lovelace/presence_app_card_ru.yaml"
DASHBOARD = ROOT / "examples/lovelace/dh_presence_app_dashboard.yaml"


def status_js(path: Path, key: str) -> str:
    """Extract the first (aggregate-status) button-card JS template."""
    lines = path.read_text(encoding="utf-8").splitlines()
    pattern = r"^\s*" + (r"- color: \|" if key == "color" else re.escape(key) + r": \|") + r"$"
    for index, line in enumerate(lines):
        if not re.match(pattern, line):
            continue
        indent = len(line) - len(line.lstrip())
        body = []
        for following in lines[index + 1:]:
            if following.strip() and len(following) - len(following.lstrip()) <= indent:
                break
            body.append(following)
        value = textwrap.dedent("\n".join(body)).strip()
        if value.startswith("[[[") and value.endswith("]]]"):
            return value[3:-3].strip()
    raise AssertionError(f"JS template {key} not found in {path}")



class LovelaceCardTests(unittest.TestCase):

    def test_native_supervisor_update_is_reflected_in_primary_status(self):
        """Only Supervisor can authorize installing an App update."""
        for path in (CARD, DASHBOARD):
            code = path.read_text(encoding="utf-8")
            for key in ("icon", "name", "label", "color"):
                expression = status_js(path, key)
                self.assertIn("update.digitalhouses_presence_app_update", expression)
                self.assertIn("binary_sensor.dh_presence_app_update_available", expression)
            self.assertIn("supervisor?.state === 'on'", status_js(path, "icon"))
            self.assertIn("if (newer) return 'Доступна новая версия';", status_js(path, "label"))
            self.assertIn("supervisor?.attributes?.latest_version", status_js(path, "name"))
            self.assertIn("releaseAvailable && valid(checkedLatest)", status_js(path, "name"))
            self.assertIn("const updating = states['update.digitalhouses_presence_app_update']",
                          code)
            self.assertIn("entity: update.digitalhouses_presence_app_update", code)
            self.assertNotIn("entity: binary_sensor.dh_presence_app_update_available\\n"
                             "            state: \"on\"", code)

    def test_card_and_dashboard_status_js_do_not_diverge(self):
        for key in ("icon", "name", "label", "color"):
            with self.subTest(template=key):
                self.assertEqual(status_js(CARD, key), status_js(DASHBOARD, key))

    @unittest.skipUnless(shutil.which("node"), "Node is not available for UI behavior test")
    def test_status_behavior_with_asynchronous_app_and_supervisor_updates(self):
        """Execute real JS templates under the combinations that caused the bug."""
        fragments = {key: status_js(CARD, key)
                     for key in ("icon", "name", "label", "color")}
        script = r"""
const src = JSON.parse(process.argv[1]);
const cases = [
  {
    name: 'native update detected, app release flag still off',
    native: {state:'on', attributes:{installed_version:'0.1.24',latest_version:'0.1.25'}},
    appFlag: 'off',
    expected: {icon:'mdi:package-up', name:'DH Presence · v0.1.24 → v0.1.25',
               label:'Доступна новая версия', color:'var(--warning-color, orange)'}
  },
  {
    name: 'release checked, supervisor install not offered yet',
    native: {state:'off', attributes:{installed_version:'0.1.24',latest_version:'0.1.24'}},
    appFlag: 'on', appLatest:'0.1.26',
    expected: {icon:'mdi:package-up', name:'DH Presence · v0.1.24 → v0.1.26',
               label:'Доступна новая версия', color:'var(--warning-color, orange)'}
  },
  {
    name: 'supervisor version wins over stale app release version',
    native: {state:'on', attributes:{installed_version:'0.1.24',latest_version:'0.1.25'}},
    appFlag: 'on', appLatest:'0.1.20',
    expected: {name:'DH Presence · v0.1.24 → v0.1.25'}
  },
  {
    name: 'no upgrade means normal presence',
    native: {state:'off', attributes:{installed_version:'0.1.25', latest_version:'0.1.25'}},
    appFlag:'off', installed:'0.1.25',
    expected: {icon:'mdi:home-account', name:'DH Presence · v0.1.25',
               label:'GPS · Есть дома · Дома 2/2', color:'var(--success-color)'}
  },
  {
    name: 'installing using native progress while app is disconnected',
    native:{state:'on', attributes:{in_progress:true,update_percentage:45,installed_version:'0.1.24',latest_version:'0.1.25'}},
    item:{state:'unavailable'}, expected:{icon:'mdi:progress-clock', label:'Установка версии… 45% · 00:00',
                                        color:'var(--info-color, var(--primary-color))'}
  },
  {
    name:'sticky error overrides available update',
    native:{state:'on',attributes:{latest_version:'0.1.25'}},
    item:{state:'error',attributes:{error:'Проверка не выполнена'}},
    expected:{icon:'mdi:alert-circle',label:'Ошибка: Проверка не выполнена',color:'var(--error-color)'}
  },
  {
    name:'running check overrides available update',
    native:{state:'on',attributes:{}},
    item:{state:'running',attributes:{operation:'check',started_at:'2026-10-18T00:00:00+00:00'}},
    expected:{icon:'mdi:progress-clock',label:'Проверка версии… 00:00',
              color:'var(--info-color, var(--primary-color))'}
  },
  {
    name:'completed version check notices new update',
    native:{state:'on',attributes:{}},
    item:{state:'success',attributes:{operation:'check',duration_seconds:1.25}},
    expected:{label:'Доступна новая версия · 1,3 сек',icon:'mdi:check-circle'}
  },
  {
    name:'completed version check with no update',
    native:{state:'off',attributes:{}},
    item:{state:'success',attributes:{operation:'check',duration_seconds:1.25}},
    expected:{label:'Версия актуальна · 1,3 сек'}
  },
  {
    name:'Supervisor update can exist even if app is unavailable',
    native:{state:'on',attributes:{installed_version:'0.1.24',latest_version:'0.1.25'}},
    item:{state:'unavailable'},
    expected:{icon:'mdi:package-up',label:'Нет связи с приложением'}
  },
  {
    name:'invalid native version does not create bogus arrow',
    native:{state:'on',attributes:{latest_version:'unknown'}},
    appFlag:'off',appLatest:'unknown',
    expected:{name:'DH Presence · v0.1.24',label:'Доступна новая версия'}
  }
];
const failures=[];
for(const c of cases){
  const states = {
    'sensor.dh_presence_app_card': c.item || {state:'idle',attributes:{}},
    'sensor.dh_presence_app_version': {state:c.installed||'0.1.24'},
    'sensor.dh_presence_app_latest_version': {state:c.appLatest||'unknown'},
    'binary_sensor.dh_presence_app_update_available': {state:c.appFlag||'off'},
    'binary_sensor.dh_presence_app_residents_home': {state:'on',attributes:{
      residents_home:2,residents_total:2,residents:{},gps_freshness_seconds:300}},
    'select.dh_presence_app_mode': {state:'gps'},
    'update.digitalhouses_presence_app_update': c.native||{state:'off',attributes:{}}
  };
  const actual={};
  for(const key of Object.keys(src)){
    try {
      actual[key]=new Function('states','performance',src[key])
        .call({},states,{now:()=>5000});
    } catch(e) {
      failures.push(c.name+' '+key+': '+e.stack);
    }
  }
  for(const [key,expected] of Object.entries(c.expected)){
    if(actual[key]!==expected) failures.push(
      c.name+' '+key+' expected '+JSON.stringify(expected)+' got '+JSON.stringify(actual[key]));
  }
}
if(failures.length){console.error(failures.join('\\n'));process.exit(1);}
console.log('PASSED '+cases.length+' status scenarios');
"""
        result = subprocess.run(
            ["node", "-e", script, json.dumps(fragments, ensure_ascii=False)],
            capture_output=True, text=True, check=False, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_presence_entities_and_dynamic_resident_roster(self):
        code = CARD.read_text(encoding="utf-8")
        for expected in (
            "binary_sensor.dh_presence_app_residents_home",
            "select.dh_presence_app_mode",
            "sensor.dh_presence_app_version",
            "sensor.dh_presence_app_card",
            "event.dh_presence_app_event",
            "sensor.dh_presence_app_started_at",
            "sensor.dh_presence_app_",
            "attributes?.residents",
            "custom:mushroom-template-card",
            "entity: this.entity_id",
            "binary_sensor.dh_presence_app_*_wifi_home",
            "r.get('user_name')",
            "r.get('status_changed_at')",
            "r.get('gps_changed_at')",
            "r.get('wifi_changed_at')",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, code)

    def test_notification_switches_visible_in_both_cards(self):
        for path in (CARD, DASHBOARD):
            s = path.read_text(encoding="utf-8")
            for key in ("presence", "gps", "wifi"):
                self.assertIn("switch.dh_presence_app_notify_" + key, s)

    def test_router_tracker_replaces_legacy_detection_switches(self):
        for path in (CARD, DASHBOARD):
            s = path.read_text(encoding="utf-8")
            self.assertNotIn("switch.dh_presence_app_ping", s)
            self.assertNotIn("switch.dh_presence_app_arp", s)
            self.assertIn("трекер роутера", s)

    def test_real_operations_and_native_supervisor_boundaries(self):
        code = CARD.read_text(encoding="utf-8")
        runtime = (ROOT / "rootfs/app/app.py").read_text(encoding="utf-8")
        for expected in (
            "button.dh_presence_app_refresh",
            "button.dh_presence_app_check_updates",
            "sensor.dh_presence_app_latest_version",
            "update.digitalhouses_presence_app_update",
            "hassio.app_restart",
            "8133339d_digitalhouses_presence_app",
            "update.install",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, code)
        self.assertIn('topic("command")', runtime)
        self.assertIn("fetch_latest_release()", runtime)
        self.assertIn("publish_controls", runtime)
        self.assertIn("action: none", code)
        self.assertIn("type: select-options", code)
        self.assertIn("Последнее подтверждение:", code)
        self.assertIn("По последним GPS-данным:", code)
        self.assertIn("r.get('gps_changed_at')", code)
        self.assertIn("Последние данные проверены", code)

    def test_universal_registry_and_controls_are_visible_without_resident_ids(self):
        code = CARD.read_text(encoding="utf-8")
        for item in (
            "custom:auto-entities",
            'entity_id: "*dh_presence_app_*"',
            "entity_id: update.digitalhouses_presence_app_update",
            "method: entity_id",
            "button.dh_presence_app_refresh",
            "button.dh_presence_app_check_updates",
            "select.dh_presence_app_mode",
            "sensor.dh_presence_app_last_refresh",
            "Refresh не выполнялся",
        ):
            with self.subTest(item=item):
                self.assertIn(item, code)
        # The dynamically discovered resident ID is not a hardcoded key.
        self.assertNotIn("39fb60fca44a2aa6", code)
        self.assertEqual(code.count("custom:auto-entities"), 2)

    def test_dynamic_mushroom_roster_has_names_states_and_transition_times(self):
        card = CARD.read_text(encoding="utf-8")
        self.assertIn('entity_id: "binary_sensor.dh_presence_app_*_wifi_home"', card)
        self.assertIn("entity: this.entity_id", card)
        self.assertIn("custom:mushroom-template-card", card)
        self.assertIn("multiline_secondary: true", card)
        self.assertIn("r.get('user_name')", card)
        self.assertIn("r.get('name')", card)
        self.assertIn("Имя не задано", card)
        for attr in ("status_changed_at", "gps_changed_at", "wifi_changed_at"):
            self.assertIn(attr, card)
        self.assertIn("Не подключён (роутер)", card)
        self.assertIn("Hybrid · GPS + трекер роутера", card)
        self.assertNotIn("Hybrid: пока только GPS", card)
        self.assertNotIn("39fb60fca44a2aa6", card)
        self.assertNotIn("roster | dictsort", card)

    def test_single_install_ingress_without_custom_registration_resources(self):
        card = CARD.read_text(encoding="utf-8")
        config = (ROOT / "config.yaml").read_text(encoding="utf-8")
        ui = (ROOT / "rootfs/app/dh_presence/ui.py").read_text(encoding="utf-8")
        self.assertNotIn("custom:dh-presence-register-card", card)
        self.assertIn("ingress: true", config)
        self.assertIn("ingress_port: 8099", config)
        self.assertIn("X-Remote-User-Id", ui)
        self.assertIn("X-Remote-User-Display-Name", ui)
        self.assertIn("api/register", ui)
        self.assertIn("start_ingress_ui", ui)
        self.assertFalse((ROOT / "registration_bridge").exists())

    def test_phone_registration_launcher_is_safe_and_single_install(self):
        card = CARD.read_text(encoding="utf-8")
        launcher = (ROOT / "examples/lovelace/presence_registration_card_ru.yaml").read_text(encoding="utf-8")
        config = (ROOT / "config.yaml").read_text(encoding="utf-8")
        self.assertIn("ingress: true", config)
        self.assertIn("registration_ready", launcher)
        self.assertIn("version[2] >= 11", launcher)
        self.assertIn("variables.registration_ready ? 'navigate' : 'none'", launcher)
        self.assertIn("/app/8133339d_digitalhouses_presence_app", launcher)
        self.assertNotIn("/hassio/ingress/", launcher)
        self.assertNotIn("/hassio/ingress/", card)
        self.assertIn("Пока недоступно", launcher)
        self.assertIn("Регистрация телефона", launcher)
        self.assertIn("type: custom:button-card", launcher)
        self.assertNotIn("custom:dh-presence-register-card", card)
        self.assertEqual(card.count("name: Регистрация телефона"), 1)
        # The same launcher is embedded in the maintained card, not duplicated
        # as a separate public system or custom frontend resource.
        noncomment = [line for line in launcher.splitlines()
                      if line.strip() and not line.startswith("#")]
        embedded = "  - " + noncomment[0] + "\n" + "\n".join(
            "    " + line for line in noncomment[1:])
        self.assertIn(embedded, "\n".join(
            line for line in card.splitlines() if line.strip()))

    def test_admin_diagnostics_card_remains_frontend_admin_only(self):
        card = CARD.read_text(encoding="utf-8")
        launch = (ROOT / "examples/lovelace/presence_admin_debug_card_ru.yaml").read_text(encoding="utf-8")
        self.assertIn("hidden:", launch)
        self.assertIn("hass.user?.is_admin !== true", launch)
        self.assertIn("Диагностика регистрации", card)

    def test_auto_entities_uses_native_filter_not_generated_json(self):
        # The CI Presence runner deliberately has no PyYAML dependency; the
        # standalone YAML is checked for structure independently of it.
        standalone = ROOT / "examples/lovelace/presence_residents_auto_entities_ru.yaml"
        source = standalone.read_text(encoding="utf-8")
        self.assertTrue(source.startswith("type: custom:auto-entities\n"))
        for required in (
            "card_param: cards",
            "  include:",
            'entity_id: "binary_sensor.dh_presence_app_*_wifi_home"',
            "type: custom:mushroom-template-card",
            "entity: this.entity_id",
            "multiline_secondary: true",
            "status_changed_at",
            "gps_changed_at",
            "wifi_changed_at",
        ):
            with self.subTest(required=required):
                self.assertIn(required, source)
        self.assertNotIn("  template: |", source)
        self.assertNotIn("roster | dictsort", source)
        for file in (CARD, DASHBOARD):
            content = file.read_text(encoding="utf-8")
            self.assertIn('entity_id: "binary_sensor.dh_presence_app_*_wifi_home"', content)
            self.assertIn("entity: this.entity_id", content)
            self.assertNotIn("roster | dictsort", content)

    def test_dashboard_embeds_same_card_without_drift(self):
        card = CARD.read_text(encoding="utf-8")
        dashboard = DASHBOARD.read_text(encoding="utf-8")
        lines = [line for line in card.splitlines()
                 if line.strip() and not line.startswith("#")]
        expected = "      - " + lines[0] + "\n" + "\n".join("        " + line for line in lines[1:])
        actual = "\n".join(line for line in dashboard.splitlines() if line.strip())
        self.assertIn(expected, actual)


if __name__ == "__main__":
    unittest.main()
