# Ruslan: passive one-group observation

This is an experimental **standalone** observer for Studio Code Server terminal,
not an installable Home Assistant App release.

Target:
- base topic: zigbee2mqtt_1
- group: zg_bedroom_tube_lights (id 112)
- two group members: 1f_bedroom_tubelight_L / 1f_bedroom_tubelight_R

The script only subscribes to the selected group and member state topics,
their set/get commands, and bridge/groups inventory. It never publishes
to MQTT, triggers GET, changes device state or reads HA secrets.
JSONL is written under /config/dh_aqara_observer, limited to 20000 records or
18 hours. Disconnect or restart of Studio Code Server can stop the process.

Prerequisite: GET http://supervisor/services/mqtt must be authorized from the
terminal app. Supervisor may deny service access when that app did not declare
the MQTT service. Do not elevate permissions merely for this diagnostic.

Install (copy into VS Code terminal):

    curl -fLsS https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/main/digitalhouses_aqara_switch_app/examples/tests/passive_group_observer.py -o /config/dh_aqara_passive_group_observer.py
    python3 -m py_compile /config/dh_aqara_passive_group_observer.py
    python3 -u /config/dh_aqara_passive_group_observer.py --hours 18

Leave this terminal running; Ctrl+C gracefully stops and retains the log.
All observed states are deliberately called OBSERVED_UNVERIFIED, because Z2M
optimistic state was true for this group and both TS0502B bulbs in the audit.
No observed MQTT packet proves physical light emission.
