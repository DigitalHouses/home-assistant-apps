"""Canonical MQTT entities. All commands are handled by the same domain engine."""
import json
import re
from core import GLOBAL, PRODUCT, PROFILE_FIELDS, Publication, ContractError

ID = "digitalhouses_system_globals_app"
PREFIX = "dh_system_globals_app"
AVAIL = PRODUCT + "/availability"
LEASE = PRODUCT + "/readiness/lease"
PROBE = PRODUCT + "/probe/ha"
LOOP = PRODUCT + "/probe/mqtt"
DISCOVERY = "homeassistant/device/" + PREFIX + "/config"
SYNC = "DigitalHouses/Global/" + ID + "/sync"
HA_STATUS = "homeassistant/status"
GATE_EVENT = "DigitalHouses/Global/system_ready/event"
LIFECYCLE_EVENT = PRODUCT + "/lifecycle/event"
CTRL = PRODUCT + "/control/"
FIELD = PRODUCT + "/entity/"
OPS = ("refresh", "check_updates")
GATES = ("mqtt_ready", "ha_ready", "zigbee_ready", "system_ready")
NUMBERS = {
    "brightness": (0, 100, 1, "%"), "volume": (0, 100, 1, "%"),
    "display_brightness": (0, 100, 1, "%"), "indicator_brightness": (0, 100, 1, "%"),
    "transition_seconds": (0, 300, 0.1, "s"),
}
BOOLEANS = ("voice_notifications_enabled", "noncritical_sound_notifications_enabled")


def state_topic(key):
    return FIELD + key + "/state"


def cmd_topic(key):
    return FIELD + key + "/set"


def discovery(version):
    components = {}
    def add(key, domain, name, **kw):
        item = {"platform": domain, "unique_id": PREFIX + "_" + key,
                "default_entity_id": domain + "." + PREFIX + "_" + key, "name": name}
        item.update(kw)
        components[key] = item

    switch = dict(payload_on="on", payload_off="off", state_on="on", state_off="off", optimistic=False, qos=1, retain=False)
    add("night_mode", "switch", "Ночной режим", state_topic=GLOBAL+"/state", command_topic=GLOBAL+"/set", icon="mdi:weather-night", **switch)
    add("auto_switch", "switch", "Автоматическое переключение", state_topic=state_topic("auto_switch"), command_topic=cmd_topic("auto_switch"), **switch)
    for key, label, pattern in (("night_start","Начало ночи",r"^([01][0-9]|2[0-3]):[0-5][0-9]$"),("night_end","Конец ночи",r"^([01][0-9]|2[0-3]):[0-5][0-9]$")):
        add(key, "text", label, state_topic=state_topic(key), command_topic=cmd_topic(key), pattern=pattern, min=5, max=5, qos=1, retain=False)
    add("timezone", "sensor", "Часовой пояс", state_topic=state_topic("timezone"))
    for mode, name in (("day", "День"), ("night", "Ночь")):
        for field, (lo, hi, step, unit) in NUMBERS.items():
            key = mode + "_" + field
            label = {"brightness":"Яркость", "volume":"Громкость", "display_brightness":"Яркость дисплеев", "indicator_brightness":"Яркость индикаторов", "transition_seconds":"Плавный переход"}[field]
            add(key, "number", name+" · "+label, state_topic=state_topic(key), command_topic=cmd_topic(key), min=lo, max=hi, step=step, unit_of_measurement=unit, mode="box", qos=1, retain=False)
        # Atomic color edit: one field, one command, no persisted inactive value.
        key=mode+"_color"
        add(key,"text",name+" · Цвет (cct:4000 / rgb:#FF5000)",state_topic=state_topic(key),command_topic=cmd_topic(key), min=0,max=12, pattern=r"^(cct:[0-9]{4}|rgb:#[0-9a-fA-F]{6})?$", qos=1,retain=False)
        for field,label in (("voice_notifications_enabled","Голосовые уведомления"),("noncritical_sound_notifications_enabled","Некритические звуки")):
            key=mode+"_"+field
            add(key,"switch",name+" · "+label,state_topic=state_topic(key),command_topic=cmd_topic(key),**switch)
    for key,label in (("brightness","Активная яркость"),("color_temp_kelvin","Активная температура"),("rgb_color","Активный RGB"),("volume","Активная громкость"),("color_mode","Активный цветовой режим")):
        add("active_"+key,"sensor",label,state_topic=state_topic("active_"+key))
    for gate in GATES:
        # Live lease is deliberately not retained. HA never opens a gate from stale retained on.
        add(gate,"binary_sensor",gate.replace("_"," "),state_topic=LEASE,value_template="{{ value_json."+gate+" }}",payload_on="on",payload_off="off",expire_after=20,device_class="connectivity")
    add("ha_probe","sensor","HA MQTT probe",state_topic=PROBE,entity_category="diagnostic",enabled_by_default=True)
    add("version","sensor","Версия",state_topic=state_topic("version"),entity_category="diagnostic")
    add("started_at","sensor","Запуск App",state_topic=state_topic("started_at"),device_class="timestamp",entity_category="diagnostic")
    add("latest_version","sensor","Последняя версия",state_topic=state_topic("latest_version"),entity_category="diagnostic")
    add("update_available","binary_sensor","Доступна новая версия",state_topic=state_topic("update_available"),payload_on="on",payload_off="off",entity_category="diagnostic")
    for key,label in (("card","Состояние приложения"),("refresh_state","Состояние обновления"),("check_state","Проверка версии")):
        add(key,"sensor",label,state_topic=state_topic(key),value_template="{{ value_json.state }}",json_attributes_topic=state_topic(key),entity_category="diagnostic")
    add("last_refresh","sensor","Последнее обновление данных",state_topic=state_topic("last_refresh"),device_class="timestamp",entity_category="diagnostic")
    for op in OPS:
        add(op,"button",{"refresh":"Обновить","check_updates":"Версия"}[op],command_topic=CTRL+op,payload_press="PRESS",qos=1,retain=False,entity_category="diagnostic")
    add("night_mode_event","event","Режим День/Ночь",state_topic=GLOBAL+"/event",event_types=["night_mode_on","night_mode_off"])
    add("gate_event","event","Готовность системы",state_topic=GATE_EVENT,event_types=[k+"_"+v for k in GATES for v in ("on","off")])
    add("ha_lifecycle","event","Жизненный цикл HA",state_topic=LIFECYCLE_EVENT,event_types=["ha_started","ha_stopping","ha_stopped","ha_connection_lost","ha_connection_restored"])
    for key,label in (("ha_core_state","Состояние HA Core"),("ha_started_at","Подтверждённый запуск HA"),("ha_stopped_at","Подтверждённая остановка HA"),("ha_uptime_seconds","Время работы HA, с"),("ha_downtime_seconds","Последний простой HA, с")):
        add(key,"sensor",label,state_topic=state_topic(key),entity_category="diagnostic")
    return {"device":{"identifiers":[ID],"name":"DigitalHouses System Globals","manufacturer":"DigitalHouses","model":"System Globals App","sw_version":version},"origin":{"name":"DigitalHouses","sw_version":version,"support_url":"https://github.com/DigitalHouses/home-assistant-apps"},"availability":[{"topic":AVAIL,"payload_available":"online","payload_not_available":"offline"}],"qos":1,"components":components}


