"""System Globals domain event catalog; no secrets or raw requests."""
import time

LOCALES = {
    "ru": {
        "mqtt_connected": "MQTT подключён",
        "mqtt_disconnected": "MQTT · соединение потеряно",
        "mqtt_unavailable": "MQTT недоступен",
        "gate_ready": "{gate} → ON",
        "gate_not_ready": "{gate} → OFF · {reason}",
        "bridge_ready": "Zigbee2MQTT · {bridge} → ON",
        "bridge_not_ready": "Zigbee2MQTT · {bridge} → OFF",
        "night_mode_on": "Ночной режим включён",
        "night_mode_off": "Дневной режим включён",
        "night_mode_unset": "Режим дома не задан",
        "config_changed": "Расписание / конфигурация изменены",
        "profiles_changed": "Профили освещения и звука изменены",
        "ha_core_state": "HA Core · {state}",
        "ha_connection_lost": "Связь с HA потеряна",
        "ha_connection_restored": "Связь с HA восстановлена",
        "ha_stopping": "HA останавливается",
        "ha_stopped": "Остановка HA подтверждена",
        "ha_started": "Запуск HA подтверждён",
        "operation_started": "Операция начата · {operation}",
        "operation_success": "Операция завершена · {operation}",
        "operation_failed": "Ошибка операции · {operation}",
        "command_rejected": "Некорректная команда отклонена",
        "command_applied": "Изменение применено движком",
    },
    "en": {
        "mqtt_connected": "MQTT connected",
        "mqtt_disconnected": "MQTT connection lost",
        "mqtt_unavailable": "MQTT unavailable",
        "gate_ready": "{gate} → ON",
        "gate_not_ready": "{gate} → OFF · {reason}",
        "bridge_ready": "Zigbee2MQTT · {bridge} → ON",
        "bridge_not_ready": "Zigbee2MQTT · {bridge} → OFF",
        "night_mode_on": "Night mode enabled",
        "night_mode_off": "Day mode enabled",
        "night_mode_unset": "House mode not configured",
        "config_changed": "Schedule / configuration changed",
        "profiles_changed": "Light and sound profiles changed",
        "ha_core_state": "HA Core · {state}",
        "ha_connection_lost": "HA connection lost",
        "ha_connection_restored": "HA connection restored",
        "ha_stopping": "HA stopping",
        "ha_stopped": "HA shutdown confirmed",
        "ha_started": "HA startup confirmed",
        "operation_started": "Operation started · {operation}",
        "operation_success": "Operation completed · {operation}",
        "operation_failed": "Operation failed · {operation}",
        "command_rejected": "Invalid command rejected",
        "command_applied": "Change applied by domain engine",
    },
}

PRODUCT_NAME = "DigitalHouses System Globals"
ICONS = {"night_mode_on":"🌙", "night_mode_off":"☀️"}
VALUE_LOCALES = {
    "ru": {
        "reason": {
            "awaiting_probe":"ожидание проверки",
            "required_components":"ожидание обязательных компонентов",
            "bridge_not_ready":"ожидание готовности Zigbee2MQTT",
            "no_bridges_discovered":"мосты Zigbee2MQTT не обнаружены",
            "ha_probe_not_confirmed":"проверка HA не подтверждена",
            "ha_offline":"HA сообщил об отключении",
            "ha_online":"HA подключён, ожидание проверки",
            "ha_probe_timeout":"истекло время проверки HA",
            "roundtrip_timeout":"истекло время проверки MQTT",
            "probe_expired":"подтверждение готовности устарело",
            "ready":"готов",
        },
        "operation":{"refresh":"обновление состояния","check":"проверка версии"},
        "state":{"RUNNING":"работает","STARTING":"запускается","STOPPING":"останавливается","NOT_RUNNING":"не запущен","STOPPED":"остановлен"},
    },
    "en": {
        "reason": {
            "awaiting_probe":"awaiting probe",
            "required_components":"awaiting required components",
            "bridge_not_ready":"awaiting Zigbee2MQTT readiness",
            "no_bridges_discovered":"no Zigbee2MQTT bridges discovered",
            "ha_probe_not_confirmed":"HA probe not confirmed",
            "ha_offline":"HA reported offline",
            "ha_online":"HA online, awaiting probe",
            "ha_probe_timeout":"HA probe timed out",
            "roundtrip_timeout":"MQTT round-trip timed out",
            "probe_expired":"readiness confirmation expired",
            "ready":"ready",
        },
        "operation":{"refresh":"refresh state","check":"check version"},
        "state":{"RUNNING":"running","STARTING":"starting","STOPPING":"stopping","NOT_RUNNING":"not running","STOPPED":"stopped"},
    },
}
STARTUP_GRACE_SECONDS = 20

