# DigitalHouses Speedtest documentation

## English

### Installation from the DigitalHouses repository

1. Confirm that an MQTT broker App is installed and running.
2. Open **Settings → Apps → App store**.
3. Open the upper-right menu and select **Repositories**.
4. Add:

   ```text
   https://github.com/DigitalHouses/home-assistant-apps
   ```

5. Install **DigitalHouses Speedtest**.
6. Review and save the configuration.
7. Start the App.
8. Open the App log and confirm the MQTT connection and connectivity checks.

For migration from the LXC prototype, stop the LXC services before starting
this App because both implementations use the same MQTT contract.

### Configuration

#### `periodic_test_enabled`

Enables automatic tests. Manual tests and connectivity checks remain available
when this option is disabled.

#### `periodic_test_interval_minutes`

Automatic test interval from 5 to 720 minutes. The first automatic test runs
one full interval after App startup. Use the MQTT button for an immediate test.

#### `server_ids`

Preferred Ookla server IDs in priority order. An empty list enables automatic
selection immediately.

Example:

```yaml
server_ids:
  - 38516
  - 70668
```

Use **Refresh server list** in the MQTT device, then inspect the attributes of
**Available Speedtest servers** to find IDs, providers and locations.

#### `automatic_server_fallback`

When enabled, automatic Ookla server selection is attempted after every
configured server ID fails.

#### `speedtest_timeout_seconds`

Maximum runtime of each individual Ookla test attempt.

#### `connectivity_check.interval_seconds`

Interval between ICMP checks. Connectivity checks run independently from speed
tests.

#### `connectivity_check.attempts`

Number of ICMP echo requests sent to each target during one check.

#### `connectivity_check.timeout_seconds`

Timeout of each ICMP echo request.

#### `expire_after_seconds`

Controls when download, upload, ping, jitter and packet loss become unavailable
without a new test. Set to `0` to disable measurement expiry.

#### `log_level`

Supported values: `debug`, `info`, `warning`, `error`.

### MQTT contract

Base topic:

```text
DigitalHouses/Global/speedtest
```

Topics:

```text
DigitalHouses/Global/speedtest/state
DigitalHouses/Global/speedtest/connectivity
DigitalHouses/Global/speedtest/servers
DigitalHouses/Global/speedtest/command
DigitalHouses/Global/speedtest/availability
```

Commands:

```text
RUN
REFRESH_SERVERS
```

### Connectivity policy

The App publishes separate connectivity binary sensors for:

- Google Public DNS: `8.8.8.8`
- Cloudflare DNS: `1.1.1.1`

A Speedtest runs when at least one target responds. When both targets are
unreachable, the test is skipped, the status changes to `No connectivity`, and
previous measurements are preserved.

ICMP reachability is a practical availability signal but is not a complete test
of DNS resolution, HTTP access, or every possible internet route.

### Recorder package

Copy:

```text
examples/packages/internet_speedtest_package.yaml
```

to:

```text
/config/packages/internet_speedtest_package.yaml
```

Confirm that `/config/configuration.yaml` contains a packages loader, for
example:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Do not create a second `homeassistant:` key if one already exists.

### Persistent files

```text
/data/state.json
/data/servers.json
/data/.config/
```

### Troubleshooting

#### MQTT service information is incomplete

Confirm that an MQTT broker App is installed, running, and exposes the Home
Assistant MQTT service.

#### Both connectivity sensors are off

Check routing, firewall rules and whether ICMP traffic to both public DNS
addresses is blocked.

#### A configured server fails

Enable automatic fallback or refresh the nearby server list and replace the
server ID.

#### Existing entities show old names

Home Assistant preserves user-customized entity names. The App keeps the same
unique IDs for migration, so previously renamed entities are not overwritten.

---

## Русский

### Установка из репозитория DigitalHouses

