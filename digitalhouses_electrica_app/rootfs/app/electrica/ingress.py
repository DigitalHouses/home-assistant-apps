"""Single-process HAOS Ingress for editing persistent Aqara bindings."""
from copy import deepcopy
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from .catalog import CatalogError
from . import climate_rules, media_rules, profiles, sensor_rules
from .binding_store import binding_document, validate_document, decode_json
from .entity_options import parse_rows, render_rows, project
from .ingress_catalog import normalize, supported_actions, required_keep
from .light_rules import parse_rule
from .mode_keeper import action_channels, validate_keep_mode, PHYSICAL

WEB = Path(__file__).with_name("web")

def revision(rows):
    return sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def snapshot(app):
    with app._mutex:
        config = deepcopy(app.config)
        targets = deepcopy(app.target_catalog)
        for eid,state in (app._last_details_payload or {}).get("target_states",{}).items():
            if eid in targets:
                targets[eid]["state"] = state
        details = deepcopy(app.device_details)
        scan = dict(app._scan)
        report = deepcopy(app._previous)
        maintenance = getattr(app,"globals",{}).get("maintenance_mode",False)
        sensor_catalog=deepcopy(getattr(app,"sensor_catalog",{}))
        engine=getattr(app,"sensor_engine",None)
        sensor_runtime_ready=bool(engine and engine.ready)
        sensor_deadlines={eid:r["deadline"] for eid,r in (engine.owners.items() if engine else [])
                          if r.get("deadline") is not None}
        global_mode = getattr(app,"_home_profile",None)
        auto_day_night = getattr(app,"globals",{}).get("auto_day_night",False)
    rows = parse_rows(app.options.read())
    indexed = {r["entity_id"]:r for r in rows if not sensor_rules.is_source(r["entity_id"])}
    sensor_rows={r["entity_id"]:r for r in rows if sensor_rules.is_source(r["entity_id"])}
    sensors=[]
    for eid in sorted(set(sensor_catalog)|set(sensor_rows)):
        entry=sensor_catalog.get(eid,{"entity_id":eid,"name":eid,"state":"unavailable","area":"—","lux_sources":[],"missing":True})
        sensors.append({**entry,"config":sensor_rows.get(eid,{"entity_id":eid,"enabled":False,"assignments":[]})})
    devices = []
    for room in details or config["rooms"]:
        for sw in room["switches"]:
            key = sw["entity_id"]
            row = indexed.pop(key, {"entity_id":key,"enabled":False,"actions":{}})
            channels = sw.get("mode_channels", [])
            if not supported_actions(sw) and not row["actions"] and not channels:
                continue
            keep = row.get("keep_mode", {})
            key_actions = {action: list(action_channels(action, channels))
                           for action in sw["fingerprint"].get("actions", [])} if channels else {}
            key_modes = {channel: keep.get(channel, "") for channel in channels}

            devices.append({"id":key,"name":sw["logical_name"],"ha_name":sw.get("ha_name"),"model":sw["fingerprint"]["model"],
                            "room":room["name"],"area_id":room.get("area_id"),"network":sw["base_topic"],
                            "status":sw.get("runtime",{}).get("status","unknown"),
                            "reason":sw.get("runtime",{}).get("reason"),
                            "enabled":row["enabled"],"disabled_actions":row.get("disabled_actions",[]),
                            "actions":supported_actions(sw, keep) if channels else supported_actions(sw),
                            "key_modes":key_modes,"key_actions":key_actions,
                            "keep_mode":keep,
                            "power_meter":sw.get("power_meter",False),
                            "power_w":sw.get("power_w"),
                            "bindings":{k:normalize(v) for k,v in row["actions"].items()}})
    for key,row in indexed.items():
        devices.append({"id":key,"name":key,"model":"—","room":"—","network":"—",
                        "status":"missing","reason":"Не найден в каталоге",
                        "enabled":row["enabled"],"disabled_actions":row.get("disabled_actions",[]),"actions":[],
                        "bindings":{k:normalize(v) for k,v in row["actions"].items()}})
    return {"devices":devices,"sensors":sensors,"sensor_runtime_ready":sensor_runtime_ready,"sensor_deadlines":sensor_deadlines,"targets":list(targets.values()),"scan":scan,
            "report":report,"revision":revision(rows),"version":app.version,"maintenance_mode":maintenance,"home_mode":global_mode["mode"] if global_mode else None,"auto_day_night":auto_day_night,"home_profiles_ready":bool(global_mode and "day" in global_mode and "night" in global_mode)}

