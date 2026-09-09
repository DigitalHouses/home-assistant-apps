# DigitalHouses Applications

A collection of Home Assistant OS Apps and native Linux agents maintained by DigitalHouses.

Repository URL:

```text
https://github.com/DigitalHouses/home-assistant-apps
```

## Development standard / Стандарт разработки

All `digitalhouses_*` applications in this repository are governed by the
[DigitalHouses Application Standard v1](docs/DIGITALHOUSES_APP_STANDARD.md).

Все приложения семейства `digitalhouses_*` в этом репозитории разрабатываются по
[DigitalHouses Application Standard v1](docs/DIGITALHOUSES_APP_STANDARD.md).

---

# English

## Application types

This repository contains two application types:

- **HAOS Apps** — installed through the Home Assistant App Store from this repository;
- **Linux Agents** — native applications installed directly on a Linux VM, LXC, or host.

## HAOS Apps

### DigitalHouses Speedtest

Internet availability monitoring and scheduled speed tests using the official Ookla Speedtest CLI.

Key features:

- download, upload, ping, jitter, and packet loss;
- independent internet connectivity checks;
- manual and periodic tests;
- configurable quality thresholds;
- preferred Ookla server selection;
- problem binary sensors;
- Home Assistant MQTT Discovery;
- reusable Internet package and Lovelace dashboard examples.

Documentation:

- [Speedtest README](digitalhouses_speedtest/README.md)
- [Speedtest documentation](digitalhouses_speedtest/DOCS.md)
- [Internet global package](digitalhouses_speedtest/examples/packages/dh_app_speedtest_internet_global_package.yaml)
- [Lovelace dashboard](digitalhouses_speedtest/examples/lovelace/dh_app_speedtest_dashboard.yaml)

### DigitalHouses DB Monitoring / DH Recorder Monitor

Monitoring for the Home Assistant Recorder database through MQTT Discovery.

Key features:

- PostgreSQL and MariaDB support;
- database size and history-depth monitoring;
- Recorder write-activity monitoring;
- record-count and write-rate metrics;
- database connection diagnostics;
- one reusable MQTT device instead of multiple manual SQL sensors.

Documentation:

- [DB Monitoring README](digitalhouses_db_monitoring/README.md)

## Installing HAOS Apps

1. Open **Settings → Apps → App store** in Home Assistant.
2. Open the menu in the upper-right corner.
3. Select **Repositories**.
4. Add:

   ```text
   https://github.com/DigitalHouses/home-assistant-apps
   ```

5. Close the repository dialog.
6. Find the required DigitalHouses App and install it.

## Linux Agents

### DigitalHouses Plex Monitoring

Native Linux workload, playback, and library monitoring for Plex Media Server with Home Assistant MQTT Device Discovery.

Key features:

- runs directly inside a Plex VM, LXC, or Linux host;
- Plex process workload and CPU monitoring;
- scanner, intro, credits, thumbnail, and transcoder activity classification;
- local Plex API playback monitoring;
- Direct Play, Direct Stream, and Transcode context;
- Plex library discovery and counters;
- adaptive MQTT publishing to reduce Recorder noise;
- systemd service and idempotent Git-based installation/update;
- Lovelace dashboard example.

Documentation:

- [Plex Monitoring README](digitalhouses_plex_monitoring/README.md)
- [Plex Monitoring dashboard](digitalhouses_plex_monitoring/examples/lovelace/plex-dashboard.yaml)

Install or update on the Plex Linux host:

```bash
curl -fsSL https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/main/digitalhouses_plex_monitoring/install.sh | sudo bash
```

Run the same command again to update from `main`. Existing production configuration is preserved.

---

# Русский

## Типы приложений

В репозитории используются два типа приложений:

- **HAOS Apps** — устанавливаются через магазин приложений Home Assistant из этого репозитория;
- **Linux Agents** — нативные приложения, устанавливаемые непосредственно в Linux VM, LXC или на Linux-хост.

