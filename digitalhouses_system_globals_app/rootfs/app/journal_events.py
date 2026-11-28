"""System Globals domain event catalog; no secrets or raw requests."""
from dh_journal import Journal

LOCALES = {
    "ru": {
        "mqtt_connected": "MQTT подключён",
        "mqtt_disconnected": "MQTT · соединение потеряно",
        "mqtt_unavailable": "MQTT недоступен",
        "gate_ready": "{gate} → ON",
        "gate_not_ready": "{gate} → OFF · {reason}",
        "bridge_ready": "Zigbee2MQTT · {bridge} → ON",
        "bridge_not_ready": "Zigbee2MQTT · {bridge} → OFF",
        "night_mode_on": "🌙 Ночной режим включён",
        "night_mode_off": "☀️ Дневной режим включён",
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
        "night_mode_on": "🌙 Night mode enabled",
        "night_mode_off": "☀️ Day mode enabled",
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

GATE_NAMES = {"mqtt_ready":"MQTT Ready", "ha_ready":"HA Ready", "zigbee_ready":"Zigbee Ready", "system_ready":"System Ready"}

class GlobalsJournal:
    """Observe meaningful changes to an already computed service snapshot."""
    def __init__(self, journal):
        self.journal = journal
        self.previous = None

    def observe(self, view):
        j = self.journal
        old = self.previous
        self.previous = view
        if old is None or old["mqtt_connected"] != view["mqtt_connected"]:
            if view["mqtt_connected"]:
                j.success("mqtt_connected")
            elif old is not None:
                j.warning("mqtt_disconnected")
        for key, ready in view["gates"].items():
            d = view["diagnostics"].get(key, {})
            if old is None or old["gates"].get(key) != ready or (not ready and (old["diagnostics"].get(key,{}) or {}).get("reason")!=d.get("reason")):
                j.record("success" if ready else "pending" if old is None else "warning",
                         "gate_ready" if ready else "gate_not_ready", gate=GATE_NAMES.get(key,key),
                         reason=d.get("reason","required_components"))
        for base, bridge in view["zigbee_bridges"].items():
            ready=bridge.get("ready",False)
            previous=(old or {}).get("zigbee_bridges",{}).get(base)
            if previous is None or previous.get("ready") != ready:
                j.record("success" if ready else "warning","bridge_ready" if ready else "bridge_not_ready",bridge=base)
        state=view["state"]
        before=(old or {}).get("state",{})
        if old is None or before.get("night_mode") != state["night_mode"]:
            j.info("night_mode_"+(state["night_mode"] or "unset"))
        for key in ("config","profiles"):
            if old is not None and before.get(key)!=state[key]:
                j.info(key+"_changed",previous=before.get(key),current=state[key])
        life=view["lifecycle"].get("ha_core_state")
        if life is not None and life!=(old or {}).get("lifecycle",{}).get("ha_core_state"):
            j.info("ha_core_state",state=life)
        card=view["card"]
        previous=(old or {}).get("card",{})
        if (card.get("state"),card.get("started_at"))!=(previous.get("state"),previous.get("started_at")):
            kind={"running":("pending","operation_started"),"success":("success","operation_success"),"error":("error","operation_failed")}.get(card.get("state"))
            if kind:
                j.record(*kind,operation=card.get("operation"),duration=card.get("duration_seconds"),reason=card.get("error"))
