# DigitalHouses Speedtest

Home Assistant App for internet availability monitoring and scheduled speed tests using the official Ookla Speedtest CLI.

## English

### Features

- Download and upload speed
- Ping and jitter
- Packet loss when returned by Ookla
- ISP and public IP
- Selected server name and server ID
- Ookla result URL
- Manual speed-test button
- Optional periodic tests every 5 to 720 minutes
- Connectivity checks to `8.8.8.8` and `1.1.1.1`
- Separate connectivity binary sensors
- Speedtest suppression when both connectivity targets are unavailable
- Preferred Ookla server IDs with automatic fallback
- Nearby-server discovery with provider, location and server ID
- Persistent state
- Home Assistant MQTT Discovery
- Automatic MQTT configuration through Home Assistant Supervisor

### Requirements

- Home Assistant OS or a supervised Home Assistant installation with Apps support
- MQTT broker exposed through Home Assistant Supervisor
- `amd64` architecture

### Installation

1. Open **Settings → Apps → App store**.
2. Open the menu in the upper-right corner.
3. Select **Repositories**.
4. Add `https://github.com/DigitalHouses/home-assistant-apps`.
5. Find **DigitalHouses Speedtest** and install it.
6. Review the configuration and start the App.
7. Enable **Start on boot** and **Watchdog** after the first successful run.

### Configuration example

```yaml
periodic_test_enabled: true
periodic_test_interval_minutes: 180
server_ids: []
automatic_server_fallback: true
speedtest_timeout_seconds: 240
connectivity_check:
  interval_seconds: 60
  attempts: 3
  timeout_seconds: 2
expire_after_seconds: 14400
log_level: info
```

### Server selection

Leave `server_ids` empty to use automatic server selection:

```yaml
server_ids: []
```

To use preferred servers, list their IDs in priority order:

```yaml
server_ids:
  - 38516
  - 70668
```

Use **Refresh server list** in the Home Assistant device and inspect the attributes of **Available Speedtest servers** to find nearby IDs, providers and locations.

### What appears in Home Assistant

The App creates one MQTT device named **Internet Speedtest**.

The device page contains:

- **Sensors** — Download, Upload, Ping and Status
- **Controls** — Run speed test and Refresh server list
- **Diagnostics** — connectivity, jitter, packet loss, ISP, external IP, server, server ID, result URL and timestamps

![Internet Speedtest sensors and controls](images/home-assistant-device-overview.png)

![Internet Speedtest diagnostics](images/home-assistant-device-diagnostics.png)

Home Assistant may translate section names and some state values according to the selected interface language.

### Connectivity logic

The App checks `8.8.8.8` and `1.1.1.1`.

A speed test runs when at least one target is reachable. When both targets are unavailable, the test is skipped, the status changes to `No connectivity`, and previous speed results are preserved.

### Recorder package

The repository includes an optional Recorder package:

`examples/packages/internet_speedtest_package.yaml`

Copy it to:

`/config/packages/internet_speedtest_package.yaml`

Ensure `/config/configuration.yaml` contains:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Do not create a second `homeassistant:` section if one already exists.

### Troubleshooting

**The App cannot connect to MQTT**

Confirm that the MQTT broker is installed, running and exposed as a Supervisor MQTT service.

**Both connectivity sensors are off**

Check internet access, routing, firewall rules and ICMP access to both public DNS addresses.

**A configured server fails**

Enable automatic fallback or refresh the nearby-server list and replace the server ID.

**Packet loss is `unknown`**

Some Ookla servers or test sessions do not return packet-loss data. `unknown` means the metric was not provided; it does not mean `0%`.

### License

DigitalHouses source code is licensed under the MIT License.

This App downloads and runs the official proprietary Ookla Speedtest CLI. Users are responsible for reviewing and complying with Ookla's license, terms of use and privacy policy.

---

## Русский

### Возможности

