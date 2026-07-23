# DigitalHouses Speedtest

A Home Assistant App that runs the official native Ookla Speedtest CLI and
publishes one MQTT device through Home Assistant MQTT Discovery.

## English

### Why this App exists

The legacy Home Assistant Speedtest.net API/integration approach behaved
unreliably in the environment where this project was developed. Tests could
fail, return inconsistent data, or behave differently from the official
Speedtest applications.

This App therefore uses the official native Ookla Speedtest CLI instead of the
legacy API implementation. Around the official CLI, it adds MQTT Discovery,
persistent state, internet reachability monitoring, scheduled execution,
manual execution, preferred-server selection, and nearby-server discovery.

### Main features

- Official Ookla Speedtest CLI 1.2.0
- Download, upload, ping, jitter, packet loss, ISP, public IP and result URL
- One MQTT device created through Home Assistant MQTT Discovery
- Manual speed-test button
- Optional scheduled tests every 5 to 720 minutes
- ICMP checks to `8.8.8.8` and `1.1.1.1`
- Automatic suppression of Speedtest when both targets are unreachable
- Preferred Ookla server IDs with optional automatic fallback
- Nearby-server list with provider, location and server ID
- Persistent state in `/data`
- Automatic MQTT service configuration through Home Assistant Supervisor
- Migration-compatible MQTT topics and unique IDs from the original LXC prototype

### Supported architecture

- `amd64`

The source includes an `aarch64` Ookla download path, but public ARM64 support
will be declared only after a real Home Assistant ARM64 test or a verified
multi-architecture build pipeline.

### Migration from the LXC prototype

Do not run the original LXC service and this App at the same time. Both publish
to the same MQTT topics.

The App intentionally retains the original MQTT base topic, device identifier,
and existing entity unique IDs. Home Assistant should therefore reuse existing
entities, dashboards and Recorder history.

### Recorder package

An optional package is provided at:

```text
examples/packages/internet_speedtest_package.yaml
```

Copy it to:

```text
/config/packages/internet_speedtest_package.yaml
```

It explicitly includes the Speedtest entities in Recorder for history,
diagnostics and later analysis.

### Ookla license notice

This project downloads and runs the official proprietary Ookla Speedtest CLI.
The Ookla package describes the CLI as intended for personal, non-commercial
use. Users are responsible for reviewing and complying with Ookla's license,
terms of use and privacy policy.

The MIT license in this repository applies only to the DigitalHouses source
code and does not relicense or redistribute Ookla software.

---

## Русский

Это приложение Home Assistant запускает официальный нативный Ookla Speedtest
CLI и публикует одно MQTT-устройство через Home Assistant MQTT Discovery.

### Зачем создано это приложение

Старый подход через Speedtest.net API/интеграцию Home Assistant в среде, где
разрабатывался проект, работал нестабильно. Тесты могли завершаться ошибками,
возвращать непоследовательные данные или отличаться от результатов официальных
приложений Speedtest.

Поэтому приложение использует официальный нативный Ookla Speedtest CLI. Вокруг
него реализованы MQTT Discovery, постоянное хранение состояния, контроль
доступности интернета, периодический и ручной запуск, выбор предпочтительных
серверов и получение списка ближайших серверов.

### Основные возможности

- официальный Ookla Speedtest CLI 1.2.0;
- download, upload, ping, jitter, packet loss, провайдер, внешний IP и URL результата;
- одно MQTT-устройство в Home Assistant;
- кнопка ручного запуска;
- периодические тесты с интервалом от 5 до 720 минут;
- ICMP-проверки `8.8.8.8` и `1.1.1.1`;
- запрет запуска Speedtest, когда оба адреса недоступны;
- список предпочтительных ID серверов с автоматическим fallback;
- список ближайших серверов с провайдером, городом и ID;
- постоянное состояние в `/data`;
- автоматическое получение параметров MQTT через Supervisor;
- совместимость с MQTT topics и unique ID исходного LXC-прототипа.

### Поддерживаемая архитектура

- `amd64`

В исходном коде предусмотрена загрузка Ookla для `aarch64`, но публичная
поддержка ARM64 будет объявлена только после реального теста на Home Assistant
ARM64 либо после проверенной multi-architecture сборки.

### Миграция с LXC-прототипа

Не запускайте старый LXC-сервис и это приложение одновременно: они публикуют
данные в одинаковые MQTT topics.

Сохранены исходные MQTT base topic, идентификатор устройства и unique ID
сущностей. Home Assistant должен использовать существующие сущности, панели и
историю Recorder.

### Пакет Recorder

Дополнительный пакет находится здесь:

```text
examples/packages/internet_speedtest_package.yaml
```

Его нужно скопировать в:

```text
/config/packages/internet_speedtest_package.yaml
```

Пакет явно включает сущности Speedtest в Recorder для истории, диагностики и
последующего анализа.

### Лицензия Ookla

Проект загружает и запускает официальный проприетарный Ookla Speedtest CLI.
Ookla указывает, что CLI предназначен для личного некоммерческого использования.
Пользователь самостоятельно отвечает за соблюдение лицензии, условий
использования и политики конфиденциальности Ookla.

Лицензия MIT в этом репозитории относится только к исходному коду DigitalHouses
и не меняет лицензию программного обеспечения Ookla.