1. Убедитесь, что MQTT broker установлен и работает.
2. Откройте **Настройки → Дополнения → Магазин дополнений**.
3. Откройте меню в правом верхнем углу и выберите **Репозитории**.
4. Добавьте:

   ```text
   https://github.com/DigitalHouses/home-assistant-apps
   ```

5. Установите **DigitalHouses Speedtest**.
6. Проверьте и сохраните конфигурацию.
7. Запустите приложение.
8. Откройте журнал и убедитесь, что MQTT подключён, а проверки доступности работают.

При миграции с LXC-прототипа сначала остановите LXC-сервисы, поскольку обе
реализации используют одинаковый MQTT-контракт.

### Настройки

#### `periodic_test_enabled`

Включает автоматические замеры. Ручной запуск и проверки доступности работают
даже при выключенном параметре.

#### `periodic_test_interval_minutes`

Период автоматических тестов от 5 до 720 минут. Первый автоматический тест
выполняется через полный интервал после запуска приложения. Для немедленного
теста используйте MQTT-кнопку.

#### `server_ids`

Предпочтительные ID серверов Ookla в порядке приоритета. Пустой список означает
автоматический выбор сервера.

Пример:

```yaml
server_ids:
  - 38516
  - 70668
```

Нажмите **Refresh server list** в MQTT-устройстве, затем откройте атрибуты
**Available Speedtest servers** и скопируйте нужные ID.

#### `automatic_server_fallback`

После отказа всех указанных серверов разрешает автоматический выбор Ookla.

#### `speedtest_timeout_seconds`

Максимальное время одной попытки Ookla Speedtest.

#### `connectivity_check.interval_seconds`

Интервал между ICMP-проверками. Они выполняются независимо от замеров скорости.

#### `connectivity_check.attempts`

Количество ICMP-запросов к каждому адресу за одну проверку.

#### `connectivity_check.timeout_seconds`

Тайм-аут одного ICMP-запроса.

#### `expire_after_seconds`

Через сколько секунд без нового теста сущности скорости становятся unavailable.
Значение `0` отключает срок действия.

#### `log_level`

Допустимые значения: `debug`, `info`, `warning`, `error`.

### MQTT-контракт

Базовый topic:

```text
DigitalHouses/Global/speedtest
```

Topics:

```text
DigitalHouses/Global/speedtest/state
DigitalHouses/Global/speedtest/connectivity
DigitalHouses/Global/speedtest/servers
DigitalHouses/Global/speedtest/command
DigitalHouses/Global/speedtest/availability
```

Команды:

```text
RUN
REFRESH_SERVERS
```

### Логика доступности интернета

Публикуются два отдельных binary sensor:

- Google Public DNS: `8.8.8.8`
- Cloudflare DNS: `1.1.1.1`

Speedtest запускается, если отвечает хотя бы один адрес. Если недоступны оба,
тест пропускается, статус становится `No connectivity`, а предыдущие результаты
сохраняются.

ICMP-доступность — практический индикатор, но она не проверяет DNS-разрешение,
HTTP-доступ и все возможные интернет-маршруты.

### Пакет Recorder

Скопируйте:

```text
examples/packages/internet_speedtest_package.yaml
```

в:

```text
/config/packages/internet_speedtest_package.yaml
```

Убедитесь, что в `/config/configuration.yaml` подключена папка packages,
например:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Если раздел `homeassistant:` уже существует, второй раздел создавать нельзя.

### Постоянные файлы

```text
/data/state.json
/data/servers.json
/data/.config/
```

### Диагностика

#### Не получены параметры MQTT

Убедитесь, что MQTT broker установлен, запущен и предоставляет MQTT-сервис
Home Assistant Supervisor.

#### Оба connectivity sensor выключены

Проверьте маршрутизацию, firewall и доступность ICMP к обоим публичным DNS.

#### Указанный сервер не работает

Включите automatic fallback либо обновите список ближайших серверов и замените ID.

#### Сущности показывают старые названия

Home Assistant сохраняет пользовательские названия. Приложение использует те же
unique ID для миграции и не перезаписывает ранее изменённые имена.