- скорость скачивания и отдачи;
- ping и jitter;
- packet loss, если Ookla возвращает этот показатель;
- провайдер и внешний IP;
- название и ID выбранного сервера;
- URL результата Ookla;
- кнопка ручного запуска;
- периодические тесты с интервалом от 5 до 720 минут;
- проверки доступности `8.8.8.8` и `1.1.1.1`;
- отдельные binary sensor доступности;
- запрет Speedtest, когда недоступны оба контрольных адреса;
- предпочтительные серверы Ookla с автоматическим fallback;
- список ближайших серверов с провайдером, городом и ID;
- постоянное хранение состояния;
- Home Assistant MQTT Discovery;
- автоматическое получение настроек MQTT через Supervisor.

### Требования

- Home Assistant OS либо supervised-установка Home Assistant с поддержкой Apps;
- MQTT broker, предоставленный через Home Assistant Supervisor;
- архитектура `amd64`.

### Установка

1. Откройте **Настройки → Дополнения → Магазин дополнений**.
2. Откройте меню в правом верхнем углу.
3. Выберите **Репозитории**.
4. Добавьте `https://github.com/DigitalHouses/home-assistant-apps`.
5. Найдите **DigitalHouses Speedtest** и установите приложение.
6. Проверьте конфигурацию и запустите приложение.
7. После успешного запуска включите **Запуск при загрузке** и **Watchdog**.

### Пример конфигурации

```yaml
periodic_test_enabled: true
periodic_test_interval_minutes: 180
server_ids: []
automatic_server_fallback: true
speedtest_timeout_seconds: 240
connectivity_check:
  interval_seconds: 60
  attempts: 3
  timeout_seconds: 2
expire_after_seconds: 14400
log_level: info
```

### Выбор сервера

Оставьте `server_ids` пустым для автоматического выбора:

```yaml
server_ids: []
```

Для предпочтительных серверов укажите ID в порядке приоритета:

```yaml
server_ids:
  - 38516
  - 70668
```

Нажмите **Refresh server list** в устройстве Home Assistant и откройте атрибуты **Available Speedtest servers**. Там отображаются ID, провайдеры и расположение ближайших серверов.

### Что появится в Home Assistant

Приложение создаёт одно MQTT-устройство **Internet Speedtest**.

На странице устройства отображаются:

- **Сенсоры** — Download, Upload, Ping и Status
- **Настройки** — Run speed test и Refresh server list
- **Диагностика** — доступность, jitter, packet loss, провайдер, внешний IP, сервер, ID сервера, URL результата и временные метки

![Сенсоры и кнопки Internet Speedtest](images/home-assistant-device-overview.png)

![Диагностика Internet Speedtest](images/home-assistant-device-diagnostics.png)

Home Assistant может переводить названия разделов и некоторые значения состояний в соответствии с языком интерфейса.

### Логика контроля доступности

Приложение проверяет `8.8.8.8` и `1.1.1.1`.

Speedtest запускается, если отвечает хотя бы один адрес. Если недоступны оба, тест пропускается, статус становится `No connectivity`, а предыдущие результаты сохраняются.

### Пакет Recorder

В репозитории находится дополнительный пакет:

`examples/packages/internet_speedtest_package.yaml`

Скопируйте его в:

`/config/packages/internet_speedtest_package.yaml`

Убедитесь, что `/config/configuration.yaml` содержит:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Если раздел `homeassistant:` уже существует, второй создавать нельзя.

### Диагностика

**Приложение не подключается к MQTT**

Убедитесь, что MQTT broker установлен, запущен и предоставлен как MQTT-сервис Supervisor.

**Оба connectivity sensor выключены**

Проверьте интернет, маршрутизацию, firewall и доступность ICMP к обоим публичным DNS-адресам.

**Указанный сервер не работает**

Включите automatic fallback либо обновите список ближайших серверов и замените ID.

**Packet loss показывает `unknown`**

Некоторые серверы Ookla или отдельные тесты не возвращают packet-loss. `unknown` означает отсутствие измерения, а не `0%`.

### Лицензия

Исходный код DigitalHouses распространяется по лицензии MIT.

Приложение загружает и запускает официальный проприетарный Ookla Speedtest CLI. Пользователь самостоятельно отвечает за соблюдение лицензии, условий использования и политики конфиденциальности Ookla.
