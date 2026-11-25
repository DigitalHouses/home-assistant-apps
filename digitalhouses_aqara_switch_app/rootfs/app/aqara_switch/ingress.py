"""Single-process HAOS Ingress for editing persistent Aqara bindings."""
from copy import deepcopy
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from .catalog import CatalogError
from .entity_options import parse_rows, render_rows, project
from .ingress_catalog import normalize, supported_actions, required_keep
from .light_rules import parse_rule

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
    rows = parse_rows(app.options.read())
    indexed = {r["entity_id"]:r for r in rows}
    devices = []
    for room in details or config["rooms"]:
        for sw in room["switches"]:
            key = sw["entity_id"]
            row = indexed.pop(key, {"entity_id":key,"enabled":False,"actions":{}})
            if not supported_actions(sw) and not row["actions"]:
                continue
            devices.append({"id":key,"name":sw["logical_name"],"model":sw["fingerprint"]["model"],
                            "room":room["name"],"network":sw["base_topic"],
                            "status":sw.get("runtime",{}).get("status","unknown"),
                            "reason":sw.get("runtime",{}).get("reason"),
                            "enabled":row["enabled"],"disabled_actions":row.get("disabled_actions",[]),
                            "actions":supported_actions(sw),
                            "bindings":{k:normalize(v) for k,v in row["actions"].items()}})
    for key,row in indexed.items():
        devices.append({"id":key,"name":key,"model":"—","room":"—","network":"—",
                        "status":"missing","reason":"Не найден в каталоге",
                        "enabled":row["enabled"],"disabled_actions":row.get("disabled_actions",[]),"actions":[],
                        "bindings":{k:normalize(v) for k,v in row["actions"].items()}})
    return {"devices":devices,"targets":list(targets.values()),"scan":scan,
            "report":report,"revision":revision(rows),"version":app.version}

def validate_assignment(assignment, targets):
    rule = parse_rule({"assignments":[assignment]})
    eid = rule["targets"][0]
    target = targets.get(eid)
    if not target:
        raise CatalogError("Целевая сущность отсутствует: " + eid)
    data = rule["target_data"][eid]
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
            allowed = set(supported_actions(sw)) if sw else set()
            targets = deepcopy(app.target_catalog)
            current = {k:normalize(v) for k,v in row["actions"].items()}
            updated = {}
            keep = dict(row.get("keep_mode",{}))
            disabled = payload.get("disabled_actions",[])
            if not isinstance(disabled,list) or any(not isinstance(a,str) or a not in bindings for a in disabled):
                raise CatalogError("Некорректный список отключённых нажатий")
            for action, assignments in bindings.items():
                # Preserve existing unavailable/obsolete bindings unchanged.
                if current.get(action) == assignments:
                    updated[action] = row["actions"][action]
                    if sw and action in allowed and action not in disabled:
                        keep = required_keep(sw,action,keep)
                    continue
                if action not in allowed:
                    raise CatalogError("Недоступное нажатие: " + action)
                rule = {"assignments":assignments}
                parse_rule(rule)
                for assignment in assignments:
                    if assignment not in current.get(action,[]):
                        validate_assignment(assignment,targets)
                if action not in disabled:
                    keep = required_keep(sw,action,keep)
                updated[action] = rule
            row["actions"] = updated
            row["disabled_actions"] = disabled
            if keep:
                row["keep_mode"] = keep
            row["enabled"] = payload["enabled"]
            options["switches"] = render_rows(rows)
            projected = project(app.config,options)
            app.options.write(options)
            app.config = projected
        app._publish_details()
    finally:
        app._scan_lock.release()

def export_bindings(app):
    rows = parse_rows(app.options.read())
    return {"schema":1,"rows":rows}

def import_bindings(app, payload):
    if not isinstance(payload,dict) or set(payload)!={"revision","document"}:
        raise CatalogError("Некорректный импорт")
    doc=payload["document"]
    if (not isinstance(doc,dict) or set(doc)!={"schema","rows"}
            or type(doc["schema"]) is not int or doc["schema"]!=1
            or not isinstance(doc["rows"],list)):
        raise CatalogError("Неподдерживаемый формат JSON")
    fields={"entity_id","enabled","actions","maintenance_mode","keep_mode","disabled_actions"}
    for row in doc["rows"]:
        if (not isinstance(row,dict) or not {"entity_id","enabled","actions"}<=set(row)
                or set(row)-fields):
            raise CatalogError("Некорректная строка привязок")
    if not app._scan_lock.acquire(blocking=False):
        raise CatalogError("Идёт сканирование — повторите импорт")
    try:
        options=app.options.read()
        if payload["revision"]!=revision(parse_rows(options)):
            raise CatalogError("Настройки изменились — обновите страницу")
        rows=parse_rows({**options,"switches":render_rows(doc["rows"])})
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
                for rule in row["actions"].values():
                    for assignment in normalize(rule):
                        if assignment["entity_id"] in app.target_catalog:
                            validate_assignment(assignment,app.target_catalog)
            app.options.write(options)
            app.config=projected
        app._publish_details()
    finally:
        app._scan_lock.release()

def live_log(app, cursor, generation):
    # Snapshot observed states only; no MQTT/HA requests per UI poll.
    with app._mutex:
        states={}
        for room in app.config["rooms"]:
            for sw in room["switches"]:
                for rule in sw.get("configured_bindings",sw.get("bindings",{})).values():
                    for eid in rule.get("targets",[]):
                        route=app.config.get("light_routes",{}).get(eid)
                        value=app.target_catalog.get(eid,{}).get("state","unknown")
                        if route:
                            base,name=route["base_topic"],route["friendly_name"]
                            net=app._networks.get(base,{})
                            if net.get("bridge_state")!="online" or app._light_availability.get((base,name))!="online":
                                value="unavailable"
                            elif (base,name,"state") in app._fresh_fields:
                                reported=net.get("states",{}).get(name,{}).get("state")
                                value=reported.lower() if reported in ("ON","OFF") else "unknown"
                            else:
                                value="unknown"
                        states[eid]=value
    return {**app.event_log.snapshot(cursor,generation),"states":states}

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
                   "/style.css":("style.css","text/css")}
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
                payload=json.loads(self.rfile.read(size))
                path=urlsplit(self.path).path
                if path == "/api/scan":
                    if not app.request_scan(foreground=False):
                        raise CatalogError("Сканирование уже выполняется")
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
