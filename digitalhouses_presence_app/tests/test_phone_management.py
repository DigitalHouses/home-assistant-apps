"""Admin-only deletion removes registration and stops the resident engine safely."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import build_engine, reconcile_registration_roster
from dh_presence.core import Status
from dh_presence.discovery import discovery, with_cleanup
from dh_presence.registration import (
    delete_registration, load_registry, load_registry_state,
    put_registration, save_registry,
)
from dh_presence.ui import HTML, ADMIN_DELETE_HTML, handler_factory

SAMPLE = {
    "user_id": "resident-user-1", "user_name": "Serzhan",
    "device_name": "13ProMAX .SKY", "device_id": "device-a",
    "entry_id": "gps:device_tracker.phone_a",
    "tracker": "device_tracker.phone_a",
    "ip": "192.168.8.54", "mac": "88:b9:45:80:a7:55",
    "wifi_tracker": "device_tracker.wifi_a",
}


def config(**kwargs):
    return {
        "presence_mode": "gps", "wifi_absence_minutes": 15,
        "gps_freshness_seconds": 300, "residents": [],
        "exclude_users": [], "resident_names": [],
        **kwargs,
    }


class PhoneManagementTests(unittest.TestCase):
    def test_unregister_is_durable_even_if_legacy_config_keeps_tracker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "registry.json")
            save_registry(path, [SAMPLE])
            original = build_engine(config(residents=["device_tracker.phone_a"]),
                                    {"schema_version": 2, "residents": []}, load_registry(path))
            self.assertEqual(len(original.residents), 1)
            self.assertTrue(next(iter(original.residents.values())).registered)
            removed = delete_registration(path, "device_tracker.phone_a")
            self.assertEqual(removed["device_name"], "13ProMAX .SKY")
            enrolled, suppressed = load_registry_state(path)
            self.assertEqual(enrolled, [])
            self.assertEqual(suppressed, {"device_tracker.phone_a"})
            self.assertTrue(reconcile_registration_roster(
                original, config(residents=["device_tracker.phone_a"]), enrolled, suppressed))
            self.assertEqual(original.residents, {})
            self.assertEqual(original.overall(), Status.UNAVAILABLE)
            self.assertEqual(original.persistent()["residents"], [])
            # Reboot, with same legacy config, must not resurrect phone.
            restarted = build_engine(config(residents=["device_tracker.phone_a"]),
                                     original.persistent(), enrolled, suppressed)
            self.assertFalse(restarted.residents)
            # A genuine new enrollment explicitly revokes the tombstone.
            enrolled = put_registration(enrolled, SAMPLE)
            save_registry(path, enrolled, disabled_trackers=suppressed - {"device_tracker.phone_a"})
            self.assertEqual(load_registry_state(path)[1], set())
            self.assertTrue(reconcile_registration_roster(
                original, config(residents=["device_tracker.phone_a"]), enrolled, set()))
            phone = original.residents["device_tracker.phone_a"]
            self.assertTrue(phone.registered)
            self.assertEqual(phone.confirmed, Status.UNAVAILABLE)

    def test_old_schema1_migrates_to_schema2_on_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            path.write_text(json.dumps({"schema_version": 1, "residents": [SAMPLE]}))
            self.assertEqual(load_registry_state(str(path))[1], set())
            delete_registration(str(path), "device_tracker.phone_a")
            saved = json.loads(path.read_text())
            self.assertEqual(saved["schema_version"], 2)
            self.assertEqual(saved["disabled_trackers"], ["device_tracker.phone_a"])

    def test_invalid_delete_and_unknown_tracker_never_mutate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            save_registry(str(path), [SAMPLE])
            before = path.read_bytes()
            for name in ("", "device_tracker.other", "sensor.phone", "device_tracker.ADMIN",
                         "device_tracker.phone_a/../../"):
                if name == "device_tracker.other":
                    with self.assertRaises(LookupError):
                        delete_registration(str(path), name)
                else:
                    with self.assertRaises(ValueError):
                        delete_registration(str(path), name)
                self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(ValueError):
                save_registry(str(path), [SAMPLE], disabled_trackers={"device_tracker.phone_a"})
            self.assertEqual(path.read_bytes(), before)

    def test_corrupt_tombstone_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            for blocked in ("unexpected", ["device_tracker.x", "device_tracker.x"],
                            ["device_tracker.Bad"], ["device_tracker.phone_a"]):
                path.write_text(json.dumps({
                    "schema_version": 2, "residents": [SAMPLE], "disabled_trackers": blocked,
                }))
                with self.assertRaises(ValueError):
                    load_registry_state(str(path))

    def test_reconcile_retains_existing_state_on_unrelated_addition(self):
        engine = build_engine(config(), {"schema_version": 2, "residents": []}, [SAMPLE])
        engine.residents["device_tracker.phone_a"].confirmed = Status.HOME
        other = dict(SAMPLE, user_id="user2", user_name="Alina",
                     tracker="device_tracker.phone_b", device_id="device-b",
                     entry_id="gps:device_tracker.phone_b", ip="192.168.8.55",
                     mac="8a:43:3e:74:09:83", wifi_tracker="device_tracker.wifi_b")
        self.assertTrue(reconcile_registration_roster(engine, config(), [SAMPLE, other], set()))
        self.assertEqual(engine.residents["device_tracker.phone_a"].confirmed, Status.HOME)
        self.assertEqual(engine.residents["device_tracker.phone_b"].confirmed, Status.UNAVAILABLE)
        self.assertFalse(reconcile_registration_roster(engine, config(), [SAMPLE, other], set()))

    def test_discovery_cleanup_and_public_roster_after_unregister(self):
        engine = build_engine(config(), {"schema_version": 2, "residents": []}, [SAMPLE])
        old = discovery("0.1.29", list(engine.residents.values()))
        roster = engine.snapshot()["residents"]
        item = next(iter(roster.values()))
        self.assertTrue(item["registered"])
        self.assertEqual(item["registration_label"], "Serzhan (13ProMAX .SKY)")
        self.assertNotIn("192.168.8.", json.dumps(roster))
        self.assertNotIn("88:b9:45", json.dumps(roster))
        reconcile_registration_roster(engine, config(), [], {"device_tracker.phone_a"})
        new = discovery("0.1.29", list(engine.residents.values()))
        gone = with_cleanup(old, new)
        self.assertTrue(any(name.endswith("_gps_home") and comp == {"platform": "binary_sensor"}
                            for name, comp in gone["components"].items()))
        self.assertEqual(engine.snapshot()["residents"], {})

    def request(self, path="/api/admin/delete-registration", tracker="device_tracker.phone_a",
                headers=None, body=None, uid="admin", registry_path="/tmp/phone-registry.json"):
        cls = handler_factory("token", registry_path, set())
        req = object.__new__(cls)
        req.path = path
        payload = json.dumps({"tracker": tracker}).encode("utf-8") if body is None else body
        req.headers = {
            "X-Remote-User-Id": uid,
            "X-Remote-User-Display-Name": "Admin",
            "X-Presence-Request": "delete-registration",
            "Content-Type": "application/json",
            "Content-Length": str(len(payload)),
            **(headers or {}),
        }
        req.client_address = ("172.30.32.2", 12345)
        req.rfile = io.BytesIO(payload)
        answers = []
        req.reply = lambda status, data: answers.append((status, data))
        return req, answers

    def test_admin_delete_works_remotely_without_arp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "registry.json")
            save_registry(path, [SAMPLE])
            req, answers = self.request(registry_path=path)
            # authenticated_ingress_user needs only Supervisor-provided identity,
            # never local-XFF context. Remote CF is valid for admin maintenance.
            with patch("dh_presence.ui.is_authorized_ha_admin", return_value=True):
                with patch("dh_presence.ui.active_arp_mac") as arp:
                    req.do_POST()
                    arp.assert_not_called()
            self.assertEqual(answers, [(200, {"deleted": True,
                                             "tracker": "device_tracker.phone_a"})])
            self.assertFalse(load_registry(path))
            self.assertIn("device_tracker.phone_a", load_registry_state(path)[1])

    def test_non_admin_and_failed_authorization_never_change_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "registry.json")
            save_registry(path, [SAMPLE])
            for authorized in (False,):
                req, answers = self.request(registry_path=path, uid="resident")
                with patch("dh_presence.ui.is_authorized_ha_admin",
                           return_value=authorized):
                    req.do_POST()
                self.assertEqual(answers[0][0], 403)
            self.assertEqual(load_registry(path), [SAMPLE])

    def test_header_and_payload_rejection_no_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "registry.json")
            save_registry(path, [SAMPLE])
            cases = [
                {"headers": {"X-Presence-Request": "register"}},
                {"headers": {"Content-Type": "text/plain"}},
                {"body": json.dumps({"tracker": "device_tracker.phone_a",
                                     "extra": "bad"}).encode()},
                {"body": b"invalid-json"},
                {"tracker": "device_tracker.other"},
            ]
            for options in cases:
                req, answers = self.request(registry_path=path, **options)
                with patch("dh_presence.ui.is_authorized_ha_admin", return_value=True):
                    req.do_POST()
                self.assertIn(answers[0][0], (400, 403, 404))
                self.assertEqual(load_registry(path), [SAMPLE])

    def test_compact_select_page_rejects_non_admin_and_requires_ingress(self):
        def request(peer="172.30.32.2"):
            cls = handler_factory("token", "/tmp/test-presence-phone-registry.json", set())
            req = object.__new__(cls)
            req.path = "/admin/delete-phone"
            req.client_address = (peer, 1000)
            req.headers = {"X-Remote-User-Id": "admin-ha-user",
                           "X-Remote-User-Display-Name": "Admin"}
            req.wfile = io.BytesIO()
            req.responses = []
            req.reply = lambda status, data: req.responses.append((status, data))
            req.send_response = lambda status: req.responses.append(status)
            req.send_header = lambda key, value: req.responses.append((key, value))
            req.end_headers = lambda: None
            return req

        with patch("dh_presence.ui.is_authorized_ha_admin", return_value=False):
            unauthorized = request()
            unauthorized.do_GET()
            self.assertEqual(unauthorized.responses, [(403, {"error": "admin_required"})])
            self.assertEqual(unauthorized.wfile.getvalue(), b"")
        with patch("dh_presence.ui.is_authorized_ha_admin", return_value=True) as check:
            allowed = request()
            allowed.do_GET()
            check.assert_called_once_with("admin-ha-user", "token")
            self.assertIn(200, allowed.responses)
            self.assertIn(("X-Frame-Options", "SAMEORIGIN"), allowed.responses)
            root = request()
            root.path = "/"
            root.do_GET()
            csp_headers = [v for k, v in root.responses if isinstance(k, str)
                           and k == "Content-Security-Policy"]
            self.assertEqual(len(csp_headers), 1)
            self.assertIn("frame-src 'self'", csp_headers[0])
            self.assertIn('src="admin/delete-phone"', HTML)
            self.assertNotIn("frame-src *", HTML)
            self.assertIn(("Cache-Control", "no-store"), allowed.responses)
            self.assertIn(b'id="phone"', allowed.wfile.getvalue())
            self.assertIn(b'id="confirmation"', allowed.wfile.getvalue())
            self.assertIn(b"api/admin/delete-registration", allowed.wfile.getvalue())
        with patch("dh_presence.ui.is_authorized_ha_admin",
                   side_effect=Exception("admin verification failed")):
            # Unexpected verifier errors must not bypass the security gate.
            broken = request()
            with self.assertRaisesRegex(Exception, "verification failed"):
                broken.do_GET()
            self.assertEqual(broken.wfile.getvalue(), b"")
        with patch("dh_presence.ui.is_authorized_ha_admin", return_value=True):
            direct = request(peer="192.168.8.1")
            direct.do_GET()
            self.assertEqual(direct.responses[0][0], 403)
            self.assertEqual(direct.wfile.getvalue(), b"")

    def test_inline_select_requires_confirmation_and_uses_admin_ingress_post(self):
        """Run the actual embedded browser JavaScript with a fake DOM/fetch."""
        import shutil
        import subprocess
        if not shutil.which("node"):
            self.skipTest("Node is not installed")
        javascript = ADMIN_DELETE_HTML.split("<script>", 1)[1].split("</script>", 1)[0]
        check = subprocess.run(["node", "--check"], input=javascript,
                               capture_output=True, text=True, check=False)
        self.assertEqual(check.returncode, 0, check.stderr)
        browser = r"""