def validate_assignment(assignment, targets):
    rule = parse_rule({"assignments":[assignment]})
    eid = rule["targets"][0]
    target = targets.get(eid)
    if not target:
        raise CatalogError("Целевая сущность отсутствует: " + eid)
    data = rule["target_data"][eid]
    if "profile" in data:
        if eid.startswith("light.") and not profiles.supported_light(target):
            raise CatalogError("Светильник не поддерживает параметры профиля: "+eid)
        if eid.startswith("media_player.") and "volume" not in target.get("operations",[]):
            raise CatalogError("Громкость не поддерживается: "+eid)
        return
    if eid.startswith("media_player."):
        media_rules.validate_capability(rule["target_operations"][eid],data,target)
        return
    if eid.startswith("climate."):
        climate_rules.validate_capability(rule["target_operations"][eid],data,target)
        return
    if eid.startswith("cover."):
        if rule["target_operations"][eid] not in target.get("operations",[]):
            raise CatalogError("Операция шторы не поддерживается: "+eid)
        for sensor in data.get("window_sensors",[]):
            if targets.get(sensor,{}).get("device_class") not in ("window","door","opening"):
                raise CatalogError("Датчик окна не подтверждён: "+sensor)
        return
    for field, cap in (("brightness_pct","brightness"),("brightness_step_pct","brightness"),
                       ("rgb_color","rgb"),("color_temp_kelvin","cct"),("transition","transition")):
        if field in data and not target[cap]:
            raise CatalogError("Параметр не поддерживается: " + eid + " / " + field)
    if "color_temp_kelvin" in data:
        kelvin = data["color_temp_kelvin"]
        lo,hi = target["min_kelvin"],target["max_kelvin"]
        if type(lo) is not int or type(hi) is not int or not lo <= kelvin <= hi:
            raise CatalogError("Цветовая температура вне диапазона: " + eid)

def save_device(app, payload):
    if not isinstance(payload,dict) or type(payload.get("enabled")) is not bool:
        raise CatalogError("Некорректные настройки устройства")
    if not app._scan_lock.acquire(blocking=False):
        raise CatalogError("Идёт сканирование — повторите сохранение")
    try:
        options = app.options.read()
        rows = parse_rows(options)
        if payload.get("revision") != revision(rows):
            raise CatalogError("Настройки изменились — обновите страницу")
        key = payload.get("id")
        row = next((r for r in rows if r["entity_id"] == key),None)
        if row is None:
            raise CatalogError("Устройство не найдено")
        bindings = payload.get("bindings")
        if not isinstance(bindings,dict):
            raise CatalogError("Некорректные назначения")
        with app._mutex:
            sw = next((s for room in app.config["rooms"] for s in room["switches"]
                       if s["entity_id"] == key),None)
            explicit = "keep_mode" in payload
            keep = dict(row.get("keep_mode",{}))
            if explicit:
                requested = payload["keep_mode"]
                if not isinstance(requested,dict):
                    raise CatalogError("Некорректные режимы клавиш")
                if requested != keep:
                    if not sw:
                        raise CatalogError("Устройство не обнаружено")
                    if set(requested) - set(sw.get("mode_channels",[])):
                        raise CatalogError("Режим клавиши не подтверждён Scan")
                    keep = validate_keep_mode(requested, sw["fingerprint"])
            allowed = set(supported_actions(sw, keep if explicit else None)) if sw else set()
            targets = deepcopy(app.target_catalog)
            current = {k:normalize(v) for k,v in row["actions"].items()}
            updated = {}
            disabled = payload.get("disabled_actions",[])
            if not isinstance(disabled,list) or any(not isinstance(a,str) or a not in bindings for a in disabled):
                raise CatalogError("Некорректный список отключённых нажатий")
            for action, assignments in bindings.items():
                # An explicitly physical key cannot retain an action, even
                # a disabled one. Require the operator to remove it first.
                channels = sw.get("mode_channels",[]) if sw else []
                if any(keep.get(k) == PHYSICAL for k in action_channels(action, channels)):
                    raise CatalogError("Удалите назначения физической клавиши: " + action)
                if explicit and action not in allowed and any(
                        keep.get(k) != row.get("keep_mode",{}).get(k)
                        for k in action_channels(action, channels)):
                    raise CatalogError("Удалите назначения клавиши перед сменой режима: " + action)
                # Preserve existing unavailable/obsolete bindings unchanged.
                if current.get(action) == assignments:
                    updated[action] = row["actions"][action]
                    if not explicit and sw and action in allowed and action not in disabled:
                        keep = required_keep(sw,action,keep)
                    continue
                if action not in allowed:
                    raise CatalogError("Недоступное нажатие: " + action)
                rule = {"assignments":assignments}
                parse_rule(rule)
                for assignment in assignments:
                    if assignment not in current.get(action,[]):
                        validate_assignment(assignment,targets)
                if not explicit and action not in disabled:
                    keep = required_keep(sw,action,keep)
                updated[action] = rule
            row["actions"] = updated
            row["disabled_actions"] = disabled
            if keep or "keep_mode" in row:
                row["keep_mode"] = keep
            row["enabled"] = payload["enabled"]
            options["switches"] = render_rows(rows)
            projected = project(app.config,options)
            app.options.write(options)
            app.config = projected
        app._publish_details()
    finally:
        app._scan_lock.release()

