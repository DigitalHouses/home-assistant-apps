# DigitalHouses Speedtest + Internet Monitoring

Home Assistant internet monitoring with Ookla Speedtest, availability statistics and optional automatic ONT/router recovery.

![DigitalHouses Internet dashboard](images/internet-dashboard.png)

The repository example is designed so a new user can install it and reproduce the dashboard above without DigitalHouses-private packages.

## English — Quick start

1. Add `https://github.com/DigitalHouses/home-assistant-apps` to the Home Assistant App store and install **DigitalHouses Speedtest**.
2. Install **Mushroom** and **mini-graph-card** through HACS.
3. Copy both files to your Home Assistant packages directory:

```text
examples/packages/internet_global_package.yaml
examples/packages/internet_settings_passport.yaml
```

4. Open `internet_settings_passport.yaml` and edit only these four values:

```yaml
power_ont_modem_switch_entity_id: ""
pause_ont_s: 10
power_router_switch_entity_id: ""
pause_router_s: 10
```

Example with controllable power relays:

```yaml
power_ont_modem_switch_entity_id: "switch.ont_power"
pause_ont_s: 10
power_router_switch_entity_id: "switch.router_power"
pause_router_s: 10
```

If hardware recovery is not required, leave both switch IDs empty. Speedtest, connectivity, monthly statistics, outage history and the dashboard still work.

5. Restart Home Assistant.
6. Import `examples/lovelace/internet_speedtest_dashboard.yaml` into a new dashboard/view.

The dashboard includes current Internet/DNS state, Download/Upload/Ping/Jitter/Packet Loss, quality thresholds, 24-hour Speedtest graphs, monthly availability, recent results, available Ookla servers and Recovery controls.

### Recommended App configuration

```yaml
periodic_test_enabled: true
periodic_test_interval_minutes: 30
server_ids: []
automatic_server_fallback: true
speedtest_timeout_seconds: 240
connectivity_check:
  interval_seconds: 60
  attempts: 3
  timeout_seconds: 2
expire_after_seconds: 14400
recent_results_limit: 20
log_level: info
```

### Recovery

Recovery is controlled from the dashboard. In Sequential mode the ONT is rebooted each recovery cycle and the router is additionally rebooted every N ONT cycles. In Simultaneous mode all enabled devices are rebooted in the same cycle.

The public package is fail-safe: an empty, malformed, missing or unavailable power switch does not cause a power action.

### Notifications/events

The public package does not require `script.write2log`, Telegram or any DigitalHouses-private boot helper. It fires Home Assistant events of type:

```text
digitalhouses_internet
```

Event data includes an `event`, `title` and `message`. Typical event values are `connection_lost`, `connection_restored`, `performance_download_low`, `performance_upload_low`, `performance_ping_high`, `recovery_ont`, `recovery_router` and `recovery_config_error`.

### Recorder

`sensor.internet_speed_recent_results` is intentionally excluded from Recorder because its large `results` attribute duplicates persistent history already maintained by the App.

---

## Русский — Быстрый старт

1. Добавьте `https://github.com/DigitalHouses/home-assistant-apps` в магазин Apps Home Assistant и установите **DigitalHouses Speedtest**.
2. Через HACS установите **Mushroom** и **mini-graph-card**.
3. Скопируйте два файла:

```text
examples/packages/internet_global_package.yaml
examples/packages/internet_settings_passport.yaml
```

4. В `internet_settings_passport.yaml` измените только четыре значения:

```yaml
power_ont_modem_switch_entity_id: ""
pause_ont_s: 10
power_router_switch_entity_id: ""
pause_router_s: 10
```

Если аппаратная перезагрузка не нужна, оставьте ID реле пустыми. Остальной мониторинг работает без них.

5. Перезапустите Home Assistant.
6. Импортируйте `examples/lovelace/internet_speedtest_dashboard.yaml` в новую панель/представление.

В результате пользователь получает панель как на скриншоте: статус Internet/DNS, Speedtest, пороги качества, графики Download/Upload, месячную доступность, историю сбоев, последние тесты, серверы Ookla и Recovery controls.

### Разделение ответственности

```text
PUBLIC / GitHub
DigitalHouses Speedtest App
  + internet_global_package.yaml
  + internet_settings_passport.yaml
  + internet_speedtest_dashboard.yaml

LOCAL / private
internet_local_extensions_package.yaml   # write2log / local notifications
dh_router_package.yaml                   # router traffic / Router dashboard
```

Телеметрия конкретного роутера и `write2log` больше не являются зависимостями публичного Internet package.