def sync(version):
    return Publication(SYNC, {"schema":1,"product_id":ID,"product_path":ID,"repository":"https://github.com/DigitalHouses/home-assistant-apps","type":"app","version":version})


def scalar(value):
    if value is None:
        return "None"
    if type(value) is bool:
        return "on" if value else "off"
    return value if isinstance(value,str) else json.dumps(value, separators=(",",":"))


def color_text(p):
    if p["color_mode"] == "cct":
        return "cct:" + str(p["color_temp_kelvin"])
    if p["color_mode"] == "rgb":
        return "rgb:#" + "".join(f"{x:02X}" for x in p["rgb_color"])
    return ""


def projections(state):
    out=[]
    def add(key,value):
        out.append(Publication(state_topic(key),scalar(value)))
    for key,value in state["config"].items():
        add(key,value)
    for mode,p in state["profiles"].items():
        for key in tuple(NUMBERS)+BOOLEANS:
            add(mode+"_"+key,p[key])
        add(mode+"_color",color_text(p))
    p=state["profiles"].get({"on":"night","off":"day"}.get(state["night_mode"]),{})
    for key in ("brightness","color_temp_kelvin","rgb_color","volume","color_mode"):
        add("active_"+key,p.get(key))
    return out


def translate(topic, payload):
    if not topic.startswith(FIELD) or not topic.endswith("/set"):
        raise ContractError("Unknown entity command")
    key=topic[len(FIELD):-len("/set")]
    if key in ("night_start","night_end"):
        return PRODUCT+"/config/set",{key:payload}
    if key=="auto_switch":
        if payload not in ("on","off"):
            raise ContractError("Invalid switch value")
        return PRODUCT+"/config/set",{key:payload=="on"}
    mode,sep,field=key.partition("_")
    if not sep or mode not in ("day","night"):
        raise ContractError("Unknown profile entity")
    if field=="color":
        if re.fullmatch(r"cct:[0-9]{4}",payload):
            patch={"color_mode":"cct","color_temp_kelvin":int(payload[4:])}
        elif re.fullmatch(r"rgb:#[0-9a-fA-F]{6}",payload):
            patch={"color_mode":"rgb","rgb_color":[int(payload[i:i+2],16) for i in (5,7,9)]}
        elif payload=="":
            patch={"color_mode":None,"color_temp_kelvin":None,"rgb_color":None}
        else:
            raise ContractError("Invalid color; use cct:4000 or rgb:#FF5000")
    elif field in NUMBERS:
        try:
            value=float(payload)
            if field!="transition_seconds":
                if not value.is_integer():
                    raise ValueError()
                value=int(value)
        except (ValueError,OverflowError):
            raise ContractError("Invalid numeric value")
        patch={field:value}
    elif field in BOOLEANS:
        if payload not in ("on","off"):
            raise ContractError("Invalid switch value")
        patch={field:payload=="on"}
    else:
        raise ContractError("Unknown profile field")
    return PRODUCT+"/profiles/set",{mode:patch}