def validate_sensor_assignment(row,sources,targets,previous=None):
    source=sources.get(row["entity_id"])
    if not source:
        if row.get("enabled"):raise CatalogError("Датчик не подтверждён каталогом")
        return
    lux_ids={x["entity_id"] for x in source.get("lux_sources",[])}
    if "lux_entity_id" in row and row["lux_entity_id"] not in lux_ids:
        raise CatalogError("Lux не подтверждён для этого датчика")
    if row["enabled"] and row["assignments"] and lux_ids and "lux_entity_id" not in row:
        raise CatalogError("Задайте порог освещённости для датчика с Lux")
    previous=previous or {}
    for a in row["assignments"]:
        check={k:v for k,v in a.items() if k!="off_delay_seconds"}
        if a not in previous.get("assignments",[]):
            validate_assignment(check,targets)

def save_sensor(app,payload):
    if not isinstance(payload,dict) or set(payload)!={"revision","config"}:
        raise CatalogError("Некорректные настройки датчика")
    row=sensor_rules.validate_row(payload["config"])
    if not app._scan_lock.acquire(blocking=False):
        raise CatalogError("Идёт сканирование — повторите сохранение")
    try:
        options=app.options.read()
        rows=parse_rows(options)
        if payload["revision"]!=revision(rows):
            raise CatalogError("Настройки изменились — обновите страницу")
        old=next((r for r in rows if r["entity_id"]==row["entity_id"]),None)
        with app._mutex:
            validate_sensor_assignment(row,app.sensor_catalog,app.target_catalog,old)
            rows=[r for r in rows if r["entity_id"]!=row["entity_id"]]+[row]
            options["switches"]=render_rows(rows)
            projected=project(app.config,options)
            app.options.write(options)
            app.config=projected
    finally:app._scan_lock.release()

def export_bindings(app):
    rows = parse_rows(app.options.read())
    return binding_document(rows)[0]

def import_bindings(app, payload):
    if not isinstance(payload,dict) or set(payload)!={"revision","document"}:
        raise CatalogError("Некорректный импорт")
    doc=validate_document(payload["document"])
    if not app._scan_lock.acquire(blocking=False):
        raise CatalogError("Идёт сканирование — повторите импорт")
    try:
        options=app.options.read()
        if payload["revision"]!=revision(parse_rows(options)):
            raise CatalogError("Настройки изменились — обновите страницу")
        rows=doc["rows"]
        with app._mutex:
            # Reset omitted adopted devices to disabled; retain orphan imports.
            known={r["entity_id"] for r in rows}
            for room in app.config["rooms"]:
                for sw in room["switches"]:
                    if sw["entity_id"] not in known:
                        rows.append({"entity_id":sw["entity_id"],"enabled":False,"actions":{}})
            options["switches"]=render_rows(rows)
            projected=project(app.config,options)
            # Preserve missing/orphan assignments for recovery, but refuse
            # invalid active policies on currently adopted devices.
            for issue in projected.get("binding_problems",[]):
                if issue.get("category") in ("invalid_binding","invalid_keep_mode"):
                    raise CatalogError(issue["object_name"]+": "+issue["reason"])
            for row in rows:
                if sensor_rules.is_source(row["entity_id"]):
                    # Preserve missing sources/targets on import, but validate
                    # all discovered capabilities; missing never authorizes ON.
                    if row["entity_id"] in getattr(app,"sensor_catalog",{}):
                        for a in row["assignments"]:
                            if a["entity_id"] in app.target_catalog:
                                validate_assignment({k:v for k,v in a.items() if k!="off_delay_seconds"},app.target_catalog)
                        if "lux_entity_id" in row and row["lux_entity_id"] not in {x["entity_id"] for x in app.sensor_catalog[row["entity_id"]]["lux_sources"]}:
                            raise CatalogError("Lux source does not belong to sensor")
                    continue
                for rule in row["actions"].values():
                    for assignment in normalize(rule):
                        if assignment["entity_id"] in app.target_catalog:
                            if assignment["entity_id"].startswith("cover."):
                                # Keep missing window IDs on import; never drop their protection.
                                check=deepcopy(assignment)
                                check["data"]["window_sensors"]=[eid for eid in check["data"].get("window_sensors",[]) if eid in app.target_catalog]
                                validate_assignment(check,app.target_catalog)
                            else:
                                validate_assignment(assignment,app.target_catalog)
            app.options.write(options)
            app.config=projected
        app._publish_details()
    finally:
        app._scan_lock.release()