GATE_NAMES = {"mqtt_ready":"MQTT Ready", "ha_ready":"HA Ready", "zigbee_ready":"Zigbee Ready", "system_ready":"System Ready"}

class GlobalsJournal:
    """Observe meaningful changes to an already computed service snapshot."""
    def __init__(self, journal, clock=time.monotonic):
        self.journal = journal
        self.previous = None
        self.clock = clock
        self.startup_deadline = clock() + STARTUP_GRACE_SECONDS
        self.ready_seen = set()
        self.gate_levels = {}
        self.bridge_levels = {}

    def observe(self, view):
        j = self.journal
        old = self.previous
        self.previous = view
        if old is None or old["mqtt_connected"] != view["mqtt_connected"]:
            if view["mqtt_connected"]:
                j.success("mqtt_connected",notify=old is not None)
            elif old is not None:
                j.warning("mqtt_disconnected",notify=True)
        initializing = self.clock() < self.startup_deadline
        for key, ready in view["gates"].items():
            d = view["diagnostics"].get(key, {})
            level = "success" if ready else "pending" if initializing and key not in self.ready_seen else "warning"
            if ready:
                self.ready_seen.add(key)
            if old is None or self.gate_levels.get(key) != level or old["gates"].get(key) != ready or (not ready and (old["diagnostics"].get(key,{}) or {}).get("reason")!=d.get("reason")):
                j.record(level,
                         "gate_ready" if ready else "gate_not_ready", gate=GATE_NAMES.get(key,key),
                         reason=d.get("reason","required_components"),notify=level!="pending" and old is not None)
            self.gate_levels[key] = level
        for base, bridge in view["zigbee_bridges"].items():
            ready=bridge.get("ready",False)
            previous=(old or {}).get("zigbee_bridges",{}).get(base)
            key = ("bridge", base)
            level = "success" if ready else "pending" if initializing and key not in self.ready_seen else "warning"
            if ready:
                self.ready_seen.add(key)
            if previous is None or previous.get("ready") != ready or self.bridge_levels.get(base) != level:
                j.record(level,"bridge_ready" if ready else "bridge_not_ready",bridge=base,notify=level!="pending" and old is not None)
            self.bridge_levels[base] = level
        state=view["state"]
        before=(old or {}).get("state",{})
        if old is None or before.get("night_mode") != state["night_mode"]:
            j.info("night_mode_"+(state["night_mode"] or "unset"),notify=old is not None)
        for key in ("config","profiles"):
            if old is not None and before.get(key)!=state[key]:
                j.info(key+"_changed",previous=before.get(key),current=state[key],notify=True)
        life=view["lifecycle"].get("ha_core_state")
        if life is not None and life!=(old or {}).get("lifecycle",{}).get("ha_core_state"):
            j.info("ha_core_state",state=life,notify=old is not None)
        card=view["card"]
        previous=(old or {}).get("card",{})
        if (card.get("state"),card.get("started_at"))!=(previous.get("state"),previous.get("started_at")):
            kind={"running":("pending","operation_started"),"success":("success","operation_success"),"error":("error","operation_failed")}.get(card.get("state"))
            if kind:
                j.record(*kind,operation=card.get("operation"),duration=card.get("duration_seconds"),reason=card.get("error"),notify=True)
