"""Single-install DH Presence UI via Supervisor Ingress.

Supervisor owns authentication. Only its documented proxy IP is accepted.
Ingress identity headers are authoritative solely on that authenticated hop.
No custom_components, extra frontend resource or separate registration service.
"""
from __future__ import annotations

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import logging
import re
from threading import Lock, Thread
from urllib.request import Request, urlopen

from dh_presence.registration import (
    active_arp_mac, completed_record, load_registry, normalized_mac, put_registration,
    save_registry,
)
from dh_presence.admin import (
    is_authorized_ha_admin, AdministratorVerificationUnavailable,
)
from dh_presence.core import resident_key

LOG = logging.getLogger(__name__)
SUPERVISOR_INGRESS = "172.30.32.2"
CORE_NETWORK = ipaddress.ip_network("172.30.32.0/23")
TRACKER_RE = re.compile(r"^device_tracker\.[a-z0-9_]+$")


def authenticated_ingress_user(peer: str, headers) -> dict:
    """Only the Supervisor proxy can assert these protected HA user headers."""
    if peer != SUPERVISOR_INGRESS:
        raise PermissionError("Only Supervisor Ingress may connect")
    uid = (headers.get("X-Remote-User-Id") or "").strip()
    name = (headers.get("X-Remote-User-Display-Name") or "").strip()
    if not uid or not name or len(uid) > 150 or len(name) > 200:
        raise PermissionError("Ingress user identity missing")
    return {"user_id": uid, "user_name": name}


def ingress_context(peer: str, headers) -> dict:
    """Registration additionally requires a verified direct LAN origin.

    Core and Supervisor each append a connected peer to X-Forwarded-For;
    the second-to-last entry is the IP directly connected to HA Core.
    A Cloudflare connector with an apparent LAN IP is still refused when
    the original HA URL was not an IP/.local host.
    """
    user = authenticated_ingress_user(peer, headers)
    forward = [x.strip() for x in (headers.get("X-Forwarded-For") or "").split(",")]
    # Direct LAN Core requests have exactly two appended hops: browser Core
    # peer and Core-to-Supervisor. Any earlier XFF hop implies a proxy/tunnel,
    # and must not be used to enroll a phone even if the last peer is LAN.
    if len(forward) != 2:
        raise PermissionError("Registration requires a direct HA Core connection")
    try:
        core_peer = ipaddress.ip_address(forward[-1])
        actual_client = ipaddress.ip_address(forward[-2])
    except ValueError as exc:
        raise PermissionError("Invalid ingress address chain") from exc
    if core_peer not in CORE_NETWORK:
        raise PermissionError("Unexpected HA Core proxy hop")
    hostname = (headers.get("X-Forwarded-Host") or "").strip().lower()
    hostname = hostname.split(":")[0]
    if not hostname or len(hostname) > 253:
        raise PermissionError("Missing direct local HA host")
    try:
        ha_host = ipaddress.ip_address(hostname)
    except ValueError:
        local_hostname = (hostname.endswith(".local") and "/" not in hostname
                          and "." in hostname)
    else:
        local_hostname = ha_host.is_private and not ha_host.is_loopback
    if not local_hostname:
        raise PermissionError("Use Home Assistant local URL to register this phone")
    if (not isinstance(actual_client, ipaddress.IPv4Address)
            or not actual_client.is_private or actual_client.is_link_local
            or actual_client.is_loopback
            or actual_client in ipaddress.ip_network("100.64.0.0/10")):
        raise PermissionError("The phone does not have a direct local HA connection")
    return {**user, "ip": str(actual_client)}


def read_core_states(token: str) -> list[dict]:
    """Fetch the ordinary read-only HA entity state registry."""
    request = Request("http://supervisor/core/api/states",
                      headers={"Authorization": "Bearer " + token,
                               "Accept": "application/json"})
    with urlopen(request, timeout=7) as result:
        states = json.load(result)
    if not isinstance(states, list):
        raise ValueError("Unexpected HA states response")
    return states