def live_log(app, cursor, generation):
    # Snapshot observed states only; no MQTT/HA requests per UI poll.
    with app._mutex:
        # Include unassigned lights so engineering tests in the picker receive
        # the same observed feedback as previously configured targets.
        ids = set(app.target_catalog)
        for room in app.config["rooms"]:
            for sw in room["switches"]:
                for rule in sw.get("configured_bindings",sw.get("bindings",{})).values():
                    ids.update(rule.get("targets",[]))
        states = {eid:app.observed_target_state(eid) for eid in ids}
    return {**app.event_log.snapshot(cursor,generation),"states":states}

def browse_media(app,payload):
    if not isinstance(payload,dict) or set(payload) not in ({"entity_id"},{"entity_id","ref"}):
        raise CatalogError("Invalid media browser request")
    eid=payload["entity_id"]
    if not isinstance(eid,str) or not eid.startswith("media_player."):
        raise CatalogError("Expected media player")
    with app._mutex:
        target=app.target_catalog.get(eid,{})
        if "play_media" not in target.get("operations",[]):
            raise CatalogError("Media browsing not supported")
    return app.registry.browse_media(eid,payload.get("ref"))

def start_ingress(app, port=8099):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def reply(self, code, data, mime="application/json; charset=utf-8"):
            if not isinstance(data,bytes):
                data=json.dumps(data,ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type",mime)
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'self'")
            self.send_header("Content-Length",str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def allowed(self):
            if self.client_address[0] != "172.30.32.2":
                self.reply(403,{"error":"Ingress only"})
                return False
            return True
        def do_GET(self):
            if not self.allowed(): return
            path=urlsplit(self.path).path
            files={"/":("index.html","text/html"),"/app.js":("app.js","text/javascript"),
                   "/style.css":("style.css","text/css"),
                   "/entity_picker.js":("entity_picker.js","text/javascript")}
            try:
                if path == "/api/state":
                    self.reply(200,snapshot(app))
                elif path == "/api/bindings":
                    self.reply(200,export_bindings(app))
                elif path == "/api/log":
                    query=parse_qs(urlsplit(self.path).query)
                    cursor=max(0,int(query.get("cursor",["0"])[0]))
                    self.reply(200,live_log(app,cursor,query.get("generation",[None])[0]))
                elif path in files:
                    name,mime=files[path]
                    self.reply(200,(WEB/name).read_bytes(),mime+"; charset=utf-8")
                else:
                    self.reply(404,{"error":"Not found"})
            except Exception:
                self.reply(503,{"error":"Данные приложения недоступны"})
        def do_POST(self):
            if not self.allowed(): return
            try:
                if self.headers.get_content_type() != "application/json":
                    raise CatalogError("Expected JSON")
                size=int(self.headers.get("Content-Length","0"))
                path=urlsplit(self.path).path
                if not 0 < size <= (1_060_000 if path == "/api/import" else 262144):
                    raise CatalogError("Invalid body size")
                payload=decode_json(self.rfile.read(size))
                path=urlsplit(self.path).path
                if path == "/api/scan":
                    if not app.request_scan(foreground=False):
                        raise CatalogError("Сканирование уже выполняется")
                elif path == "/api/test-light":
                    if not isinstance(payload,dict) or set(payload) != {"entity_id"}:
                        raise CatalogError("Тест требует один entity_id")
                    rid = app.request_light_test(payload["entity_id"])
                    self.reply(200,{"ok":True,"id":rid})
                    return
                elif path == "/api/browse-media":
                    self.reply(200,browse_media(app,payload))
                    return
                elif path == "/api/save-sensor":
                    save_sensor(app,payload)
                elif path == "/api/save":
                    save_device(app,payload)
                elif path == "/api/import":
                    import_bindings(app,payload)
                else:
                    self.reply(404,{"error":"Not found"})
                    return
                self.reply(200,{"ok":True})
            except (CatalogError,ValueError,TypeError,KeyError) as exc:
                self.reply(400,{"error":str(exc)})
            except Exception:
                self.reply(503,{"error":"Операция не выполнена"})
    return ThreadingHTTPServer(("0.0.0.0",port),Handler)