## HAOS Apps

### DigitalHouses Speedtest

Контроль доступности интернета и периодические измерения скорости с официальным Ookla Speedtest CLI.

Основные возможности:

- download, upload, ping, jitter и packet loss;
- независимые проверки доступности интернета;
- ручные и периодические тесты;
- настраиваемые пороги качества;
- выбор приоритетных серверов Ookla;
- problem binary sensors;
- Home Assistant MQTT Discovery;
- reusable Internet package и пример Lovelace dashboard.

Документация:

- [README Speedtest](digitalhouses_speedtest/README.md)
- [Подробная документация Speedtest](digitalhouses_speedtest/DOCS.md)
- [Глобальный Internet package](digitalhouses_speedtest/examples/packages/dh_app_speedtest_internet_global_package.yaml)
- [Lovelace dashboard](digitalhouses_speedtest/examples/lovelace/dh_app_speedtest_dashboard.yaml)

### DigitalHouses DB Monitoring / DH Recorder Monitor

Мониторинг базы данных Home Assistant Recorder через MQTT Discovery.

Основные возможности:

- PostgreSQL и MariaDB;
- размер базы и глубина истории;
- контроль записи Recorder;
- количество записей и интенсивность записи;
- диагностика подключения к базе данных;
- одно переиспользуемое MQTT-устройство вместо множества ручных SQL-сенсоров.

Документация:

- [README DB Monitoring](digitalhouses_db_monitoring/README.md)

## Установка HAOS Apps

1. Откройте **Настройки → Дополнения → Магазин дополнений**.
2. Откройте меню в правом верхнем углу.
3. Выберите **Репозитории**.
4. Добавьте:

   ```text
   https://github.com/DigitalHouses/home-assistant-apps
   ```

5. Закройте окно репозиториев.
6. Найдите нужное приложение DigitalHouses и установите его.

## Linux Agents

### DigitalHouses Plex Monitoring

Нативный Linux-agent для мониторинга нагрузки, воспроизведения и библиотек Plex Media Server с Home Assistant MQTT Device Discovery.

Основные возможности:

- установка непосредственно в Plex VM, LXC или Linux-хост;
- мониторинг Plex-процессов и CPU;
- классификация scanner, intro, credits, thumbnail и transcoder activity;
- локальный Plex API для мониторинга воспроизведения;
- Direct Play, Direct Stream и Transcode context;
- обнаружение Plex-библиотек и их счётчиков;
- адаптивная публикация MQTT для уменьшения шума в Recorder;
- systemd service и идемпотентная установка/обновление из Git;
- пример Lovelace dashboard.

Документация:

- [README Plex Monitoring](digitalhouses_plex_monitoring/README.md)
- [Dashboard Plex Monitoring](digitalhouses_plex_monitoring/examples/lovelace/plex-dashboard.yaml)

Установка или обновление на Linux-хосте Plex:

```bash
curl -fsSL https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/main/digitalhouses_plex_monitoring/install.sh | sudo bash
```

Повторный запуск той же команды обновляет приложение из `main`. Существующий production `.conf` сохраняется.

---

## Repository structure

```text
home-assistant-apps/
├── .github/
│   └── workflows/
├── digitalhouses_db_monitoring/       # HAOS App
├── digitalhouses_plex_monitoring/     # Linux Agent
├── digitalhouses_speedtest/           # HAOS App
├── docs/
├── scripts/
│   └── validators/
├── LICENSE
├── README.md
└── repository.yaml
```

## Support the project

DigitalHouses projects are developed independently and provided free of charge.

If this project is useful to you, you can support continued development, testing, maintenance, and documentation:

[![Support DigitalHouses on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/digitalhouses)

Support is entirely optional. All public features remain available to everyone.

## License

DigitalHouses source code is licensed under the MIT License.
Third-party software retains its own license terms.