def read_core_time_zone(token: str) -> str | None:
    """Use the Home Assistant configured timezone, not the browser's timezone.

    Debugging must remain available when Core configuration is temporarily
    inaccessible. In that case the UI explicitly shows UTC, without calling
    a browser-local time Home Assistant time.
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    req = Request("http://supervisor/core/api/config",
                  headers={"Authorization": "Bearer " + token,
                           "Accept": "application/json"})
    try:
        with urlopen(req, timeout=5) as response:
            data = json.load(response)
        zone = data.get("time_zone") if isinstance(data, dict) else None
        if not isinstance(zone, str) or not zone:
            return None
        ZoneInfo(zone)  # Reject invalid timezone data from Core.
        return zone
    except (OSError, ValueError, TypeError, ZoneInfoNotFoundError):
        LOG.warning("Unable to read HA timezone for Presence debug; displaying UTC")
        return None


def gps_candidates(token: str) -> list[dict]:
    """Read-only HA Core observation; never guess a person from a tracker.

    Source ownership is NOT cryptographically attested here; the user must
    explicitly select the actual phone, and ARP proves only network endpoint.
    """
    states = read_core_states(token)
    candidates = []
    for item in states:
        if not isinstance(item, dict):
            continue
        tracker = item.get("entity_id")
        attrs = item.get("attributes")
        if (not isinstance(tracker, str) or not TRACKER_RE.fullmatch(tracker)
                or not isinstance(attrs, dict) or attrs.get("source_type") != "gps"):
            continue
        name = attrs.get("friendly_name")
        if not isinstance(name, str) or not name.strip():
            name = tracker.split(".", 1)[1].replace("_", " ")
        candidates.append({"tracker": tracker, "device_name": name.strip()[:120]})
    return sorted(candidates, key=lambda r: r["device_name"].casefold())


def find_router_wifi_tracker(states: list[dict], registered_mac: str) -> dict:
    """Match one HA router tracker by verified phone MAC; never use IP/name.

    WLAN metadata may disappear while a router tracker is not_home; only
    explicit LAN records are excluded. Duplicates must not be auto-selected.
    """
    expected = normalized_mac(registered_mac)
    matches = []
    for item in states:
        if not isinstance(item, dict):
            continue
        entity = item.get("entity_id")
        attrs = item.get("attributes")
        if (not isinstance(entity, str) or not TRACKER_RE.fullmatch(entity)
                or not isinstance(attrs, dict)
                or attrs.get("source_type") != "router"
                or attrs.get("network_type") == "LAN"):
            continue
        raw_mac = attrs.get("mac_address") or attrs.get("mac")
        if not isinstance(raw_mac, str):
            continue
        try:
            if normalized_mac(raw_mac) != expected:
                continue
        except ValueError:
            continue
        matches.append({
            "tracker": entity,
            "state": item.get("state") if item.get("state") in ("home", "not_home")
                     else "unavailable",
        })
    if not matches:
        return {"status": "not_found"}
    if len(matches) != 1:
        return {"status": "multiple", "count": len(matches)}
    return {"status": "matched", **matches[0]}


def admin_registration_diagnostics(token: str, registry_path: str) -> list[dict]:
    """All registered phones including private IP/MAC, for verified HA admins only.

    The stored IP/MAC are enrollment snapshots, not evidence of the phone's
    current address or its being online. GPS is read from current HA states.
    """
    registrations = load_registry(registry_path)
    states = {
        item.get("entity_id"): item
        for item in read_core_states(token)
        if isinstance(item, dict) and isinstance(item.get("entity_id"), str)
    }
    aggregate = states.get("binary_sensor.dh_presence_app_residents_home", {})
    attrs = aggregate.get("attributes", {})
    roster = attrs.get("residents", {}) if isinstance(attrs, dict) else {}
    if not isinstance(roster, dict):
        roster = {}
    records = []
    for reg in registrations:
        wifi_data = roster.get(resident_key(reg["tracker"]), {})
        if not isinstance(wifi_data, dict):
            wifi_data = {}
        gps = states.get(reg["tracker"], {})
        raw = gps.get("state")
        source = gps.get("attributes") or {}
        if not isinstance(source, dict):
            source = {}
        records.append({
            "user_name": reg["user_name"], "device_name": reg["device_name"],
            "tracker": reg["tracker"], "ip": reg["ip"], "mac": reg["mac"],
            "gps": raw if raw in ("home", "not_home") else "unavailable",
            "wifi": wifi_data.get("wifi", "unavailable"),
            "wifi_last_verified_at": wifi_data.get("wifi_last_verified_at"),
            "wifi_last_probe_at": wifi_data.get("wifi_last_probe_at"),
            "wifi_probe_result": wifi_data.get("wifi_probe_result", "not_checked"),
            "last_gps_at": gps.get("last_reported") or gps.get("last_updated"),
            "registration_status": "registered",
            "ip_mac_note": "Адреса проверены при регистрации; текущий IP/MAC не подтверждён",
        })
    return sorted(records, key=lambda row: (row["user_name"].casefold(), row["device_name"].casefold()))


def handler_factory(token: str, registry_path: str, excluded_users: set[str]):
    lock = Lock()

    class PresenceHandler(BaseHTTPRequestHandler):
        server_version = "DH-Presence-Ingress"

        def log_message(self, fmt, *args):
            LOG.debug("Presence ingress: %s", fmt % args)

        def reply(self, status: int, payload: dict):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def context(self):
            return ingress_context(self.client_address[0], self.headers)

        def authenticated_user(self):
            return authenticated_ingress_user(self.client_address[0], self.headers)

        def do_GET(self):
            try:
                context = self.authenticated_user()
                if self.path.split("?")[0] in ("/", "/index.html"):
                    body = HTML.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Frame-Options", "SAMEORIGIN")
                    self.send_header("Content-Security-Policy",
                                     "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/api/candidates":
                    if context["user_id"] in excluded_users:
                        self.reply(403, {"error": "excluded_ha_user"})
                    else:
                        self.reply(200, {"user_name": context["user_name"],
                                         "candidates": gps_candidates(token)})
                elif self.path == "/api/status":
                    # Regular residents can view only their own names/devices;
                    # IP/MAC and other residents' details belong to admin debug.
                    records = [x for x in load_registry(registry_path)
                               if x["user_id"] == context["user_id"]]
                    self.reply(200, {"residents": [
                        {"user_name": x["user_name"], "device_name": x["device_name"],
                         "tracker": x["tracker"]}
                        for x in records]})
                elif self.path == "/api/admin/debug":
                    if not is_authorized_ha_admin(context["user_id"], token):
                        self.reply(403, {"error": "admin_required"})
                    else:
                        self.reply(200, {
                            "residents": admin_registration_diagnostics(token, registry_path),
                            "time_zone": read_core_time_zone(token),
                        })
                else:
                    self.reply(404, {"error": "not_found"})
            except PermissionError as exc:
                self.reply(403, {"error": str(exc)})
            except AdministratorVerificationUnavailable:
                self.reply(503, {"error": "Не удалось подтвердить права администратора"})
            except (ValueError, OSError, KeyError, TypeError) as exc:
                LOG.warning("Ingress read failed: %s", type(exc).__name__)
                self.reply(503, {"error": "Registration service temporarily unavailable"})

        def do_POST(self):
            try:
                context = self.context()
                if self.path not in ("/api/register", "/api/lookup-wifi"):
                    return self.reply(404, {"error": "not_found"})
                if context["user_id"] in excluded_users:
                    return self.reply(403, {"error": "excluded_ha_user"})
                expected_action = "register" if self.path == "/api/register" else "lookup-wifi"
                if self.headers.get("X-Presence-Request") != expected_action:
                    return self.reply(403, {"error": "missing_request_proof"})
                size = int(self.headers.get("Content-Length", "0"))
                if not 1 <= size <= 1024:
                    return self.reply(400, {"error": "invalid_body"})
                data = json.loads(self.rfile.read(size))
                tracker = data.get("tracker") if isinstance(data, dict) else None
                if not isinstance(tracker, str):
                    return self.reply(400, {"error": "tracker_required"})
                choice = next((x for x in gps_candidates(token)
                               if x["tracker"] == tracker), None)
                if choice is None:
                    return self.reply(400, {"error": "unknown_gps_tracker"})
                # A verified *direct* ARP reply is required; never infer MAC
                # from neighbour cache, Wi-Fi misses or a browser field.
                mac, iface = active_arp_mac(context["ip"])
                if self.path == "/api/lookup-wifi":
                    # Preview only: no identity binding or registry modification.
                    # The MAC belongs to the local browser phone, not by proof
                    # to the GPS tracker selected in the dropdown.
                    return self.reply(200, find_router_wifi_tracker(
                        read_core_states(token), mac))
                record = completed_record({
                    **context,
                    **choice,
                    "device_id": "tracker:" + tracker,
                    "entry_id": "gps:" + tracker,
                }, mac)
                with lock:
                    before = load_registry(registry_path)
                    after = put_registration(before, record)
                    save_registry(registry_path, after)
                LOG.info("Confirmed phone enrollment: tracker=%s iface=%s", tracker, iface)
                self.reply(200, {
                    "registered": True, "user_name": record["user_name"],
                    "device_name": record["device_name"], "tracker": tracker,
                    "ip": record["ip"], "mac": mac,
                })
            except PermissionError as exc:
                self.reply(403, {"error": str(exc)})
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                self.reply(400, {"error": "Invalid registration or no fresh IP/MAC evidence"})
            except (OSError, RuntimeError) as exc:
                LOG.warning("Mobile enrollment unavailable: %s", type(exc).__name__)
                self.reply(503, {"error": "Active LAN verification unavailable"})

    return PresenceHandler


HTML = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DH Presence — регистрация</title>
<style>
:root{color-scheme:light dark;-webkit-text-size-adjust:100%}
body{margin:0;padding:12px;background:var(--primary-background-color,#f5f6f8);color:var(--primary-text-color,#252525);font:14px/1.4 system-ui,-apple-system,sans-serif}
main{max-width:700px;margin:0 auto}
h2{font-size:20px;margin:6px 3px 12px}h3{font-size:17px;line-height:1.25;margin:0 0 10px}
.panel{padding:16px;border-radius:14px;background:var(--card-background-color,#fff);margin:10px 0;box-shadow:0 1px 7px #0000000a}
p{margin:8px 0 12px;line-height:1.45}
.muted{color:var(--secondary-text-color,#777)}[hidden]{display:none!important}
button,select{font:inherit;border-radius:9px;min-height:38px}
button{cursor:pointer;border:none;padding:8px 12px;background:var(--primary-color,#277ca6);color:#fff}
button:focus-visible,select:focus-visible{outline:2px solid var(--primary-color,#277ca6);outline-offset:2px}
select{max-width:100%;width:100%;padding:8px;margin:2px 0 9px;border:1px solid var(--divider-color,#ddd);background:var(--card-background-color,#fff);color:inherit}
.actions{display:flex;flex-wrap:wrap;gap:8px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;margin:8px 0 0}
.device-item{overflow-wrap:anywhere;padding:6px 0;border-top:1px solid var(--divider-color,#ddd)}
.device-item:first-child{border-top:none}
.debug-note{font-size:12px;margin:0 0 10px}
.debug-person{padding:10px 0;border-top:1px solid var(--divider-color,#ddd)}
.debug-person:first-child{border-top:none}
.debug-name{font-weight:650;font-size:15px;overflow-wrap:anywhere;margin:0 0 5px}
.debug-badges{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 6px}
.debug-badge{display:inline-block;font-size:12px;padding:3px 7px;border-radius:12px;background:var(--secondary-background-color,#f1f2f3);color:var(--primary-text-color,#333)}
.debug-badge--home{color:var(--success-color,#15804a)}
.debug-badge--away{color:var(--info-color,#277ca6)}
.debug-row{display:grid;grid-template-columns:minmax(90px,35%) minmax(0,1fr) auto;gap:5px;align-items:center;padding:5px 0;font-size:13px}
.debug-key{color:var(--secondary-text-color,#666)}
.debug-value{min-width:0;overflow-wrap:anywhere;word-break:break-word;font-variant-numeric:tabular-nums}
.copy-btn{min-height:28px;padding:4px 7px;font-size:12px;white-space:nowrap;border:1px solid var(--divider-color,#bbb);background:transparent;color:var(--primary-color,#277ca6)}
@media(max-width:430px){body{padding:8px}.panel{padding:13px;margin:8px 0}.debug-row{grid-template-columns:minmax(75px,34%) minmax(0,1fr) auto;gap:4px}.copy-btn{padding:4px 5px}}
</style></head><body><main>
<h2>DH Presence</h2>
<section class="panel"><h3>Регистрация телефона</h3>
<p class="muted">Откройте Home Assistant с регистрируемого телефона через домашний Wi-Fi и локальный адрес. Через Cloudflare/VPN доступны только уже зарегистрированные устройства.</p>
<div id="who" class="muted">Загрузка...</div>
<select id="tracker" aria-label="Выбрать телефон"></select>
<p id="wifiLookup" class="muted" role="status">Выберите устройство для поиска Wi-Fi-трекера по MAC текущего телефона.</p>
<div class="actions"><button id="register">Зарегистрировать</button><button id="reload">Обновить</button></div>
<pre id="result" role="status"></pre></section>
<section class="panel"><h3>Мои устройства</h3><div id="residents" class="muted">...</div></section>
<section class="panel" id="adminDebug" hidden>
<h3>Диагностика · администратор</h3>
<p class="muted debug-note">IP и MAC сохранены при регистрации. Это не проверка текущего адреса или подключения к Wi-Fi.</p>
<button id="reloadDebug">Обновить диагностику</button>
<div id="debugList" role="status"></div>
</section>
</main><script>
const q=id=>document.getElementById(id);
const APP_ROOT=(()=>{
 let path=window.location.pathname;
 if(path.endsWith('/index.html'))path=path.slice(0,-'index.html'.length);
 if(!path.endsWith('/'))path+='/';
 return path;
})();
async function api(url,options={}){
 const res=await fetch(APP_ROOT+url,{cache:'no-store',...options});
 const data=await res.json();
 if(!res.ok)throw Error(data.error||'HTTP '+res.status);
 return data;
}
async function load(){
 try{
  const [c,s]=await Promise.all([api('api/candidates'),api('api/status')]);
  q('who').textContent='Пользователь: '+c.user_name;
  q('tracker').replaceChildren();
  const placeholder=document.createElement('option');
  placeholder.value='';placeholder.textContent='Выберите устройство...';
  q('tracker').append(placeholder);
  q('wifiLookup').textContent='Выберите устройство для поиска Wi-Fi-трекера.';
  for(const x of c.candidates){
   const o=document.createElement('option');o.value=x.tracker;
   o.textContent=x.device_name+' ('+x.tracker+')';q('tracker').append(o);
  }
  q('residents').textContent=s.residents.length?s.residents.map(x=>
   x.user_name+' ('+x.device_name+')').join('\\n')
   :'Пока нет зарегистрированных устройств';
 }catch(e){q('result').textContent=e.message}
}
function gpsLabel(status){
 return status==='home'?'Дома':status==='not_home'?'Вне дома':'Недоступен';
}
function wifiLabel(status){
 return status==='home'?'Дома':status==='not_home'?'Вне дома':'Недоступен';
}
function registrationLabel(status){
 return status==='registered'?'Зарегистрирован':'Не подтверждена';
}
function wifiProbeLabel(status){
 const labels={
  mac_verified:'MAC совпадает',no_reply:'ARP: устройство не отвечает',
  probe_error:'Проверка сети не выполнена',
  mac_mismatch:'IP принадлежит другому MAC',not_registered:'Нет привязки',
  not_checked:'Проверка не выполнялась'
 };
 return labels[status]||'Нет данных';
}
function formattedGpsTime(value,timeZone){
 if(!value)return '—';
 const date=new Date(value);
 if(Number.isNaN(date.getTime()))return '—';
 const zone=timeZone||'UTC';
 try{
  return new Intl.DateTimeFormat('ru-RU',{
   timeZone:zone,day:'2-digit',month:'2-digit',year:'numeric',
   hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false
  }).format(date)+' ('+zone+')';
 }catch(error){
  return date.toISOString().replace('T',' ').slice(0,19)+' (UTC)';
 }
}
function debugRow(label,value,copy=false){
 const row=document.createElement('div');
 row.className='debug-row';
 const key=document.createElement('span');
 key.className='debug-key';key.textContent=label;
 const val=document.createElement('span');
 val.className='debug-value';val.textContent=String(value??'—');
 row.append(key,val);
 if(copy && value){
  const btn=document.createElement('button');
  btn.className='copy-btn';btn.textContent='Копировать';
  btn.setAttribute('aria-label','Копировать '+label);
  btn.addEventListener('click',()=>copyValue(String(value),btn));
  row.append(btn);
 }
 return row;
}
async function copyValue(value,button){
 try{
  if(navigator.clipboard && window.isSecureContext){
   await navigator.clipboard.writeText(value);
  }else{
   const input=document.createElement('textarea');
   input.value=value;input.setAttribute('readonly','');
   input.style.cssText='position:fixed;left:-9999px;top:0';
   document.body.append(input);input.select();
   try{
    if(!document.execCommand('copy'))throw Error('copy unavailable');
   }finally{input.remove();}
  }
  button.textContent='Скопировано';
  setTimeout(()=>{button.textContent='Копировать';},1600);
 }catch(error){
  button.textContent='Не удалось';
  setTimeout(()=>{button.textContent='Копировать';},1600);
 }
}
async function loadAdminDebug(){
 try{
  const data=await api('api/admin/debug');
  q('adminDebug').hidden=false;
  const destination=q('debugList');
  destination.replaceChildren();
  if(!data.residents.length){
   destination.textContent='Зарегистрированных устройств пока нет';return;
  }
  for(const device of data.residents){
   const article=document.createElement('div');
   article.className='debug-person';
   const heading=document.createElement('div');
   heading.className='debug-name';
   heading.textContent=device.user_name+' ('+device.device_name+')';
   article.append(heading);
   const badges=document.createElement('div');
   badges.className='debug-badges';
   const status=[
    ['GPS: '+gpsLabel(device.gps),device.gps==='home'?'debug-badge--home':device.gps==='not_home'?'debug-badge--away':''],
    ['Wi-Fi: '+wifiLabel(device.wifi),''],
    [registrationLabel(device.registration_status),'']
   ];
   for(const [label,mod] of status){
    const chip=document.createElement('span');
    chip.className='debug-badge'+(mod?' '+mod:'');
    chip.textContent=label;badges.append(chip);
   }
   article.append(badges);
   article.append(
    debugRow('GPS tracker',device.tracker),
    debugRow('IP при регистрации',device.ip,true),
    debugRow('MAC при регистрации',device.mac,true),
    debugRow('Последний GPS',formattedGpsTime(device.last_gps_at,data.time_zone)),
    debugRow('Wi-Fi: подтверждён',formattedGpsTime(device.wifi_last_verified_at,data.time_zone)),
    debugRow('Проверка Wi-Fi',wifiProbeLabel(device.wifi_probe_result))
   );
   destination.append(article);
  }
 }catch(error){
  // No access or unavailable HA admin verification: fail closed visually
  // and through the independently gated private backend.
  q('adminDebug').hidden=true;
  q('debugList').replaceChildren();
 }
}
let lookupRequest=0;
async function lookupWifiTracker(){
 const selected=q('tracker').value;
 const current=++lookupRequest;
 if(!selected){
  q('wifiLookup').textContent='Выберите устройство для поиска Wi-Fi-трекера.';
  return;
 }
 q('wifiLookup').textContent='Поиск Wi-Fi-трекера по MAC текущего телефона...';
 try{
  const result=await api('api/lookup-wifi',{
   method:'POST',
   headers:{'Content-Type':'application/json','X-Presence-Request':'lookup-wifi'},
   body:JSON.stringify({tracker:selected})
  });
  if(current!==lookupRequest||q('tracker').value!==selected)return;
  if(result.status==='matched'){
   q('wifiLookup').textContent='Wi-Fi-трекер найден: '+result.tracker+' · '+result.state+
    ' (MAC телефона, открывшего эту страницу)';
  }else if(result.status==='multiple'){
   q('wifiLookup').textContent='Найдено '+result.count+
    ' трекеров с одним MAC. Автоматический выбор запрещён.';
  }else{
   q('wifiLookup').textContent='Wi-Fi-трекер с MAC текущего телефона не найден.';
  }
 }catch(e){
  if(current!==lookupRequest||q('tracker').value!==selected)return;
  q('wifiLookup').textContent='Wi-Fi-поиск недоступен: '+e.message+
   '. Регистрацию можно выполнить отдельно.';
 }
}
q('tracker').addEventListener('change',lookupWifiTracker);
q('reload').onclick=()=>{++lookupRequest;load()};
q('reloadDebug').onclick=loadAdminDebug;
loadAdminDebug();
q('register').onclick=async()=>{
 const selected=q('tracker').value;
 if(!selected)return;
 if(!confirm('Подтверждаете, что открыли HA на телефоне '+selected+' по домашнему Wi-Fi?'))return;
 q('result').textContent='Проверка локального соединения и MAC...';
 try{
  const out=await api('api/register',{
   method:'POST',headers:{'Content-Type':'application/json','X-Presence-Request':'register'},
   body:JSON.stringify({tracker:selected})
  });
  q('result').textContent='Зарегистрирован: '+out.user_name+' ('+out.device_name+')';
  await load();
 }catch(e){q('result').textContent='Регистрация не завершена: '+e.message}
};
load();
</script></body></html>"""


def start_ingress_ui(token: str, registry_path: str, excluded_users: list[str]):
    # With host_network the Supervisor reaches its host via the hassio
    # bridge gateway. Never expose the registration server on a LAN socket.
    server = ThreadingHTTPServer(("172.30.32.1", 8099),
                                 handler_factory(token, registry_path, set(excluded_users)))
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, name="PresenceIngress", daemon=True)
    thread.start()
    LOG.info("DH Presence native Supervisor Ingress started on port 8099")
    return server