const assert=require('node:assert/strict');
const elements=new Map();
function el(id){
 if(!elements.has(id)){
  elements.set(id,{
   id,disabled:false,hidden:false,value:'',textContent:'',children:[],events:{},
   append(child){this.children.push(child)},
   replaceChildren(...children){this.children=children;this.value=''},
   addEventListener(name,listener){this.events[name]=listener},
  });
 }
 return elements.get(id);
}
global.document={
 getElementById:el,
 createElement:tag=>({tag,value:'',textContent:''}),
};
global.window={location:{pathname:'/api/hassio_ingress/abc/admin/delete-phone'}};
const phones=[
 {tracker:'device_tracker.phone_a',user_name:'Serzhan',device_name:'13ProMAX .SKY'},
 {tracker:'device_tracker.phone_b',user_name:'Alina',device_name:'iPhone'},
];
const requests=[];
global.fetch=async (url,options={})=>{
 requests.push({url,options});
 if(url.endsWith('/api/admin/debug'))
  return {ok:true,json:async()=>({residents:phones})};
 if(url.endsWith('/api/admin/delete-registration')){
  const value=JSON.parse(options.body);
  const index=phones.findIndex(p=>p.tracker===value.tracker);
  if(index>=0)phones.splice(index,1);
  return {ok:true,json:async()=>({deleted:true,tracker:value.tracker})};
 }
 throw Error('unexpected request '+url);
};
""" + javascript + r"""
async function settle(){await new Promise(resolve=>setTimeout(resolve,5))}
(async()=>{
 await settle();
 assert.equal(el('phone').children.length,3);
 assert.equal(el('remove').disabled,true);
 el('phone').value='device_tracker.phone_a';
 el('phone').events.change();
 assert.equal(el('remove').disabled,false);
 el('remove').events.click();
 assert.equal(el('confirmation').hidden,false);
 assert.equal(requests.filter(r=>r.options.method==='POST').length,0);
 el('cancel').events.click();
 assert.equal(el('confirmation').hidden,true);
 assert.equal(requests.filter(r=>r.options.method==='POST').length,0);
 el('remove').events.click();
 el('accept').events.click();
 await settle();
 assert.equal(requests.filter(r=>r.options.method==='POST').length,1);
 const post=requests.find(r=>r.options.method==='POST');
 assert.equal(post.url,'/api/hassio_ingress/abc/api/admin/delete-registration');
 assert.equal(post.options.headers['X-Presence-Request'],'delete-registration');
 assert.deepEqual(JSON.parse(post.options.body),{tracker:'device_tracker.phone_a'});
 assert.equal(phones.length,1);
 assert.equal(el('remove').disabled,true);
 assert.equal(el('confirmation').hidden,true);
 assert.equal(el('phone').children.length,2);
 assert.match(el('status').textContent,/Регистрация удалена/);
 console.log('PASS secure select-confirm-post-refresh');
})().catch(error=>{console.error(error.stack);process.exit(1)});
"""
        result = subprocess.run(["node", "-e", browser],
                                capture_output=True, text=True, check=False, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_admin_ingress_javascript_is_valid(self):
        # Ingress JS is embedded in a Python multiline string; escaping errors
        # can pass Python compileall while breaking the entire phone manager.
        import shutil
        import subprocess
        from dh_presence.ui import HTML
        if shutil.which("node") is None:
            self.skipTest("Node is not available")
        javascript = HTML.split("<script>", 1)[1].split("</script>", 1)[0]
        result = subprocess.run(["node", "--check"], input=javascript,
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_admin_phone_tree_displays_private_ip_mac_with_compact_pve_lines(self):
        """Registered IP/MAC must render only inside authorized Ingress."""
        import shutil
        import subprocess
        from dh_presence.ui import HTML
        if shutil.which("node") is None:
            self.skipTest("Node is not available")
        javascript = HTML.split("<script>", 1)[1].split("</script>", 1)[0]
        start = javascript.index("function privatePhoneTree(devices){")
        end = javascript.index("async function loadAdminDebug()", start)
        script = javascript[start:end] + "\n" + (
            "const devices=JSON.parse(process.argv[1]);"
            "process.stdout.write(privatePhoneTree(devices));"
        )
        second = dict(SAMPLE, user_name="Alina", device_name="iPhone", 
                      tracker="device_tracker.iphone_alina",
                      wifi_tracker=None, ip="192.168.8.55",
                      mac="8a:43:3e:74:09:83")
        first = dict(SAMPLE, user_name="<Admin>", device_name="13ProMAX .SKY")
        result = subprocess.run(
            ["node", "-e", script, json.dumps([first, second], ensure_ascii=False)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 11)
        self.assertEqual(lines[0], "Зарегистрированные телефоны")
        self.assertEqual(lines[1], "├─ 📱 <Admin> (13ProMAX .SKY)")
        self.assertEqual(lines[2], "│  ├─ GPS · phone_a")
        self.assertEqual(lines[3], "│  ├─ Wi-Fi · wifi_a")
        self.assertEqual(lines[4], "│  ├─ IP (рег.) · 192.168.8.54")
        self.assertEqual(lines[5], "│  └─ MAC (рег.) · 88:b9:45:80:a7:55")
        self.assertEqual(lines[6], "└─ 📱 Alina (iPhone)")
        self.assertEqual(lines[7], "   ├─ GPS · iphone_alina")
        self.assertEqual(lines[8], "   ├─ Wi-Fi · не привязан")
        self.assertEqual(lines[9], "   ├─ IP (рег.) · 192.168.8.55")
        self.assertEqual(lines[10], "   └─ MAC (рег.) · 8a:43:3e:74:09:83")
        self.assertNotIn("\n\n", result.stdout)

        # Browser textContent, not innerHTML, protects untrusted labels.
        self.assertIn("q('adminPhoneTree').textContent", javascript)
        self.assertIn("q('adminPhoneTree').textContent=''", javascript)
        self.assertNotIn("q('adminPhoneTree').innerHTML", javascript)
        self.assertIn("line-height:1", HTML)
        self.assertIn("white-space:pre", HTML)
        self.assertIn('id="adminDebug" hidden', HTML)

    def test_dashboard_shows_network_tree_from_app_and_admin_interface_remains_secure(self):
        base = Path(__file__).resolve().parents[1]
        card = (base / "examples/lovelace/presence_registered_phones_markdown_ru.yaml").read_text()
        dash = (base / "examples/lovelace/dh_presence_app_dashboard.yaml").read_text()
        self.assertIn("sensor.dh_presence_app_registered_phones", card)
        self.assertIn("sensor.dh_presence_app_registered_phones", dash)
        self.assertIn("tree | e", card)
        self.assertNotIn("phone.", card)
        self.assertNotIn("residents_home", card)
        self.assertNotIn("api/admin/delete-registration", card)
        self.assertIn("line-height:1", card)
        # The old private Ingress workflow stays available and independently
        # verifies admin identity before editing the saved phone registry.
        self.assertIn('is_authorized_ha_admin(context["user_id"], token)',
                      (base / "rootfs/app/dh_presence/ui.py").read_text())
        for marker in (
                "X-Presence-Request", "delete-registration",
                "Удалить регистрацию", "confirm(", "q('adminDebug').hidden=true"):
            self.assertIn(marker, HTML)


if __name__ == "__main__":
    unittest.main()
